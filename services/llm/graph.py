"""LangGraph workflow for the simplified multi-agent LLM pipeline.

Clarification resume path:
    START → update_spec → clarifier → generate → validate → …

The ``update_spec`` node is entered only when ``clarifying`` is True
(i.e. the user has answered a clarification question).  It rebuilds the
spec using the full clarification_history so that the answer actually
influences the generated code.
"""

from __future__ import annotations

import json
import logging
import os
import re

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import START, StateGraph

from context_normalizer import normalize_context_safe
from prompts import (
    CLARIFIER_AGENT_PROMPT,
    SPEC_AGENT_PROMPT,
    make_generate_prompt,
    make_repair_prompt,
)
from state import PipelineState
from checker_client import LuaCheckerClient
from validator_client import LuaValidatorClient

logger = logging.getLogger(__name__)

MODEL = "qwen2.5-coder:7b-instruct-q4_K_M"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST")
# Number of repair attempts allowed after the initial generation.
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
_checker = LuaCheckerClient(
    host=os.environ.get("LUA_CHECKER_HOST", "lua-checker"),
    port=int(os.environ.get("LUA_CHECKER_PORT", "50053")),
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


# ── Helpers ────────────────────────────────────────────────────────────

def _build_spec_user_text(
    request: str,
    raw_context: dict | None,
    context_raw: str | None,
    clarification_history: list[dict] | None,
) -> str:
    """Build the user message for the spec-agent.

    When *clarification_history* is non-empty the answers are appended so the
    LLM can incorporate them into the updated spec.
    """
    parts: list[str] = [f"Request: {request}"]

    if raw_context:
        parts.append(
            f"\n\nLua context:\n{json.dumps(raw_context, ensure_ascii=False, indent=2)}"
        )
    elif context_raw:
        parts.append(f"\n\nAdditional context: {context_raw}")

    if clarification_history:
        history_lines: list[str] = []
        for entry in clarification_history:
            q = entry.get("question", "")
            a = entry.get("answer", "")
            history_lines.append(f"Q: {q}\nA: {a}")
        parts.append(
            "\n\nClarification dialogue:\n" + "\n".join(history_lines)
        )

    return "\n".join(parts)


def _call_spec_agent(user_text: str) -> tuple[str, dict]:
    """Call the spec LLM and return ``(spec_json_string, parsed_dict)``.

    On parse failure a minimal fallback spec is returned.
    """
    messages = [
        SystemMessage(content=SPEC_AGENT_PROMPT),
        HumanMessage(content=user_text),
    ]

    logger.info("═══════════════════════════════════════════════════════")
    logger.info("[SPEC AGENT] INPUT:\n%s", user_text)

    response = _llm_zero.invoke(messages)
    text = response.content

    logger.info("[SPEC AGENT] OUTPUT:\n%s", text)
    logger.info("═══════════════════════════════════════════════════════")

    try:
        spec = _parse_json_response(text)
        return json.dumps(spec, ensure_ascii=False), spec
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Spec-agent did not return valid JSON: %s — %s", text, e)
        fallback = {
            "goal": "unknown",
            "input_path": "wf.vars",
            "output_type": "return_value",
            "transformation": "as requested by user",
            "edge_cases": [],
            "need_clarification": False,
            "clarification_reason": None,
        }
        return json.dumps(fallback, ensure_ascii=False), fallback


# Nodes

def extract_context_node(state: PipelineState) -> PipelineState:
    """Pass raw context through — no introspection needed."""
    context_json = state.get("context")
    if not context_json:
        logger.info("No context provided, skipping")
        return {"raw_context": None}

    try:
        parsed = json.loads(context_json)
        logger.info("Context provided (%d bytes), passing through", len(context_json))
        return {"raw_context": parsed}
    except json.JSONDecodeError as e:
        logger.warning("Context is not valid JSON: %s", e)
        return {"raw_context": None}


def spec_node(state: PipelineState) -> PipelineState:
    user_text = _build_spec_user_text(
        request=state["request"],
        raw_context=state.get("raw_context"),
        context_raw=state.get("context"),
        clarification_history=None,          # first run — no history yet
    )
    spec_json_str, spec = _call_spec_agent(user_text)
    logger.info("Spec generated: %s", spec.get("goal", "unknown"))
    return {"spec_json": spec_json_str}


def update_spec_node(state: PipelineState) -> PipelineState:
    user_text = _build_spec_user_text(
        request=state["request"],
        raw_context=state.get("raw_context"),
        context_raw=state.get("context"),
        clarification_history=state.get("clarification_history") or [],
    )
    spec_json_str, spec = _call_spec_agent(user_text)
    logger.info("Spec updated: %s", spec.get("goal", "unknown"))
    return {
        "spec_json": spec_json_str,
        "clarification_answer": None,   # consumed
        "clarifying": False,             # consumed
    }


def clarifier_node(state: PipelineState) -> PipelineState:
    spec_json = state.get("spec_json", "")
    dialog_language = state.get("dialog_language", "en")

    user_text = f"Specification:\n{spec_json}\n\ndialog_language: {dialog_language}"

    messages = [
        SystemMessage(content=CLARIFIER_AGENT_PROMPT),
        HumanMessage(content=user_text),
    ]

    logger.info("═══════════════════════════════════════════════════════")
    logger.info("[CLARIFIER AGENT] INPUT:\n%s", user_text)

    response = _llm_zero.invoke(messages)
    text = response.content

    logger.info("[CLARIFIER AGENT] OUTPUT:\n%s", text)
    logger.info("═══════════════════════════════════════════════════════")

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
    return {
        "is_ambiguous": False,
        "clarification_question": None,
        "spec_approved": True,
    }


def generate_node(state: PipelineState) -> PipelineState:
    spec_json = state.get("spec_json", "")
    dialog_language = state.get("dialog_language", "en")
    attempt = state.get("generation_attempt", 0) + 1

    if attempt > 1:
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
        user_text = f"Specification:\n{spec_json}"
        system_prompt = make_generate_prompt(dialog_language)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_text),
    ]

    logger.info("═══════════════════════════════════════════════════════")
    logger.info("[GENERATOR AGENT] INPUT (attempt %d):\n%s", attempt, user_text)

    response = _llm_generate.invoke(messages)
    code = _extract_code(response.content)

    logger.info("[GENERATOR AGENT] OUTPUT:\n%s", code)
    logger.info("═══════════════════════════════════════════════════════")

    logger.info("Generated code (attempt %d, %d chars)", attempt, len(code))
    return {
        "code": code,
        "generation_attempt": attempt,
    }


