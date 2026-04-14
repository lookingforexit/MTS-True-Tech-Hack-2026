"""Shared decision logic for spec extraction and clarification.

This module is the single source of truth for:
- final spec normalization
- clarification blocker detection
- clarification question generation
"""

from __future__ import annotations

import json
import re
from typing import Literal

from typing_extensions import TypedDict

INPUT_PATH_NOT_APPLICABLE = "__INPUT_PATH_NOT_APPLICABLE__"
INPUT_PATH_NEEDS_CLARIFICATION = "__INPUT_PATH_NEEDS_CLARIFICATION__"

ClarificationTarget = Literal["none", "goal", "return_value", "input_path"]

_GENERIC_GOALS = {
    "",
    "unknown",
    "not specified",
    "unspecified",
    "tbd",
    "todo",
    "?",
}

_GENERIC_RETURN_VALUES = {
    "",
    "return_value",
    "value",
    "result",
    "output",
    "single_value",
    "return the result",
    "returned value",
    "result value",
    "string",
    "number",
    "boolean",
    "table",
    "array",
    "object",
}

_IDENTIFIER_STOPWORDS = {
    "wf",
    "vars",
    "initvariables",
    "lua",
    "json",
    "table",
    "array",
    "object",
    "string",
    "value",
    "result",
    "return",
    "function",
    "code",
    "field",
    "fields",
    "element",
    "elements",
    "item",
    "items",
    "data",
    "context",
}


class NormalizedSpec(TypedDict):
    goal: str
    input_path: str
    output_type: str
    transformation: str
    return_value: str
    clarification_required: bool
    clarification_target: ClarificationTarget
    clarification_question: str | None
    need_clarification: bool
    clarification_reason: str | None


class ClarifierDecision(TypedDict):
    status: Literal["approved", "question"]
    question: str | None


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _flatten_context_paths(node: object, prefix: str = "wf") -> list[str]:
    paths = [prefix]
    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                continue
            child_path = f"{prefix}.{key}"
            paths.extend(_flatten_context_paths(value, child_path))
    elif isinstance(node, list):
        for item in node:
            paths.extend(_flatten_context_paths(item, prefix))
    return list(dict.fromkeys(paths))


