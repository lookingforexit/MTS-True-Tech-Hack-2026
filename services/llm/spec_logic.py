"""Shared decision logic for spec extraction and clarification.

This module is the single source of truth for:
- final spec normalization
- clarification blocker detection
- clarification question generation
- clarification-history-aware blocker resolution
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
    "goal",
    "transform",
    "transformation",
    "convert",
    "generate",
    "greeting",
    "sort",
    "sorted",
    "descending",
    "ascending",
    "binary",
    "search",
    "fibonacci",
    "tree",
    "node",
    "red",
    "black",
    "unix",
    "timestamp",
    "time",
    "age",
    "first_name",
    "last_name",
    "role",
}


class NormalizedSpec(TypedDict):
    goal: str
    input_path: str
    output_type: str
    transformation: str
    return_value: str
    spec_parse_failed: bool
    clarification_required: bool
    clarification_target: ClarificationTarget
    clarification_question: str | None
    need_clarification: bool
    clarification_reason: str | None


class ClarifierDecision(TypedDict):
    status: Literal["approved", "question", "blocked"]
    question: str | None
    reason: str | None


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


def _extract_canonical_path(text: str) -> str | None:
    if not text:
        return None
    match = re.search(r"\b(wf\.(?:vars|initVariables)(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b", text)
    if not match:
        return None
    return match.group(1)


def _extract_entity_hint(text: str) -> str | None:
    if not text:
        return None

    patterns = (
        r"(?:variable|object|array)\s+`?([A-Za-z_][A-Za-z0-9_]*)`?",
        r"(?:переменн\w*|объект\w*|массив\w*)\s+`?([A-Za-z_][A-Za-z0-9_]*)`?",
        r"(?:sort|filter|group|convert|transform|merge)\s+`?([A-Za-z_][A-Za-z0-9_]*)`?",
        r"(?:отсортируй|сортируй|фильтруй|сгруппируй|конвертируй|преобразуй)\s+`?([A-Za-z_][A-Za-z0-9_]*)`?",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


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


def _infer_target_from_question(question: str) -> ClarificationTarget:
    lowered = question.lower()
    if "return" in lowered or "возвращ" in lowered:
        return "return_value"
    if "path" in lowered or "путь" in lowered:
        return "input_path"
    if "what exactly should the final lua code do" in lowered or "что именно должен сделать" in lowered:
        return "goal"
    return "none"


def _answer_indicates_no_input(answer: str) -> bool:
    lowered = answer.lower()
    markers = (
        "no input",
        "without input",
        "no context",
        "context is not needed",
        "don't use input",
        "does not use input",
        "нет входных данных",
        "без входных данных",
        "контекст не нужен",
        "входные данные не нужны",
        "не зависит от входных данных",
        "использовать входные данные не нужно",
    )
    return any(marker in lowered for marker in markers)


def _is_meaningful_goal(goal: str) -> bool:
    return goal.lower() not in _GENERIC_GOALS


def _is_meaningful_return_value(return_value: str) -> bool:
    lowered = return_value.lower()
    if lowered in _GENERIC_RETURN_VALUES:
        return False
    if lowered.startswith("result ") or lowered.startswith("return "):
        return False
    return bool(return_value)


def _merge_clarification_history(
    *,
    goal: str,
    input_path: str,
    return_value: str,
    clarification_history: list[dict] | None,
) -> tuple[str, str, str, bool]:
    input_path_answer_seen = False
    for entry in clarification_history or []:
        answer = _clean_text(entry.get("answer"))
        if not answer:
            continue

        target = entry.get("target") or _infer_target_from_question(_clean_text(entry.get("question")))
        if target == "goal" and not _is_meaningful_goal(goal):
            goal = answer
            continue

        if target == "return_value" and not _is_meaningful_return_value(return_value):
            return_value = answer
            continue

        if target != "input_path":
            continue

        input_path_answer_seen = True
        resolved_path = _extract_canonical_path(answer)
        if resolved_path:
            input_path = resolved_path
            continue

        if _answer_indicates_no_input(answer):
            input_path = INPUT_PATH_NOT_APPLICABLE
            continue

        if not input_path or input_path == INPUT_PATH_NEEDS_CLARIFICATION:
            input_path = answer

    return goal, input_path, return_value, input_path_answer_seen


def resolve_input_path(
    *,
    request: str,
    raw_context: dict | None,
    raw_input_path: str,
    goal: str,
    transformation: str,
    return_value: str,
) -> str | None:
    explicit_path = _extract_canonical_path(raw_input_path)
    if explicit_path:
        return explicit_path

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
    if _extract_canonical_path(raw_input_path):
        return True
    if raw_input_path and raw_input_path != INPUT_PATH_NOT_APPLICABLE:
        return True

    lowered = request.lower()
    if "wf.vars" in lowered or "wf.initvariables" in lowered:
        return True
    if _extract_entity_hint(request):
        return True

    contextual_markers = (
        "using object",
        "using array",
        "using variable",
        "используя объект",
        "используя массив",
        "используя переменн",
        "объект",
        "массив",
        "переменн",
    )
    return any(marker in lowered for marker in contextual_markers)


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
        binary_search_markers = ("binary search", "бинарн", "двоичн")
        if any(marker in f"{request} {goal}".lower() for marker in binary_search_markers):
            return (
                "Что должна возвращать функция бинарного поиска: индекс, сам элемент или true/false?"
                if is_ru
                else "What should the binary search return: index, element, or true/false?"
            )
        return (
            "Что именно должен возвращать итоговый Lua-код?"
            if is_ru
            else "What exactly should the final Lua code return?"
        )

    entity = _extract_entity_hint(request) or ("входных данных" if is_ru else "input data")
    if entity in ("входных данных", "input data"):
        example_path = "wf.vars.users"
    else:
        example_path = "wf.vars.users" if entity.lower().endswith("s") else f"wf.vars.{entity}"
    return (
        f"Какой точный Lua path у {entity} в контексте, например `{example_path}`?"
        if is_ru
        else f"What is the exact Lua path to the {entity} data, for example `{example_path}`?"
    )


def evaluate_spec(
    raw_spec: dict | None,
    *,
    request: str,
    raw_context: dict | None,
    dialog_language: str,
    clarification_history: list[dict] | None = None,
    parse_failed: bool = False,
) -> NormalizedSpec:
    raw_spec = raw_spec or {}

    goal = _clean_text(raw_spec.get("goal"))
    input_path = _clean_text(raw_spec.get("input_path"))
    output_type = _clean_text(raw_spec.get("output_type")) or "return_value"
    transformation = _clean_text(raw_spec.get("transformation")) or "as requested by user"
    return_value = _clean_text(raw_spec.get("return_value"))

    goal, input_path, return_value, input_path_answer_seen = _merge_clarification_history(
        goal=goal,
        input_path=input_path,
        return_value=return_value,
        clarification_history=clarification_history,
    )

    resolved_path = resolve_input_path(
        request=request,
        raw_context=raw_context,
        raw_input_path=input_path,
        goal=goal,
        transformation=transformation,
        return_value=return_value,
    )
    needs_contextual_input = _needs_contextual_input(request, input_path)
    no_input_confirmed = any(
        _answer_indicates_no_input(_clean_text(entry.get("answer")))
        for entry in clarification_history or []
        if (entry.get("target") or _infer_target_from_question(_clean_text(entry.get("question")))) == "input_path"
    )

    if resolved_path:
        normalized_input_path = resolved_path
    elif no_input_confirmed and not needs_contextual_input:
        normalized_input_path = INPUT_PATH_NOT_APPLICABLE
    elif input_path_answer_seen:
        normalized_input_path = input_path or INPUT_PATH_NOT_APPLICABLE
    elif needs_contextual_input:
        normalized_input_path = INPUT_PATH_NEEDS_CLARIFICATION
    else:
        normalized_input_path = INPUT_PATH_NOT_APPLICABLE

    clarification_target: ClarificationTarget = "none"
    clarification_reason: str | None = None

    if not _is_meaningful_goal(goal):
        clarification_target = "goal"
        clarification_reason = "goal is missing or too generic"
    elif not _is_meaningful_return_value(return_value):
        clarification_target = "return_value"
        clarification_reason = "return_value is missing or too generic"
    elif normalized_input_path == INPUT_PATH_NEEDS_CLARIFICATION:
        clarification_target = "input_path"
        clarification_reason = "input_path is required but still unresolved"

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
        "spec_parse_failed": parse_failed,
        "clarification_required": clarification_required,
        "clarification_target": clarification_target,
        "clarification_question": clarification_question,
        "need_clarification": clarification_required,
        "clarification_reason": "spec agent returned invalid JSON" if parse_failed else clarification_reason,
    }


def load_spec_json(
    spec_json: str | None,
    *,
    request: str,
    raw_context: dict | None,
    dialog_language: str,
    clarification_history: list[dict] | None = None,
) -> NormalizedSpec:
    parsed = json.loads(spec_json) if spec_json else {}
    return evaluate_spec(
        parsed,
        request=request,
        raw_context=raw_context,
        dialog_language=dialog_language,
        clarification_history=clarification_history,
        parse_failed=bool(parsed.get("spec_parse_failed")),
    )


def _question_was_already_asked(question: str | None, clarification_history: list[dict] | None) -> bool:
    if not question:
        return False
    asked = {_clean_text(entry.get("question")) for entry in clarification_history or []}
    return question in asked


def build_clarifier_decision(
    spec: NormalizedSpec,
    clarification_history: list[dict] | None = None,
) -> ClarifierDecision:
    if spec["clarification_required"] and spec["clarification_question"]:
        if _question_was_already_asked(spec["clarification_question"], clarification_history):
            return {
                "status": "blocked",
                "question": None,
                "reason": "clarification blocker is still unresolved after the same question was already asked",
            }
        return {
            "status": "question",
            "question": spec["clarification_question"],
            "reason": spec.get("clarification_reason"),
        }
    return {
        "status": "approved",
        "question": None,
        "reason": None,
    }
