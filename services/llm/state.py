"""LangGraph state definition for the LLM pipeline."""

from typing import Optional

from typing_extensions import TypedDict


class PipelineState(TypedDict, total=False):
    """State carried through the LangGraph pipeline."""

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

    # Output
    phase: str  # "clarification_needed" | "code_generated" | "done" | "error"
    error: Optional[str]
