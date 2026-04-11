"""LangGraph workflow for the multi-agent deterministic LLM pipeline.

Pipeline stages:
    1. Spec-agent       — normalize user request into JSON spec
    2. Clarifier-agent  — approve spec or ask one clarification question
    3. Test-agent       — generate test cases from spec
    4. Generator-agent  — produce N Lua candidates from spec
    5. Validator stack  — run tests against each candidate
    6. Repair-agent     — fix failing candidates (up to MAX_REPAIRS)
    7. Ranker           — pick best passing candidate (shortest, simplest)
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
    RANKER_PROMPT,
    SPEC_AGENT_PROMPT,
    TEST_AGENT_PROMPT,
    make_generate_prompt,
    make_repair_prompt,
)
from state import PipelineState
from validator_client import LuaValidatorClient

logger = logging.getLogger(__name__)

MODEL = os.environ.get("LLM_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
MAX_REPAIRS = int(os.environ.get("MAX_REPAIRS", "2"))
CANDIDATE_COUNT = int(os.environ.get("CANDIDATE_COUNT", "3"))

# Deterministic LLM instances — temperature=0 for reproducibility.
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
    num_predict=256,
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


def _run_candidate(code: str, tests: list[dict]) -> dict:
    """Run one candidate against all tests. Returns a CandidateResult dict."""
    failures = []
    passed = 0
    total = len(tests)

    for tc in tests:
        stdin = tc.get("stdin", "")
        expected = tc.get("expected_output", "")
        try:
            result = _validator.validate(code, stdin=stdin)
            actual_output = (result.output or "").strip()
            expected_stripped = expected.strip()
            if result.success and actual_output == expected_stripped:
                passed += 1
            else:
                failures.append({
                    "test_name": tc.get("name", ""),
                    "stdin": stdin,
                    "expected": expected,
                    "actual": result.output or "",
                    "error": result.error or "",
                })
        except Exception as e:
            failures.append({
                "test_name": tc.get("name", ""),
                "stdin": stdin,
                "expected": expected,
                "actual": "",
                "error": str(e),
            })

    all_passing = len(failures) == 0
    return {
        "all_passing": all_passing,
        "passed_tests": passed,
        "total_tests": total,
        "failures": failures,
        "char_count": len(code),
    }


# ── Nodes ────────────────────────────────────────────────────────────────

def spec_node(state: PipelineState) -> PipelineState:
    """Spec-agent: normalize user request into JSON spec."""
    request = state["request"]
    context = state.get("context") or ""

    user_text = f"Request: {request}"
    if context:
        user_text += f"\nAdditional context: {context}"

    messages = [
        SystemMessage(content=SPEC_AGENT_PROMPT),
        HumanMessage(content=user_text),
    ]
    response = _llm_zero.invoke(messages)
    text = response.content

    try:
        spec = _parse_json_response(text)
        spec_json = json.dumps(spec, ensure_ascii=False)
        missing = spec.get("missing_critical_fields", [])
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Spec-agent did not return valid JSON: %s — %s", text, e)
        # Fallback: create a minimal spec
        spec = {
            "task_type": "script",
            "goal": request,
            "input": {"source": "stdin", "format": "raw_text"},
            "output": {"type": "stdout", "format": "raw_text"},
            "constraints": ["standard_lua_5_4", "no_external_libs"],
            "assumptions": [],
            "need_clarification": False,
            "missing_critical_fields": [],
        }
        spec_json = json.dumps(spec, ensure_ascii=False)
        missing = []

    logger.info("Spec generated: %s", spec.get("goal", "unknown"))
    return {
        "spec_json": spec_json,
        "missing_critical_fields": missing,
    }


def clarifier_node(state: PipelineState) -> PipelineState:
    """Clarifier-agent: review spec and approve or ask one question."""
    # If user already answered a clarification, skip re-asking.
    if state.get("clarification_answer"):
        return {"is_ambiguous": False, "spec_approved": True}

    spec_json = state.get("spec_json", "")
    dialog_language = state.get("dialog_language", "en")

    user_text = f"Specification:\n{spec_json}"

    messages = [
        SystemMessage(content=CLARIFIER_AGENT_PROMPT),
        HumanMessage(content=f"{user_text}\n\ndialog_language: {dialog_language}"),
    ]
    response = _llm_zero.invoke(messages)
    text = response.content

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


def test_node(state: PipelineState) -> PipelineState:
    """Test-agent: generate test cases from the spec."""
    spec_json = state.get("spec_json", "")
    dialog_language = state.get("dialog_language", "en")

    messages = [
        SystemMessage(content=TEST_AGENT_PROMPT),
        HumanMessage(content=f"Specification:\n{spec_json}"),
    ]
    response = _llm_zero.invoke(messages)
    text = response.content

    try:
        parsed = _parse_json_response(text)
        tests = parsed.get("tests", [])
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Test-agent did not return valid JSON: %s — %s", text, e)
        # Fallback: minimal test
        tests = [
            {
                "name": "basic",
                "stdin": "",
                "expected_output": "",
                "description": "basic smoke test",
            }
        ]

    logger.info("Generated %d test cases", len(tests))
    return {"tests": tests}


def generate_node(state: PipelineState) -> PipelineState:
    """Generator-agent: produce N Lua candidates from the spec."""
    spec_json = state.get("spec_json", "")
    dialog_language = state.get("dialog_language", "en")
    n = CANDIDATE_COUNT

    candidates = []
    for i in range(n):
        user_text = (
            f"Specification:\n{spec_json}\n\n"
            f"Generate candidate {i + 1} of {n}. "
            f"Each candidate should be an independent solution."
        )

        messages = [
            SystemMessage(content=make_generate_prompt(dialog_language)),
            HumanMessage(content=user_text),
        ]
        response = _llm_generate.invoke(messages)
        code = _extract_code(response.content)

        candidates.append({
            "index": i,
            "code": code,
            "all_passing": False,
            "passed_tests": 0,
            "total_tests": 0,
            "failures": [],
            "char_count": len(code),
        })
        logger.info("Generated candidate %d (%d chars)", i, len(code))

    return {"candidates": candidates, "candidate_count": n}


def validate_node(state: PipelineState) -> PipelineState:
    """Validator stack: run all candidates against all tests."""
    candidates = state.get("candidates") or []
    tests = state.get("tests") or []

    any_passing = False
    for c in candidates:
        result = _run_candidate(c["code"], tests)
        c.update(result)
        if c["all_passing"]:
            any_passing = True
        logger.info(
            "Candidate %d: %d/%d tests passing, all_passing=%s",
            c["index"], c["passed_tests"], c["total_tests"], c["all_passing"],
        )

    return {
        "candidates": candidates,
        "validation_success": any_passing,
    }


def repair_node(state: PipelineState) -> PipelineState:
    """Repair-agent: fix failing candidates using test failure info."""
    candidates = state.get("candidates") or []
    spec_json = state.get("spec_json", "")
    dialog_language = state.get("dialog_language", "en")
    repair_count = state.get("repair_count", 0) + 1

    for c in candidates:
        if c.get("all_passing"):
            continue  # Skip already-passing candidates
        if not c.get("failures"):
            continue

        # Build failure summary
        failure_summary = "\n".join(
            f"Test '{f['test_name']}':\n"
            f"  stdin: {f['stdin']!r}\n"
            f"  expected: {f['expected']!r}\n"
            f"  actual: {f['actual']!r}\n"
            f"  error: {f['error']}"
            for f in c["failures"]
        )

        user_text = (
            f"Specification:\n{spec_json}\n\n"
            f"Broken code:\n{c['code']}\n\n"
            f"Failing tests:\n{failure_summary}\n\n"
            f"Fix the code. Return ONLY raw Lua code, no markdown fences."
        )

        messages = [
            SystemMessage(content=make_repair_prompt(dialog_language)),
            HumanMessage(content=user_text),
        ]
        response = _llm_zero.invoke(messages)
        new_code = _extract_code(response.content)
        c["code"] = new_code
        logger.info("Repaired candidate %d (%d chars), iteration %d", c["index"], len(new_code), repair_count)

    # Re-validate repaired candidates
    tests = state.get("tests") or []
    any_passing = False
    for c in candidates:
        result = _run_candidate(c["code"], tests)
        c.update(result)
        if c["all_passing"]:
            any_passing = True

    return {
        "candidates": candidates,
        "validation_success": any_passing,
        "repair_count": repair_count,
    }


def ranker_node(state: PipelineState) -> PipelineState:
    """Ranker: select the best candidate from all passing ones."""
    candidates = state.get("candidates") or []

    if not candidates:
        return {"code": "", "best_candidate_index": 0}

    # Separate passing and failing
    passing = [c for c in candidates if c.get("all_passing")]
    if passing:
        pool = passing
    else:
        # No passing candidates — pick the one with most passing tests
        pool = candidates

    # Sort by: most tests passed (desc), then shortest code (asc)
    pool.sort(key=lambda c: (-c.get("passed_tests", 0), c.get("char_count", 999999)))
    best = pool[0]

    logger.info(
        "Selected candidate %d (passing=%s, chars=%d)",
        best["index"], best["all_passing"], best["char_count"],
    )
    return {
        "code": best["code"],
        "best_candidate_index": best["index"],
    }


# ── Routing ──────────────────────────────────────────────────────────────

def route_after_spec(state: PipelineState) -> str:
    """After spec: always go to clarifier."""
    return "clarifier"


def route_after_clarifier(state: PipelineState) -> str:
    """After clarifier: if needs question → ask user; otherwise → test."""
    if state.get("is_ambiguous"):
        return "clarification_needed"
    return "test"


def route_after_validate(state: PipelineState) -> str:
    """After validate: if any passing → rank; if repairs left → repair; else → rank anyway."""
    if state.get("validation_success"):
        return "ranker"
    if state.get("repair_count", 0) < MAX_REPAIRS:
        return "repair"
    # Even if no candidates pass after all repairs, still rank to pick the best
    return "ranker"


def route_after_repair(state: PipelineState) -> str:
    """After repair: go back to validate."""
    return "validate"


# ── Build Graph ──────────────────────────────────────────────────────────

def build_graph():
    """Construct and compile the LangGraph workflow."""
    builder = StateGraph(PipelineState)

    # Add nodes
    builder.add_node("spec", spec_node)
    builder.add_node("clarifier", clarifier_node)
    builder.add_node("test", test_node)
    builder.add_node("generate", generate_node)
    builder.add_node("validate", validate_node)
    builder.add_node("repair", repair_node)
    builder.add_node("ranker", ranker_node)

    # Edges
    builder.add_edge(START, "spec")
    builder.add_edge("spec", "clarifier")
    builder.add_conditional_edges("clarifier", route_after_clarifier, {
        "clarification_needed": "clarification_needed",
        "test": "test",
    })
    builder.add_edge("test", "generate")
    builder.add_edge("generate", "validate")
    builder.add_conditional_edges("validate", route_after_validate, {
        "ranker": "ranker",
        "repair": "repair",
    })
    builder.add_edge("repair", "validate")
    builder.add_edge("ranker", "done")

    # Terminal nodes
    builder.add_node("clarification_needed", lambda s: {"phase": "clarification_needed"})
    builder.add_node("done", lambda s: {"phase": "done"})
    builder.add_node("error", lambda s: {"phase": "error"})

    return builder.compile()


graph = build_graph()
