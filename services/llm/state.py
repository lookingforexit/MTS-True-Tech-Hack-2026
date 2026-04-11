"""LangGraph state definition for the LLM pipeline."""

from typing import Optional

from typing_extensions import TypedDict


class PipelineState(TypedDict, total=False):
    """State carried through the LangGraph pipeline.

    Extended with session semantics:
    - dialog_language: detected from the first user request ("ru" or "en").
    - original_request: preserved across the whole session.
    - clarification_history: optional log of clarification Q&A pairs.
    """

    # Input
    session_id: str
    request: str
    context: Optional[str]
    clarification_answer: Optional[str]

    # Clarify phase
    is_ambiguous: bool
    clarification_question: Optional[str]

    # Generate phase
    code: Optional[str]

    # Validate phase
    validation_success: bool
    validation_output: Optional[str]
    validation_error: Optional[str]

    # Repair phase
    repair_count: int
    last_error: Optional[str]

    # Session / language
    dialog_language: str  # "ru" | "en"
    original_request: str
    clarification_history: Optional[list[dict]]  # [{"question": ..., "answer": ...}]

    # Output
    phase: str  # "clarification_needed" | "done" | "error"
    error: Optional[str]