def _extract_identifiers(text: str) -> list[str]:
    if not text:
        return []

    raw_identifiers = re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`|([A-Za-z_][A-Za-z0-9_]*)", text)
    identifiers: list[str] = []
    for pair in raw_identifiers:
        ident = pair[0] or pair[1]
        lowered = ident.lower()
        if lowered in _IDENTIFIER_STOPWORDS:
            continue
        identifiers.append(ident)
    return list(dict.fromkeys(identifiers))


def _candidate_parent_path(paths: list[str], identifiers: list[str]) -> str | None:
    if not identifiers:
        return None

    by_suffix: dict[str, list[str]] = {}
    for path in paths:
        suffix = path.split(".")[-1]
        by_suffix.setdefault(suffix, []).append(path)

    for ident in identifiers:
        matches = by_suffix.get(ident, [])
        concrete = [path for path in matches if path.count(".") >= 2]
        if len(concrete) == 1:
            return concrete[0]

    matched_parents: list[str] = []
    for ident in identifiers:
        for path in by_suffix.get(ident, []):
            if path.count(".") >= 3:
                matched_parents.append(path.rsplit(".", 1)[0])

    unique_parents = list(dict.fromkeys(matched_parents))
    if len(unique_parents) == 1 and len(matched_parents) >= 2:
        return unique_parents[0]

    return None


def resolve_input_path(
    *,
    request: str,
    raw_context: dict | None,
    raw_input_path: str,
    goal: str,
    transformation: str,
    return_value: str,
) -> str | None:
    if raw_input_path.startswith("wf.vars") or raw_input_path.startswith("wf.initVariables"):
        return raw_input_path

    if not raw_context:
        return None

    combined_text = " ".join(part for part in (request, goal, transformation, return_value, raw_input_path) if part)
    identifiers = _extract_identifiers(combined_text)
    if not identifiers:
        return None

    root = raw_context.get("wf") if isinstance(raw_context, dict) and "wf" in raw_context else raw_context
    paths = _flatten_context_paths(root)
    return _candidate_parent_path(paths, identifiers)


def _needs_contextual_input(request: str, raw_input_path: str) -> bool:
    if raw_input_path == INPUT_PATH_NEEDS_CLARIFICATION:
        return True
    if raw_input_path and not (
        raw_input_path.startswith("wf.vars") or raw_input_path.startswith("wf.initVariables")
    ):
        return True

    lowered = request.lower()
    identifier_count = len(_extract_identifiers(request))
    context_markers = (
        "используя",
        "объект",
        "массива",
        "массив ",
        "переменн",
        "context",
        "using",
        "object",
        "array",
        "variable",
    )
    return identifier_count > 0 and any(marker in lowered for marker in context_markers)


def _is_meaningful_goal(goal: str) -> bool:
    return goal.lower() not in _GENERIC_GOALS


def _is_meaningful_return_value(return_value: str) -> bool:
    lowered = return_value.lower()
    if lowered in _GENERIC_RETURN_VALUES:
        return False
    if lowered.startswith("result ") or lowered.startswith("return "):
        return False
    return bool(return_value)


def _build_question(target: ClarificationTarget, request: str, goal: str, dialog_language: str) -> str | None:
    if target == "none":
        return None

    is_ru = dialog_language == "ru"

    if target == "goal":
        return (
            "Что именно должен сделать итоговый Lua-код?"
            if is_ru
            else "What exactly should the final Lua code do?"
        )

    if target == "return_value":
        return (
            "Что именно должен возвращать итоговый Lua-код?"
            if is_ru
            else "What exactly should the final Lua code return?"
        )

    return (
        "Укажи точный путь к входным данным в контексте, например `wf.vars.users`."
        if is_ru
        else "Provide the exact path to the input data in context, for example `wf.vars.users`."
    )


def evaluate_spec(
    raw_spec: dict | None,
    *,
    request: str,
    raw_context: dict | None,
    dialog_language: str,
) -> NormalizedSpec:
    raw_spec = raw_spec or {}

    goal = _clean_text(raw_spec.get("goal"))
    input_path = _clean_text(raw_spec.get("input_path"))
    output_type = _clean_text(raw_spec.get("output_type")) or "return_value"
    transformation = _clean_text(raw_spec.get("transformation")) or "as requested by user"
    return_value = _clean_text(raw_spec.get("return_value"))

    if input_path == INPUT_PATH_NOT_APPLICABLE:
        normalized_input_path = INPUT_PATH_NOT_APPLICABLE
    else:
        resolved_path = resolve_input_path(
            request=request,
            raw_context=raw_context,
            raw_input_path=input_path,
            goal=goal,
            transformation=transformation,
            return_value=return_value,
        )
        if resolved_path:
            normalized_input_path = resolved_path
        elif input_path == INPUT_PATH_NOT_APPLICABLE:
            normalized_input_path = INPUT_PATH_NOT_APPLICABLE
        elif _needs_contextual_input(request, input_path):
            normalized_input_path = INPUT_PATH_NEEDS_CLARIFICATION
        else:
            normalized_input_path = INPUT_PATH_NOT_APPLICABLE

    clarification_target: ClarificationTarget = "none"
    clarification_reason: str | None = None

    if not _is_meaningful_goal(goal):
        clarification_target = "goal"
        clarification_reason = "goal"
    elif not _is_meaningful_return_value(return_value):
        clarification_target = "return_value"
        clarification_reason = "return_value"
    elif normalized_input_path == INPUT_PATH_NEEDS_CLARIFICATION:
        clarification_target = "input_path"
        clarification_reason = "input_path"

    clarification_required = clarification_target != "none"
    clarification_question = _build_question(
        clarification_target,
        request=request,
        goal=goal,
        dialog_language=dialog_language,
    )

    return {
        "goal": goal,
        "input_path": normalized_input_path,
        "output_type": output_type,
        "transformation": transformation,
        "return_value": return_value,
        "clarification_required": clarification_required,
        "clarification_target": clarification_target,
        "clarification_question": clarification_question,
        "need_clarification": clarification_required,
        "clarification_reason": clarification_reason,
    }


def load_spec_json(spec_json: str | None, *, request: str, raw_context: dict | None, dialog_language: str) -> NormalizedSpec:
    parsed = json.loads(spec_json) if spec_json else {}
    return evaluate_spec(
        parsed,
        request=request,
        raw_context=raw_context,
        dialog_language=dialog_language,
    )


def build_clarifier_decision(spec: NormalizedSpec) -> ClarifierDecision:
    if spec["clarification_required"] and spec["clarification_question"]:
        return {
            "status": "question",
            "question": spec["clarification_question"],
        }
    return {
        "status": "approved",
        "question": None,
    }
