"""LangGraph state definition for the simplified multi-agent LLM pipeline.

State machine phases (``phase`` field):
    running               — pipeline is executing
    clarification_needed  — waiting for user answer to a clarification question
    done                  — pipeline completed successfully
    error                 — pipeline failed with an unrecoverable error

Clarification lifecycle:
    1. shared spec logic detects ambiguity → sets clarification_question + is_ambiguous
    2. route_after_clarifier routes to clarification_needed terminal node
    3. External caller provides answer via StartOrContinue or AnswerClarification
    4. Resume sets clarification_answer + phase=running + clarifying=True
    5. update_spec_node rebuilds spec with clarification_history
    6. clarifier_node reviews the updated spec (no short-circuit)
"""

from typing import Optional

from typing_extensions import TypedDict


class PipelineState(TypedDict, total=False):
    """State carried through the simplified LLM pipeline.

    Pipeline stages:
        1. Prepare context  — parse raw JSON, pass through directly
        2. Spec-agent       — extract a raw structured spec from request + context
        3. Shared policy    — normalize the spec and decide whether one clarification is needed
        4. Clarifier-agent  — ask at most one question derived from the shared policy
        5. Generator-agent  — produce Lua code (with repair loop on validation failure)
    """

    # ── Input ────────────────────────────────────────────────────────
    session_id: str
    request: str
    context: Optional[str]            # Raw JSON context string from backend
    raw_context: Optional[dict]       # Parsed JSON context (passed through, no introspection)
    dialog_language: str              # "ru" | "en"

    # ── Clarification ────────────────────────────────────────────────
    clarification_answer: Optional[str]
    clarification_question: Optional[str]
    clarification_history: list[dict]  # list of {"question": str, "answer": str, ...}
    is_ambiguous: bool
    clarifying: bool                   # True when re-running after a clarification answer

    # ── Spec ─────────────────────────────────────────────────────────
    spec_json: Optional[str]           # normalized JSON spec, includes return_value, parse status, and clarification metadata
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
    assistant_text: Optional[str]
