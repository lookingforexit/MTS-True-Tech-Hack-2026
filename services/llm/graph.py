"""LangGraph workflow for the simplified multi-agent LLM pipeline.

Pipeline stages:
    1. Prepare context — pass raw JSON context directly (no introspection)
    2. Spec-agent       — normalize user request + context into JSON spec
    3. Clarifier-agent  — approve spec or ask one clarification question
    4. Generator-agent  — produce Lua code
    5. Validator        — run code; if fails → generator retries (up to MAX_REPAIRS)
    6. Done             — return code immediately
"""

import json
import logging
import os
import re

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import START, StateGraph

from prompts import (
    CLARIFIER_AGENT_PROMPT,
    SPEC_AGENT_PROMPT,
    make_generate_prompt,
    make_repair_prompt,
)
from state import PipelineState
from validator_client import LuaValidatorClient

logger = logging.getLogger(__name__)

MODEL = "qwen2.5-coder:7b-instruct-q4_K_M"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST")
MAX_REPAIRS = 2

_llm_zero = ChatOllama(
    model=MODEL,
    base_url=OLLAMA_HOST,
    temperature=0.2,
    num_predict=256,
    num_ctx=4096,
)

_llm_generate = ChatOllama(
    model=MODEL,
    base_url=OLLAMA_HOST,
    temperature=0.8,
    num_predict=512,
    num_ctx=4096,
)

_validator = LuaValidatorClient(
    host=os.environ.get("LUA_VALIDATOR_HOST", "lua-validator"),
    port=int(os.environ.get("LUA_VALIDATOR_PORT", "50052")),
)


def detect_language(text: str) -> str:
    """Detect whether *text* is predominantly Russian or English."""
    cyrillic = sum(1 for ch in text if "\u0400" <= ch <= "\u04FF")
    latin = sum(1 for ch in text if "\u0041" <= ch <= "\u005A"
                                     or "\u0061" <= ch <= "\u007A")
    return "ru" if cyrillic >= latin else "en"


def _extract_code(text: str) -> str:
    """Extract raw Lua code, tolerant of markdown fences as fallback."""
    m = re.search(r"```lua\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def _parse_json_response(text: str) -> dict:
    """Parse a JSON response, stripping fences if present."""
    stripped = text.strip()
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", stripped, re.DOTALL)
    if m:
        stripped = m.group(1).strip()
    return json.loads(stripped)


# ── Nodes ──────────────────────────────────────────────────────────────

def extract_context_node(state: PipelineState) -> PipelineState:
    """Pass raw context through — no introspection needed."""
    context_json = state.get("context")
    if not context_json:
        logger.info("No context provided, skipping")
        return {"raw_context": None}

    # Validate it's proper JSON
    try:
        parsed = json.loads(context_json)
        logger.info("Context provided (%d bytes), passing through", len(context_json))
        return {"raw_context": parsed}
    except json.JSONDecodeError as e:
        logger.warning("Context is not valid JSON: %s", e)
        return {"raw_context": None}


def spec_node(state: PipelineState) -> PipelineState:
    """Spec-agent: normalize user request + context into JSON spec."""
    request = state["request"]
    raw_context = state.get("raw_context")

    user_text = f"Request: {request}"
    if raw_context:
        context_str = json.dumps(raw_context, ensure_ascii=False, indent=2)
        user_text += f"\n\nLua context:\n{context_str}"
    elif state.get("context"):
        user_text += f"\n\nAdditional context: {state['context']}"

    messages = [
        SystemMessage(content=SPEC_AGENT_PROMPT),
        HumanMessage(content=user_text),
    ]

    # ── DEBUG: log agent input/output ──
    logger.info("═══════════════════════════════════════════════════════")
    logger.info("[SPEC AGENT] INPUT:\n%s", user_text)
    # ──────────────────────────────────────────────────────────────────

    response = _llm_zero.invoke(messages)
    text = response.content

    # ── DEBUG: log agent output ──
    logger.info("[SPEC AGENT] OUTPUT:\n%s", text)
    logger.info("═══════════════════════════════════════════════════════")
    # ──────────────────────────────────────────────────────────────────

    try:
        spec = _parse_json_response(text)
        spec_json = json.dumps(spec, ensure_ascii=False)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Spec-agent did not return valid JSON: %s — %s", text, e)
        # Fallback: create a minimal spec
        spec = {
            "goal": request,
            "input_path": "wf.vars",
            "output_type": "return_value",
            "transformation": "as requested by user",
            "edge_cases": [],
            "need_clarification": False,
            "clarification_reason": None,
        }
        spec_json = json.dumps(spec, ensure_ascii=False)

    logger.info("Spec generated: %s", spec.get("goal", "unknown"))
    return {
        "spec_json": spec_json,
    }


def clarifier_node(state: PipelineState) -> PipelineState:
    """Clarifier-agent: review spec and approve or ask one question."""
    # If user already answered a clarification, skip re-asking.
    if state.get("clarification_answer"):
        return {"is_ambiguous": False, "spec_approved": True}

    spec_json = state.get("spec_json", "")
    dialog_language = state.get("dialog_language", "en")

    user_text = f"Specification:\n{spec_json}\n\ndialog_language: {dialog_language}"

    messages = [
        SystemMessage(content=CLARIFIER_AGENT_PROMPT),
        HumanMessage(content=user_text),
    ]

    # ── DEBUG: log agent input/output ──
    logger.info("═══════════════════════════════════════════════════════")
    logger.info("[CLARIFIER AGENT] INPUT:\n%s", user_text)
    # ──────────────────────────────────────────────────────────────────

    response = _llm_zero.invoke(messages)
    text = response.content

    # ── DEBUG: log agent output ──
    logger.info("[CLARIFIER AGENT] OUTPUT:\n%s", text)
    logger.info("═══════════════════════════════════════════════════════")
    # ──────────────────────────────────────────────────────────────────

    try:
        parsed = _parse_json_response(text)
        status = parsed.get("status", "approved")
        question = parsed.get("question")
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Clarifier did not return valid JSON: %s — %s", text, e)
        status = "approved"
        question = None

    if status == "question" and question:
        logger.info("Clarifier asks: %s", question)
        return {
            "is_ambiguous": True,
            "clarification_question": question,
            "spec_approved": False,
        }

    logger.info("Clarifier approved the spec")
    return {"is_ambiguous": False, "spec_approved": True}


def generate_node(state: PipelineState) -> PipelineState:
    """Generator-agent: produce Lua code from the spec.

    If this is a retry (generation_attempt > 0), include validation error info.
    """
    spec_json = state.get("spec_json", "")
    dialog_language = state.get("dialog_language", "en")
    attempt = state.get("generation_attempt", 0) + 1

    if attempt > 1:
        # Repair mode — include validation feedback
        validation_error = state.get("validation_error") or "unknown error"
        validation_output = state.get("validation_output") or ""
        prev_code = state.get("code") or ""

        user_text = (
            f"Specification:\n{spec_json}\n\n"
            f"Previous code (failed validation):\n{prev_code}\n\n"
            f"Validation error: {validation_error}\n"
            f"Validation output: {validation_output}\n\n"
            f"Fix the code. Return ONLY raw Lua code, no markdown fences."
        )
        system_prompt = make_repair_prompt(dialog_language)
    else:
        # First attempt — fresh generation
        user_text = f"Specification:\n{spec_json}"
        system_prompt = make_generate_prompt(dialog_language)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_text),
    ]

    # ── DEBUG: log agent input/output ──
    logger.info("═══════════════════════════════════════════════════════")
    logger.info("[GENERATOR AGENT] INPUT (attempt %d):\n%s", attempt, user_text)
    # ──────────────────────────────────────────────────────────────────

    response = _llm_generate.invoke(messages)
    code = _extract_code(response.content)

    # ── DEBUG: log agent output ──
    logger.info("[GENERATOR AGENT] OUTPUT:\n%s", code)
    logger.info("═══════════════════════════════════════════════════════")
    # ──────────────────────────────────────────────────────────────────

    logger.info("Generated code (attempt %d, %d chars)", attempt, len(code))
    return {
        "code": code,
        "generation_attempt": attempt,
    }


