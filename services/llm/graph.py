"""LangGraph workflow for the deterministic LLM pipeline."""

import logging
import os
import re

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from prompts import CLARIFY_SYSTEM_PROMPT, GENERATE_SYSTEM_PROMPT, REPAIR_SYSTEM_PROMPT
from state import PipelineState
from validator_client import LuaValidatorClient

logger = logging.getLogger(__name__)

MODEL = os.environ.get("LLM_MODEL", "qwen2.5-coder:7b-instruct-q5_0")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
MAX_REPAIRS = int(os.environ.get("MAX_REPAIRS", "2"))

_llm = ChatOllama(
    model=MODEL,
    base_url=OLLAMA_HOST,
    temperature=0.2,
    num_predict=4096,
)

_validator = LuaValidatorClient(
    host=os.environ.get("LUA_VALIDATOR_HOST", "lua-validator"),
    port=int(os.environ.get("LUA_VALIDATOR_PORT", "50052")),
)


def _extract_code(text: str) -> str:
    """Extract Lua code from markdown code blocks."""
    m = re.search(r"```lua\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


# ── Nodes ──────────────────────────────────────────────────────────────

def clarify_node(state: PipelineState) -> PipelineState:
    """Check if the request is ambiguous."""
    request = state["request"]
    if state.get("clarification_answer"):
        # User answered the question — skip clarify, go to generate.
        return {"is_ambiguous": False}

    messages = [
        SystemMessage(content=CLARIFY_SYSTEM_PROMPT),
        HumanMessage(content=f"Request: {request}"),
    ]
    response = _llm.invoke(messages)
    text = response.content.strip()

    is_ambiguous = "AMBIGUITY: true" in text
    question = None
    if is_ambiguous:
        q_match = re.search(r"QUESTION:\s*(.+)", text)
        question = q_match.group(1).strip() if q_match else None
        logger.info("Request is ambiguous. Question: %s", question)

    return {
        "is_ambiguous": is_ambiguous,
        "clarification_question": question,
    }


def generate_node(state: PipelineState) -> PipelineState:
    """Generate Lua code from the request."""
    request = state["request"]
    context = state.get("context") or ""
    answer = state.get("clarification_answer") or ""

    user_text = f"Request: {request}"
    if context:
        user_text += f"\nContext: {context}"
    if answer:
        user_text += f"\nClarification answer: {answer}"

    messages = [
        SystemMessage(content=GENERATE_SYSTEM_PROMPT),
        HumanMessage(content=user_text),
    ]
    response = _llm.invoke(messages)
    code = _extract_code(response.content)
    logger.info("Generated code (%d chars)", len(code))
    return {"code": code, "repair_count": 0}


def validate_node(state: PipelineState) -> PipelineState:
    """Run the generated code through the Lua Validator."""
    code = state.get("code", "")
    if not code:
        return {
            "validation_success": False,
            "validation_error": "No code to validate",
            "validation_output": "",
        }

    try:
        result = _validator.validate(code)
        logger.info(
            "Validation: success=%s exit=%d time=%dms",
            result.success, result.exit_code, result.exec_time_ms,
        )
        return {
            "validation_success": result.success,
            "validation_output": result.output,
            "validation_error": result.error if not result.success else "",
        }
    except Exception as e:
        logger.error("Validation RPC failed: %s", e)
        return {
            "validation_success": False,
            "validation_error": str(e),
            "validation_output": "",
        }


def repair_node(state: PipelineState) -> PipelineState:
    """Repair the code based on validation errors."""
    code = state.get("code", "")
    errors = state.get("validation_error", "")
    request = state["request"]

    user_text = (
        f"Original request: {request}\n\n"
        f"Broken code:\n```lua\n{code}\n```\n\n"
        f"Validation errors:\n{errors}\n\n"
        f"Fix the code."
    )

    messages = [
        SystemMessage(content=REPAIR_SYSTEM_PROMPT),
        HumanMessage(content=user_text),
    ]
    response = _llm.invoke(messages)
    new_code = _extract_code(response.content)
    repair_count = state.get("repair_count", 0) + 1
    logger.info("Repaired code (%d chars), iteration %d", len(new_code), repair_count)
    return {"code": new_code, "repair_count": repair_count}


# ── Routing ────────────────────────────────────────────────────────────

def route_after_clarify(state: PipelineState) -> str:
    """After clarify: if ambiguous → ask user; otherwise → generate."""
    if state.get("is_ambiguous"):
        return "clarification_needed"
    return "generate"


def route_after_validate(state: PipelineState) -> str:
    """After validate: if success → done; if failure and repairs left → repair; else → error."""
    if state.get("validation_success"):
        return "done"
    if state.get("repair_count", 0) < MAX_REPAIRS:
        return "repair"
    return "error"


def route_after_repair(state: PipelineState) -> str:
    """After repair: go back to validate."""
    return "validate"


# ── Build Graph ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Construct and compile the LangGraph workflow."""
    builder = StateGraph(PipelineState)

    # Add nodes
    builder.add_node("clarify", clarify_node)
    builder.add_node("generate", generate_node)
    builder.add_node("validate", validate_node)
    builder.add_node("repair", repair_node)

    # Edges
    builder.add_edge(START, "clarify")
    builder.add_conditional_edges("clarify", route_after_clarify, {
        "clarification_needed": "clarification_needed",
        "generate": "generate",
    })
    builder.add_edge("generate", "validate")
    builder.add_conditional_edges("validate", route_after_validate, {
        "done": "done",
        "repair": "repair",
        "error": "error",
    })
    builder.add_conditional_edges("repair", route_after_repair, {
        "validate": "validate",
    })

    # Terminal nodes (no-op, just mark phase)
    builder.add_node("clarification_needed", lambda s: {"phase": "clarification_needed"})
    builder.add_node("done", lambda s: {"phase": "done"})
    builder.add_node("error", lambda s: {"phase": "error"})

    return builder.compile()


graph = build_graph()
