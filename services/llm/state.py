"""LangGraph state definition for the simplified multi-agent LLM pipeline."""

from typing import Optional

from typing_extensions import TypedDict


class PipelineState(TypedDict, total=False):
    """State carried through the simplified LLM pipeline.

    Pipeline stages:
        1. Spec-agent       — extract structured spec from request + Lua context
        2. Clarifier-agent  — approve spec or ask one clarification question
        3. Generator-agent  — produce Lua code (with repair loop on validation failure)
    """

    # ── Input ────────────────────────────────────────────────────────
    session_id: str
    request: str
    context: Optional[str]            # Raw JSON context from backend
    extracted_context: Optional[dict]  # Context extracted from Lua environment via introspection
    dialog_language: str              # "ru" | "en"

    # ── Clarification ────────────────────────────────────────────────
    clarification_answer: Optional[str]
    clarification_question: Optional[str]
    clarification_history: Optional[list[dict]]
    is_ambiguous: bool

    # ── Spec ─────────────────────────────────────────────────────────
    spec_json: Optional[str]
    spec_approved: bool

    # ── Code generation ──────────────────────────────────────────────
    code: Optional[str]
    generation_attempt: int

    # ── Validation ───────────────────────────────────────────────────
    validation_success: bool
    validation_output: Optional[str]
    validation_error: Optional[str]

    # ── Phase / output ───────────────────────────────────────────────
    phase: str  # "running" | "clarification_needed" | "done" | "error"
    error: Optional[str]