def validate_node(state: PipelineState) -> PipelineState:
    code = state.get("code") or ""
    raw_context = state.get("context")
    normalised_context = normalize_context_safe(raw_context)

    env_vars = json.dumps({"CONTEXT_JSON": normalised_context})

    logger.info("═══════════════════════════════════════════════════════")
    logger.info("[CHECKER] INPUT:\n%s", code)

    try:
        check_result = _checker.check(code)
        checker_success = check_result.valid
        checker_output = "\n".join(check_result.violations or [])

        logger.info("[CHECKER] OUTPUT (success=%s):\n%s", checker_success, checker_output)
        if not checker_success:
            summary = (
                f"Static validation failed: {check_result.violations[0]}"
                if check_result.violations
                else "Static validation failed before runtime validation."
            )
            logger.info("═══════════════════════════════════════════════════════")
            return {
                "validation_success": False,
                "validation_output": checker_output,
                "validation_error": summary,
            }
    except Exception as e:
        logger.exception("Checker failed with exception")
        return {
            "validation_success": False,
            "validation_output": "",
            "validation_error": f"Lua checker unavailable: {e}",
        }

    logger.info("[VALIDATOR] INPUT:\n%s", code)
    logger.info("[VALIDATOR] env_vars: %s", env_vars)

    try:
        result = _validator.validate(code, env_vars=env_vars)
        success = result.success
        output = result.output or ""
        error = result.error or ""

        logger.info("[VALIDATOR] OUTPUT (success=%s):\n%s", success, output)
        if error:
            logger.info("[VALIDATOR] ERROR:\n%s", error)
        logger.info("═══════════════════════════════════════════════════════")

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



def route_entry(state: PipelineState) -> str:
    if state.get("clarifying"):
        return "update_spec"
    return "spec"


def route_after_clarifier(state: PipelineState) -> str:
    if state.get("is_ambiguous"):
        return "clarification_needed"
    return "generate"


def route_after_validate(state: PipelineState) -> str:
    if state.get("validation_success"):
        return "done"
    if state.get("generation_attempt", 0) <= MAX_REPAIRS:
        return "generate"
    return "error"


def build_graph():
    """Construct and compile the LangGraph workflow."""
    builder = StateGraph(PipelineState)

    # Nodes
    builder.add_node("extract_context", extract_context_node)
    builder.add_node("spec", spec_node)
    builder.add_node("update_spec", update_spec_node)
    builder.add_node("clarifier", clarifier_node)
    builder.add_node("generate", generate_node)
    builder.add_node("validate", validate_node)

    # Edges
    builder.add_edge(START, "extract_context")
    builder.add_conditional_edges("extract_context", route_entry, {
        "spec": "spec",
        "update_spec": "update_spec",
    })
    builder.add_edge("spec", "clarifier")
    builder.add_edge("update_spec", "clarifier")
    builder.add_conditional_edges("clarifier", route_after_clarifier, {
        "clarification_needed": "clarification_needed",
        "generate": "generate",
    })
    builder.add_edge("generate", "validate")
    builder.add_conditional_edges("validate", route_after_validate, {
        "done": "done",
        "generate": "generate",
        "error": "error",
    })

    # Terminal nodes
    builder.add_node("clarification_needed", lambda s: {"phase": "clarification_needed"})
    builder.add_node("done", lambda s: {"phase": "done"})

    def error_node(state: PipelineState) -> PipelineState:
        return {
            "phase": "error",
            "error": state.get("validation_error") or state.get("error") or "unknown error",
            "validation_error": state.get("validation_error"),
            "validation_output": state.get("validation_output"),
        }

    builder.add_node("error", error_node)

    return builder.compile()


graph = build_graph()
