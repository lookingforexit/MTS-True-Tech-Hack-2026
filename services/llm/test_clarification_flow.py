"""Unit tests for the clarification flow in the LLM pipeline.

These tests mock the LLM and validator to exercise the state machine
logic deterministically without external services.

Test matrix:
    1. Ambiguous prompt without answer → clarification question returned
    2. After answer, spec_json changes (update_spec_node incorporates the answer)
    3. After answer, generation uses the updated spec
    4. AnswerClarification when session is NOT waiting → FAILED_PRECONDITION
    5. StartOrContinue when session is done → returns saved state, no restart
    6. Full round-trip: ambiguous → answer → spec updated → generate → done
"""

from __future__ import annotations

import json
import uuid
from threading import Lock
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures — mock LLM, validator, and session infrastructure
# ---------------------------------------------------------------------------

SPEC_INITIAL = {
    "goal": "Process data",
    "input_path": "wf.vars.input",
    "output_type": "transformed_table",
    "transformation": "unknown",
    "edge_cases": [],
    "need_clarification": True,
    "clarification_reason": "ambiguous request",
}

SPEC_AFTER_CLARIFICATION = {
    "goal": "Filter parsedCsv by Discount field",
    "input_path": "wf.vars.parsedCsv",
    "output_type": "filtered_array",
    "transformation": "Keep rows where Discount is non-empty",
    "edge_cases": ["null values"],
    "need_clarification": False,
    "clarification_reason": None,
}

CLARIFIER_QUESTION = {
    "status": "question",
    "question": "Which field should be used for filtering?",
}

CLARIFIER_APPROVED = {
    "status": "approved",
    "question": None,
}

LUA_CODE = """local result = {}
return result"""


def _make_llm_response(content) -> MagicMock:
    """Create a mock LLM response with the given content."""
    if isinstance(content, dict):
        content = json.dumps(content)
    mock = MagicMock()
    mock.content = content
    return mock


def _make_validation_result(success: bool = True) -> MagicMock:
    """Create a mock validation result."""
    result = MagicMock()
    result.success = success
    result.output = "OK"
    result.error = ""
    return result


# ---------------------------------------------------------------------------
# Helper: build a minimal graph for testing with mocked LLM/validator
# ---------------------------------------------------------------------------

