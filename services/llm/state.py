"""LangGraph state definition for the multi-agent LLM pipeline."""

from typing import Optional

from typing_extensions import TypedDict


class TestCase(TypedDict, total=False):
    """A single test case derived from the spec."""
    name: str
    stdin: str
    expected_output: str
    description: str


class CandidateResult(TypedDict, total=False):
    """One generated candidate with its validation results."""
    index: int
    code: str
    all_passing: bool
    passed_tests: int
    total_tests: int
    failures: list[dict]  # [{test_name, stdin, expected, actual, error}]
    char_count: int


class PipelineState(TypedDict, total=False):
    """State carried through the multi-agent LangGraph pipeline.

    Pipeline stages:
        1. Spec-agent       — normalize user request into JSON spec
        2. Clarifier-agent  — approve spec or ask one clarification question
        3. Test-agent       — generate test cases from spec
        4. Generator-agent  — produce 2-4 Lua candidates from spec
        5. Validator stack  — run syntax + runtime + semantic tests
        6. Repair-agent     — fix failing candidates (up to MAX_REPAIRS)
        7. Ranker           — pick best passing candidate (shortest, simplest)
    """

    # ── Input / session ──────────────────────────────────────────────
    session_id: str
    request: str
    context: Optional[str]
    clarification_answer: Optional[str]
    dialog_language: str  # "ru" | "en"
    original_request: str
    clarification_history: Optional[list[dict]]

    # ── Spec ─────────────────────────────────────────────────────────
    spec_json: Optional[str]          # Normalized JSON spec from Spec-agent
    missing_critical_fields: list[str]  # Fields the clarifier may ask about

    # ── Clarifier ────────────────────────────────────────────────────
    is_ambiguous: bool
    clarification_question: Optional[str]
    spec_approved: bool               # Clarifier approved the spec

    # ── Tests ────────────────────────────────────────────────────────
    tests: Optional[list[TestCase]]

    # ── Generation ───────────────────────────────────────────────────
    candidates: Optional[list[CandidateResult]]
    candidate_count: int

    # ── Validation ───────────────────────────────────────────────────
    validation_success: bool
    validation_output: Optional[str]
    validation_error: Optional[str]

    # ── Repair ───────────────────────────────────────────────────────
    repair_count: int
    last_error: Optional[str]

    # ── Ranking ──────────────────────────────────────────────────────
    best_candidate_index: int

    # ── Output ───────────────────────────────────────────────────────
    code: Optional[str]
    phase: str  # "specifying" | "clarification_needed" | "testing" | "generating" | "validating" | "repairing" | "ranking" | "done" | "error"
    error: Optional[str]
