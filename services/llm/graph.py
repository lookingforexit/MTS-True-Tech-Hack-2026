"""LangGraph workflow for the deterministic LLM pipeline.

Uses proper LangGraph patterns:
- Each node returns a partial state update (TypedDict with only changed fields).
- Routing functions read state and return the next node name.
- temperature=0 for all LLM calls (deterministic).
"""

import json
import logging
import os
import re

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import START, StateGraph

from prompts import (
    CLARIFY_SYSTEM_PROMPT,
    make_generate_prompt,
    make_repair_prompt,
)
from state import PipelineState
from validator_client import LuaValidatorClient

logger = logging.getLogger(__name__)

MODEL = os.environ.get("LLM_MODEL", "qwen2.5-coder:1.5b-instruct-q4_K_M")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
MAX_REPAIRS = int(os.environ.get("MAX_REPAIRS", "2"))

# Deterministic LLM instances — temperature=0 for reproducibility.
_llm_zero = ChatOllama(
    model=MODEL,
    base_url=OLLAMA_HOST,
    temperature=0,
    num_predict=1024,
    num_ctx=4096,
)

_llm_generate = ChatOllama(
    model=MODEL,
    base_url=OLLAMA_HOST,
    temperature=0,
    num_predict=2048,
    num_ctx=4096,
)

_validator = LuaValidatorClient(
    host=os.environ.get("LUA_VALIDATOR_HOST", "lua-validator"),
    port=int(os.environ.get("LUA_VALIDATOR_PORT", "50052")),
)


# ── Helpers ──────────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """Detect whether *text* is predominantly Russian or English.

    Counts Cyrillic vs Latin code-points.  If Cyrillic count >= Latin count
    the language is ``"ru"``, otherwise ``"en"``.
    """
    cyrillic = sum(1 for ch in text if "\u0400" <= ch <= "\u04FF")
    latin = sum(1 for ch in text if "\u0041" <= ch <= "\u005A"
                                     or "\u0061" <= ch <= "\u007A")
    return "ru" if cyrillic >= latin else "en"


def _extract_code(text: str) -> str:
    """Extract raw Lua code, tolerant of markdown fences as fallback."""
    # Try fenced block first (model should NOT produce these, but be tolerant)
    m = re.search(r"```lua\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: return the whole response stripped
    return text.strip()


def _parse_clarify_json(text: str) -> dict:
    """Parse the clarify model's JSON response, stripping fences if present."""
    stripped = text.strip()
    # Strip markdown fences if the model added them despite instructions
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", stripped, re.DOTALL)
    if m:
        stripped = m.group(1).strip()
    return json.loads(stripped)


# ── Nodes ────────────────────────────────────────────────────────────────
# Each node returns a partial state update — only the fields that changed.

def clarify_node(state: PipelineState) -> PipelineState:
    """Check if the request is ambiguous.

    If a clarification_answer is already set the user has answered — skip
    straight to generation by returning ``is_ambiguous=False``.
    """
    if state.get("clarification_answer"):
        return {"is_ambiguous": False}

    request = state["request"]

    messages = [
        SystemMessage(content=CLARIFY_SYSTEM_PROMPT),
        HumanMessage(content=f"Request: {request}"),
    ]
    response = _llm_zero.invoke(messages)
    text = response.content

    try:
        parsed = _parse_clarify_json(text)
        is_ambiguous = bool(parsed.get("need_clarification", False))
        question = parsed.get("question")
    except (json.JSONDecodeError, KeyError):
        logger.warning("Clarify model did not return valid JSON: %s", text)
        is_ambiguous = False
        question = None

    if is_ambiguous and question:
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
    dialog_language = state.get("dialog_language", "en")

    user_text = f"Request: {request}"
    if context:
        user_text += f"\nContext: {context}"
    if answer:
        user_text += f"\nClarification answer: {answer}"

    messages = [
        SystemMessage(content=make_generate_prompt(dialog_language)),
        HumanMessage(content=user_text),
    ]
    response = _llm_generate.invoke(messages)
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
        full_output = (result.output or "") + (result.error or "")
        return {
            "validation_success": result.success,
            "validation_output": result.output,
            "validation_error": full_output if not result.success else "",
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
    dialog_language = state.get("dialog_language", "en")

    user_text = (
        f"Original request: {request}\n\n"
        f"Broken code:\n{code}\n\n"
        f"Validation errors:\n{errors}\n\n"
        f"Fix the code. Return ONLY raw Lua code, no markdown fences."
    )

    messages = [
        SystemMessage(content=make_repair_prompt(dialog_language)),
        HumanMessage(content=user_text),
    ]
    response = _llm_zero.invoke(messages)
    new_code = _extract_code(response.content)
    repair_count = state.get("repair_count", 0) + 1
    logger.info("Repaired code (%d chars), iteration %d", len(new_code), repair_count)
    return {"code": new_code, "repair_count": repair_count}


# ── Routing ──────────────────────────────────────────────────────────────

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


# ── Build Graph ──────────────────────────────────────────────────────────

def build_graph():
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
