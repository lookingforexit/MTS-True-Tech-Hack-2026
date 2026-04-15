"""Context normalization and validation layer.

Provides a single authoritative entry point for parsing, validating, and
normalizing the ``context`` JSON that flows through the pipeline:

    frontend → backend → LLM service → lua-validator

Contract
--------
* Context is **optional**.  When absent the pipeline uses a safe default
  ``{"wf": {"vars": {}, "initVariables": {}}}``.
* When present it **must** be a JSON object (``dict``).
* The normalised form is always::

      {"wf": {"vars": {...}, "initVariables": {...}}}

  Missing ``wf``, ``vars``, or ``initVariables`` are filled with empty dicts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel: safe default context when none is provided.
DEFAULT_CONTEXT: dict[str, Any] = {"wf": {"vars": {}, "initVariables": {}}}


class ContextError(Exception):
    """Raised when context cannot be normalised."""


def normalize_context(raw: str | None) -> str:
    """Parse, validate, and normalise *raw* context JSON.

    Parameters
    ----------
    raw:
        Raw JSON string from the backend (may be ``None`` or empty).

    Returns
    -------
    str
        A canonical JSON string in the form
        ``{"wf": {"vars": {...}, "initVariables": {...}}}``.

    Raises
    ------
    ContextError
        If *raw* is not valid JSON or is not a JSON object.
    """
    if raw is None or raw.strip() == "":
        logger.info("No context provided — using safe default")
        return json.dumps(DEFAULT_CONTEXT, ensure_ascii=False)

    # ── Parse ──────────────────────────────────────────────────────
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Context is not valid JSON: %s", exc)
        raise ContextError(f"Invalid context JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        logger.warning("Context must be a JSON object, got %s", type(parsed).__name__)
        raise ContextError(
            f"Context must be a JSON object, got {type(parsed).__name__}"
        )

    # ── Normalise ──────────────────────────────────────────────────
    wf = parsed.get("wf")
    if wf is None:
        logger.info("Context missing 'wf' — inserting empty wf")
        wf = {}
    if not isinstance(wf, dict):
        logger.warning("Context 'wf' must be a JSON object, got %s", type(wf).__name__)
        raise ContextError(
            f"Context 'wf' must be a JSON object, got {type(wf).__name__}"
        )

    vars_section = wf.get("vars")
    if vars_section is None:
        logger.info("Context wf missing 'vars' — inserting empty dict")
        vars_section = {}
    if not isinstance(vars_section, dict):
        logger.warning("Context wf.vars must be a JSON object")
        raise ContextError("Context 'wf.vars' must be a JSON object")

    init_vars = wf.get("initVariables")
    if init_vars is None:
        logger.info("Context wf missing 'initVariables' — inserting empty dict")
        init_vars = {}
    if not isinstance(init_vars, dict):
        logger.warning("Context wf.initVariables must be a JSON object")
        raise ContextError("Context 'wf.initVariables' must be a JSON object")

    normalised = {"wf": {"vars": vars_section, "initVariables": init_vars}}
    result = json.dumps(normalised, ensure_ascii=False)
    logger.debug("Normalised context: %s", result)
    return result


def normalize_context_safe(raw: str | None) -> str:
    """Like :func:`normalize_context` but never raises — falls back to default.

    Use this in the pipeline where we want best-effort behaviour.
    """
    try:
        return normalize_context(raw)
    except ContextError as exc:
        logger.warning("Context normalisation failed (%s) — using safe default", exc)
        return json.dumps(DEFAULT_CONTEXT, ensure_ascii=False)