def _build_test_graph(
    spec_responses: list,
    clarifier_responses: list,
    generate_response: str | list[str] = LUA_CODE,
    validation_success: bool = True,
    validation_results: list[MagicMock] | None = None,
):
    """Build a pipeline graph with pre-programmed mock LLM responses.

    *spec_responses* — list of contents returned by the spec LLM
        (consumed in order: first call → spec_responses[0], etc.)
    *clarifier_responses* — same for the clarifier LLM.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langgraph.graph import START, StateGraph

    from graph import (
        extract_context_node,
        clarifier_node,
        generate_node,
        route_after_clarifier,
        route_after_validate,
        route_entry,
        update_spec_node,
        validate_node,
        spec_node,
    )
    from state import PipelineState

    spec_counter = 0
    clarifier_counter = 0

    def mock_llm_zero_invoke(messages):
        nonlocal spec_counter
        idx = min(spec_counter, len(spec_responses) - 1)
        spec_counter += 1
        return _make_llm_response(spec_responses[idx])

    def mock_clarifier_llm_invoke(messages):
        nonlocal clarifier_counter
        idx = min(clarifier_counter, len(clarifier_responses) - 1)
        clarifier_counter += 1
        return _make_llm_response(clarifier_responses[idx])

    # Patch the LLM instances
    import graph as graph_module

    original_llm_zero = graph_module._llm_zero
    original_llm_generate = graph_module._llm_generate

    mock_llm_zero = MagicMock()
    mock_llm_generate = MagicMock()

    def llm_zero_side_effect(messages):
        # Determine if this is a spec or clarifier call by checking the prompt
        first_msg = messages[0]
        if isinstance(first_msg, SystemMessage):
            content = first_msg.content
            if "specification extractor" in content.lower():
                return mock_llm_zero_invoke(messages)
            elif "clarifier" in content.lower():
                return mock_clarifier_llm_invoke(messages)
        # Default to spec
        return mock_llm_zero_invoke(messages)

    mock_llm_zero.invoke.side_effect = llm_zero_side_effect
    if isinstance(generate_response, list):
        generate_counter = 0

        def generate_side_effect(messages):
            nonlocal generate_counter
            idx = min(generate_counter, len(generate_response) - 1)
            generate_counter += 1
            return _make_llm_response(generate_response[idx])
    else:
        def generate_side_effect(messages):
            return _make_llm_response(generate_response)

    mock_llm_generate.invoke.side_effect = generate_side_effect

    # Patch validator
    mock_validator = MagicMock()
    if validation_results is not None:
        validation_counter = 0

        def validate_side_effect(*args, **kwargs):
            nonlocal validation_counter
            idx = min(validation_counter, len(validation_results) - 1)
            validation_counter += 1
            return validation_results[idx]
    else:
        def validate_side_effect(*args, **kwargs):
            return _make_validation_result(validation_success)

    mock_validator.validate.side_effect = validate_side_effect
    original_validator = graph_module._validator

    graph_module._llm_zero = mock_llm_zero
    graph_module._llm_generate = mock_llm_generate
    graph_module._validator = mock_validator

    try:
        # Rebuild graph with patched modules
        builder = StateGraph(PipelineState)
        builder.add_node("extract_context", extract_context_node)
        builder.add_node("spec", spec_node)
        builder.add_node("update_spec", update_spec_node)
        builder.add_node("clarifier", clarifier_node)
        builder.add_node("generate", generate_node)
        builder.add_node("validate", validate_node)

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

        builder.add_node("clarification_needed", lambda s: {"phase": "clarification_needed"})
        builder.add_node("done", lambda s: {"phase": "done"})
        builder.add_node("error", lambda s: {
            "phase": "error",
            "error": s.get("validation_error") or s.get("error"),
            "validation_error": s.get("validation_error"),
            "validation_output": s.get("validation_output"),
        })

        return builder.compile()
    finally:
        # Restore originals
        graph_module._llm_zero = original_llm_zero
        graph_module._llm_generate = original_llm_generate
        graph_module._validator = original_validator


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClarificationFlow:
    """Core clarification flow tests using the graph directly."""

    def test_ambiguous_prompt_returns_question(self):
        """Ambiguous prompt without answer → clarification question returned."""
        graph = _build_test_graph(
            spec_responses=[SPEC_INITIAL],
            clarifier_responses=[CLARIFIER_QUESTION],
        )

        state = {
            "session_id": "test-1",
            "request": "Process the data",
            "context": None,
            "dialog_language": "en",
            "clarification_answer": None,
            "clarification_question": None,
            "clarification_history": [],
            "is_ambiguous": False,
            "clarifying": False,
            "spec_json": None,
            "spec_approved": False,
            "code": None,
            "generation_attempt": 0,
            "validation_success": False,
            "validation_output": None,
            "validation_error": None,
            "phase": "running",
            "error": None,
        }

        result = graph.invoke(state)
        assert result["phase"] == "clarification_needed"
        assert result["is_ambiguous"] is True
        assert result["clarification_question"] == "Which field should be used for filtering?"
        assert result["code"] is None

    def test_spec_changes_after_clarification_answer(self):
        """After answer, spec_json should be different (rebuilt with clarification)."""
        graph = _build_test_graph(
            spec_responses=[SPEC_INITIAL, SPEC_AFTER_CLARIFICATION],
            clarifier_responses=[CLARIFIER_QUESTION, CLARIFIER_APPROVED],
        )

        # First run — should ask a question
        state = {
            "session_id": "test-2",
            "request": "Process the data",
            "context": None,
            "dialog_language": "en",
            "clarification_answer": None,
            "clarification_question": None,
            "clarification_history": [],
            "is_ambiguous": False,
            "clarifying": False,
            "spec_json": None,
            "spec_approved": False,
            "code": None,
            "generation_attempt": 0,
            "validation_success": False,
            "validation_output": None,
            "validation_error": None,
            "phase": "running",
            "error": None,
        }

        result1 = graph.invoke(state)
        assert result1["phase"] == "clarification_needed"
        first_spec = json.loads(result1["spec_json"])

        # Resume with answer
        resumed = {
            **result1,
            "clarification_answer": "Filter by Discount field",
            "clarification_history": [{
                "question": result1["clarification_question"],
                "answer": "Filter by Discount field",
            }],
            "clarifying": True,
            "phase": "running",
        }

        result2 = graph.invoke(resumed)
        assert result2["phase"] == "done"
        second_spec = json.loads(result2["spec_json"])

        # Specs should be different after clarification
        assert first_spec != second_spec, (
            "spec_json must change after clarification answer. "
            f"Before: {first_spec}\nAfter: {second_spec}"
        )
        # The updated spec should reflect the clarification
        assert "Discount" in second_spec["goal"] or "Discount" in second_spec["transformation"]

    def test_generation_uses_updated_spec(self):
        """After answer, generation must use the updated spec (not the original)."""
        graph = _build_test_graph(
            spec_responses=[SPEC_INITIAL, SPEC_AFTER_CLARIFICATION],
            clarifier_responses=[CLARIFIER_QUESTION, CLARIFIER_APPROVED],
            validation_success=True,
        )

        state = {
            "session_id": "test-3",
            "request": "Process the data",
            "context": None,
            "dialog_language": "en",
            "clarification_answer": None,
            "clarification_question": None,
            "clarification_history": [],
            "is_ambiguous": False,
            "clarifying": False,
            "spec_json": None,
            "spec_approved": False,
            "code": None,
            "generation_attempt": 0,
            "validation_success": False,
            "validation_output": None,
            "validation_error": None,
            "phase": "running",
            "error": None,
        }

        # First run — clarification needed
        result1 = graph.invoke(state)
        assert result1["phase"] == "clarification_needed"

        # Resume with answer
        resumed = {
            **result1,
            "clarification_answer": "Filter by Discount field",
            "clarification_history": [{
                "question": result1["clarification_question"],
                "answer": "Filter by Discount field",
            }],
            "clarifying": True,
            "phase": "running",
        }

        result2 = graph.invoke(resumed)
        assert result2["phase"] == "done"
        assert result2["code"] is not None
        assert result2["generation_attempt"] >= 1

        # Verify the spec used for generation was the updated one
        final_spec = json.loads(result2["spec_json"])
        assert final_spec == SPEC_AFTER_CLARIFICATION, (
            f"Generation should use the updated spec. Got: {final_spec}"
        )

    def test_answer_when_not_waiting_is_rejected(self):
        """AnswerClarification when session is NOT waiting → FAILED_PRECONDITION."""
        # This is tested at the gRPC level (see TestGrpcClarificationFlow below)
        # Here we test the graph-level invariant: clarifying=False + no ambiguity
        # means the graph proceeds normally without treating answer as special.
        graph = _build_test_graph(
            spec_responses=[SPEC_AFTER_CLARIFICATION],
            clarifier_responses=[CLARIFIER_APPROVED],
            validation_success=True,
        )

        # State with an answer but clarifying=False (simulates wrong usage)
        state = {
            "session_id": "test-4",
            "request": "Filter data by Discount",
            "context": None,
            "dialog_language": "en",
            "clarification_answer": "some answer",  # set but not in clarification flow
            "clarification_question": None,
            "clarification_history": [],
            "is_ambiguous": False,
            "clarifying": False,  # NOT in clarification mode
            "spec_json": None,
            "spec_approved": False,
            "code": None,
            "generation_attempt": 0,
            "validation_success": False,
            "validation_output": None,
            "validation_error": None,
            "phase": "running",
            "error": None,
        }

        # The graph should proceed normally (spec → clarifier → generate → done)
        # The answer is ignored because clarifying=False
        result = graph.invoke(state)
        assert result["phase"] == "done"
        assert result["code"] is not None


class TestGrpcClarificationFlow:
    """Tests for the gRPC service layer (main.py)."""

    def _make_servicer(self):
        """Create a servicer with a clean session store."""
        import main as main_module

        # Reset session store
        main_module._sessions.clear()

        return main_module.LLMServiceServicer()

    def _make_mock_context(self):
        """Create a mock gRPC context."""
        ctx = MagicMock()
        ctx.set_code = MagicMock()
        ctx.set_details = MagicMock()
        return ctx

    def test_answer_when_not_waiting_returns_failed_precondition(self):
        """AnswerClarification when session is not waiting → FAILED_PRECONDITION."""
        import grpc
        import main as main_module
        from generated.api.llm.v1 import llm_pb2

        servicer = self._make_servicer()
        mock_ctx = self._make_mock_context()

        # Create a session that is NOT in clarification_needed phase
        session_id = "session-not-waiting"
        main_module._sessions[session_id] = {
            "session_id": session_id,
            "phase": "done",
            "code": "some code",
            "clarification_question": None,
            "clarification_history": [],
        }

        req = llm_pb2.AnswerRequest(session_id=session_id, answer="test")
        resp = servicer.AnswerClarification(req, mock_ctx)

        mock_ctx.set_code.assert_called_once_with(grpc.StatusCode.FAILED_PRECONDITION)

    def test_answer_for_unknown_session_returns_not_found(self):
        """AnswerClarification for unknown session → NOT_FOUND."""
        import grpc
        import main as main_module
        from generated.api.llm.v1 import llm_pb2

        servicer = self._make_servicer()
        mock_ctx = self._make_mock_context()

        req = llm_pb2.AnswerRequest(session_id="nonexistent", answer="test")
        resp = servicer.AnswerClarification(req, mock_ctx)

        mock_ctx.set_code.assert_called_once_with(grpc.StatusCode.NOT_FOUND)

    def test_start_or_continue_done_session_returns_saved_state(self):
        """StartOrContinue when session is done → returns saved state, no restart."""
        import main as main_module
        from generated.api.llm.v1 import llm_pb2

        servicer = self._make_servicer()

        session_id = "session-done"
        main_module._sessions[session_id] = {
            "session_id": session_id,
            "phase": "done",
            "code": "existing code",
            "clarification_question": None,
            "clarification_history": [],
        }

        req = llm_pb2.SessionRequest(
            session_id=session_id,
            request="new request that should be ignored",
            context="",
        )
        resp = servicer.StartOrContinue(req, MagicMock())

        assert resp.phase == llm_pb2.DONE
        assert resp.code == "existing code"

    @patch("main.pipeline_graph")
    def test_full_round_trip_via_start_or_continue(self, mock_graph):
        """Full round-trip: ambiguous → answer → spec updated → generate → done.

        This tests the integration of StartOrContinue with the graph.
        """
        import main as main_module
        from generated.api.llm.v1 import llm_pb2

        servicer = self._make_servicer()

        # First call: clarification needed
        first_result = {
            "session_id": "sess-1",
            "phase": "clarification_needed",
            "spec_json": json.dumps(SPEC_INITIAL),
            "clarification_question": "Which field?",
            "clarification_history": [],
            "is_ambiguous": True,
            "clarifying": False,
            "clarification_answer": None,
            "code": None,
            "generation_attempt": 0,
            "request": "Process data",
            "context": None,
            "dialog_language": "en",
            "error": None,
        }

        # Second call (after answer): done with updated spec
        second_result = {
            **first_result,
            "phase": "done",
            "spec_json": json.dumps(SPEC_AFTER_CLARIFICATION),
            "clarification_question": "Which field?",
            "clarification_history": [{
                "question": "Which field?",
                "answer": "Discount field",
            }],
            "is_ambiguous": False,
            "clarifying": False,
            "clarification_answer": None,
            "code": LUA_CODE,
            "generation_attempt": 1,
        }

        mock_graph.invoke.side_effect = [first_result, second_result]

        # First call — new session
        req1 = llm_pb2.SessionRequest(
            session_id="sess-1",
            request="Process data",
            context="",
        )
        resp1 = servicer.StartOrContinue(req1, MagicMock())
        assert resp1.phase == llm_pb2.CLARIFICATION_NEEDED
        assert resp1.clarification_question == "Which field?"

        # Second call — answer the clarification
        req2 = llm_pb2.SessionRequest(
            session_id="sess-1",
            request="Discount field",
            context="",
        )
        resp2 = servicer.StartOrContinue(req2, MagicMock())
        assert resp2.phase == llm_pb2.DONE
        assert resp2.code == LUA_CODE

        # Verify the graph was invoked twice with correct states
        assert mock_graph.invoke.call_count == 2

        # Check the second invocation had clarifying=True
        second_invoke_state = mock_graph.invoke.call_args_list[1][0][0]
        assert second_invoke_state["clarifying"] is True
        assert second_invoke_state["clarification_answer"] == "Discount field"
        assert len(second_invoke_state["clarification_history"]) == 1


class TestStateInvariants:
    """Verify state machine invariants are maintained."""

    def test_clarifying_flag_routes_correctly(self):
        """clarifying=True → route_entry returns 'update_spec'."""
        from graph import route_entry

        state_with_clarifying = {
            "clarifying": True,
            "phase": "running",
        }
        assert route_entry(state_with_clarifying) == "update_spec"

    def test_no_clarifying_routes_to_spec(self):
        """clarifying=False → route_entry returns 'spec'."""
        from graph import route_entry

        state_without_clarifying = {
            "clarifying": False,
            "phase": "running",
        }
        assert route_entry(state_without_clarifying) == "spec"

    def test_clarifier_never_short_circuits(self):
        """clarifier_node always calls the LLM, even with clarification_answer set.

        The answer has already been consumed by update_spec_node.
        """
        from graph import clarifier_node
        import graph as graph_module

        original_llm_zero = graph_module._llm_zero
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_llm_response(CLARIFIER_APPROVED)
        graph_module._llm_zero = mock_llm

        try:
            state = {
                "session_id": "test",
                "request": "test",
                "dialog_language": "en",
                "spec_json": json.dumps(SPEC_AFTER_CLARIFICATION),
                "clarification_answer": "some answer",  # answer is set
                "clarifying": False,  # but clarifying is False (consumed by update_spec)
                "clarification_question": None,
                "clarification_history": [],
                "is_ambiguous": False,
                "spec_approved": False,
                "phase": "running",
            }

            result = clarifier_node(state)

            # The LLM should have been called (no short-circuit)
            mock_llm.invoke.assert_called_once()
            assert result["spec_approved"] is True
            assert result["is_ambiguous"] is False
        finally:
            graph_module._llm_zero = original_llm_zero

    def test_update_spec_resets_clarification_answer(self):
        """update_spec_node consumes the answer and resets clarifying flag."""
        from graph import update_spec_node
        import graph as graph_module

        original_llm_zero = graph_module._llm_zero
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_llm_response(SPEC_AFTER_CLARIFICATION)
        graph_module._llm_zero = mock_llm

        try:
            state = {
                "session_id": "test",
                "request": "Process data",
                "context": None,
                "dialog_language": "en",
                "spec_json": json.dumps(SPEC_INITIAL),
                "clarification_answer": "Discount field",
                "clarifying": True,
                "clarification_question": "Which field?",
                "clarification_history": [{
                    "question": "Which field?",
                    "answer": "Discount field",
                }],
                "is_ambiguous": False,
                "spec_approved": False,
                "phase": "running",
            }

            result = update_spec_node(state)

            # Answer and clarifying should be reset
            assert result["clarification_answer"] is None
            assert result["clarifying"] is False
            # Spec should be updated
            assert result["spec_json"] is not None
            parsed = json.loads(result["spec_json"])
            assert parsed == SPEC_AFTER_CLARIFICATION
        finally:
            graph_module._llm_zero = original_llm_zero

    def test_clarifier_approve_clears_stale_question(self):
        """Clarifier approval must clear the previous clarification question."""
        from graph import clarifier_node
        import graph as graph_module

        original_llm_zero = graph_module._llm_zero
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = _make_llm_response(CLARIFIER_APPROVED)
        graph_module._llm_zero = mock_llm

        try:
            state = {
                "session_id": "test",
                "request": "Process data",
                "dialog_language": "en",
                "spec_json": json.dumps(SPEC_AFTER_CLARIFICATION),
                "clarification_question": "Which field?",
                "clarification_history": [{
                    "question": "Which field?",
                    "answer": "Discount field",
                }],
                "is_ambiguous": True,
                "spec_approved": False,
                "phase": "running",
            }

            result = clarifier_node(state)

            assert result["spec_approved"] is True
            assert result["is_ambiguous"] is False
            assert result["clarification_question"] is None
        finally:
            graph_module._llm_zero = original_llm_zero

    def test_validation_failure_after_exhausted_retries_returns_error(self):
        """Exhausted repair loop must terminate in the error phase with diagnostics."""
        result_fail = _make_validation_result(False)
        result_fail.output = "stack traceback"
        result_fail.error = "lua validation failed"

        graph = _build_test_graph(
            spec_responses=[SPEC_AFTER_CLARIFICATION],
            clarifier_responses=[CLARIFIER_APPROVED],
            validation_results=[result_fail, result_fail, result_fail],
        )

        state = {
            "session_id": "test-error-route",
            "request": "Filter data by Discount",
            "context": None,
            "dialog_language": "en",
            "clarification_answer": None,
            "clarification_question": None,
            "clarification_history": [],
            "is_ambiguous": False,
            "clarifying": False,
            "spec_json": None,
            "spec_approved": False,
            "code": None,
            "generation_attempt": 0,
            "validation_success": False,
            "validation_output": None,
            "validation_error": None,
            "phase": "running",
            "error": None,
        }

        result = graph.invoke(state)
        assert result["phase"] == "error"
        assert result["generation_attempt"] == 3
        assert result["validation_error"] == "lua validation failed"
        assert result["validation_output"] == "stack traceback"

    def test_max_repairs_allows_two_repairs_after_initial_generation(self):
        """MAX_REPAIRS=2 means 3 total generation attempts before failing."""
        first_fail = _make_validation_result(False)
        first_fail.output = "fail #1"
        first_fail.error = "validation #1"

        second_fail = _make_validation_result(False)
        second_fail.output = "fail #2"
        second_fail.error = "validation #2"

        final_ok = _make_validation_result(True)
        final_ok.output = "OK"
        final_ok.error = ""

        graph = _build_test_graph(
            spec_responses=[SPEC_AFTER_CLARIFICATION],
            clarifier_responses=[CLARIFIER_APPROVED],
            generate_response=["code-1", "code-2", "code-3"],
            validation_results=[first_fail, second_fail, final_ok],
        )

        state = {
            "session_id": "test-repairs",
            "request": "Filter data by Discount",
            "context": None,
            "dialog_language": "en",
            "clarification_answer": None,
            "clarification_question": None,
            "clarification_history": [],
            "is_ambiguous": False,
            "clarifying": False,
            "spec_json": None,
            "spec_approved": False,
            "code": None,
            "generation_attempt": 0,
            "validation_success": False,
            "validation_output": None,
            "validation_error": None,
            "phase": "running",
            "error": None,
        }

        result = graph.invoke(state)
        assert result["phase"] == "done"
        assert result["generation_attempt"] == 3
        assert result["code"] == "code-3"

    def test_state_to_response_clamps_negative_repair_count(self):
        """repair_count must never be negative before the first generation."""
        import main as main_module

        response = main_module._state_to_response("sess", {"phase": "error", "generation_attempt": 0})
        assert response.repair_count == 0

    @patch("main.pipeline_graph")
    def test_resume_with_clarification_exception_returns_response(self, mock_graph):
        """Exception path must return SessionResponse and set INTERNAL status."""
        import grpc
        import main as main_module
        from generated.api.llm.v1 import llm_pb2

        main_module._sessions.clear()
        servicer = main_module.LLMServiceServicer()
        mock_ctx = MagicMock()
        mock_ctx.set_code = MagicMock()
        mock_ctx.set_details = MagicMock()

        session_id = "session-crash"
        main_module._sessions[session_id] = {
            "session_id": session_id,
            "phase": "clarification_needed",
            "request": "Process data",
            "context": None,
            "dialog_language": "en",
            "clarification_question": "Which field?",
            "clarification_history": [],
            "clarifying": False,
            "clarification_answer": None,
            "generation_attempt": 0,
            "error": None,
        }

        mock_graph.invoke.side_effect = RuntimeError("boom")

        req = llm_pb2.AnswerRequest(session_id=session_id, answer="Discount")
        resp = servicer.AnswerClarification(req, mock_ctx)

        assert isinstance(resp, llm_pb2.SessionResponse)
        assert resp.phase == llm_pb2.ERROR
        assert resp.error == "boom"
        mock_ctx.set_code.assert_called_once_with(grpc.StatusCode.INTERNAL)
        mock_ctx.set_details.assert_called_once_with("boom")