def validate_node(state: PipelineState) -> PipelineState:
    """Validator: run the generated code in lua-validator."""
    code = state.get("code") or ""
    context_json = state.get("context") or ""

    # Build env_vars with CONTEXT_JSON so the sandbox can populate `wf`
    if context_json:
        env_vars = json.dumps({"CONTEXT_JSON": context_json})
    else:
        env_vars = "{}"

    # ── DEBUG: log validation request ──
    logger.info("═══════════════════════════════════════════════════════")
    logger.info("[VALIDATOR] INPUT:\n%s", code)
    logger.info("[VALIDATOR] env_vars: %s", env_vars)
    # ──────────────────────────────────────────────────────────────────

    try:
        result = _validator.validate(code, env_vars=env_vars)
        success = result.success
        output = result.output or ""
        error = result.error or ""

        # ── DEBUG: log validation result ──
        logger.info("[VALIDATOR] OUTPUT (success=%s):\n%s", success, output)
        if error:
            logger.info("[VALIDATOR] ERROR:\n%s", error)
        logger.info("═══════════════════════════════════════════════════════")
        # ──────────────────────────────────────────────────────────────────

        logger.info(
            "Validation: success=%s, output_len=%d, error_len=%d",
            success, len(output), len(error),
        )
        return {
            "validation_success": success,
            "validation_output": output,
            "validation_error": error,
        }
    except Exception as e:
        logger.exception("Validation failed with exception")
        return {
            "validation_success": False,
            "validation_output": "",
            "validation_error": str(e),
        }


# ── Routing ──────────────────────────────────────────────────────────────

def route_after_clarifier(state: PipelineState) -> str:
    """After clarifier: if needs question → ask user; otherwise → generate."""
    if state.get("is_ambiguous"):
        return "clarification_needed"
    return "generate"


def route_after_validate(state: PipelineState) -> str:
    """After validate: if success → done; if repairs left → retry generate; else → done anyway."""
    if state.get("validation_success"):
        return "done"
    if state.get("generation_attempt", 0) <= MAX_REPAIRS:
        return "generate"
    # Even after max attempts, return whatever we have
    return "done"


# ── Build Graph ──────────────────────────────────────────────────────────

def build_graph():
    """Construct and compile the LangGraph workflow."""
    builder = StateGraph(PipelineState)

    # Add nodes
    builder.add_node("extract_context", extract_context_node)
    builder.add_node("spec", spec_node)
    builder.add_node("clarifier", clarifier_node)
    builder.add_node("generate", generate_node)
    builder.add_node("validate", validate_node)

    # Edges
    builder.add_edge(START, "extract_context")
    builder.add_edge("extract_context", "spec")
    builder.add_edge("spec", "clarifier")
    builder.add_conditional_edges("clarifier", route_after_clarifier, {
        "clarification_needed": "clarification_needed",
        "generate": "generate",
    })
    builder.add_edge("generate", "validate")
    builder.add_conditional_edges("validate", route_after_validate, {
        "done": "done",
        "generate": "generate",
    })

    # Terminal nodes
    builder.add_node("clarification_needed", lambda s: {"phase": "clarification_needed"})
    builder.add_node("done", lambda s: {"phase": "done"})
    builder.add_node("error", lambda s: {"phase": "error"})

    return builder.compile()


graph = build_graph()
