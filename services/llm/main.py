"""gRPC server for the LangGraph LLM pipeline service.

Session semantics
-----------------
* **New session** — ``StartOrContinue`` with an unknown (or empty) ``session_id``
  creates a fresh pipeline, detects ``dialog_language`` from the request, and
  stores the resulting state.
* **Existing session waiting for clarification** — ``StartOrContinue`` with the
  same ``session_id`` treats ``request.request`` as the user's answer to the
  pending clarification question and resumes the pipeline.
* **Existing session already finished** (``done`` / ``error``) — the saved state
  is returned as-is; the pipeline is **not** restarted implicitly.  Clients that
  want a fresh run must generate a new ``session_id``.
"""

from __future__ import annotations

import logging
import uuid
from concurrent import futures
from threading import Lock

import grpc
from grpc_reflection.v1alpha import reflection

from generated.api.llm.v1 import llm_pb2
from generated.api.llm.v1 import llm_pb2_grpc
from context_normalizer import normalize_context_safe
from graph import detect_language, graph as pipeline_graph
from state import PipelineState

logger = logging.getLogger(__name__)

# In-memory session store: session_id -> latest state snapshot
_sessions: dict[str, dict] = {}
_sessions_lock = Lock()


def _get_session(session_id: str) -> dict | None:
    with _sessions_lock:
        return _sessions.get(session_id)


def _save_session(session_id: str, state: dict):
    with _sessions_lock:
        _sessions[session_id] = state


def _phase_to_enum(phase: str) -> int:
    mapping = {
        "clarification_needed": llm_pb2.CLARIFICATION_NEEDED,
        "done": llm_pb2.DONE,
        "error": llm_pb2.ERROR,
    }
    return mapping.get(phase, llm_pb2.PHASE_UNSPECIFIED)


def _state_to_response(session_id: str, state: dict) -> llm_pb2.SessionResponse:
    """Convert LangGraph state to gRPC response."""
    phase = state.get("phase", "error")
    error_msg = state.get("error")

    # When validation failed after all retries, enrich the error message
    # with diagnostics so downstream services and the UI can surface details.
    if phase == "error" and not error_msg:
        validation_error = state.get("validation_error")
        validation_output = state.get("validation_output")
        if validation_error or validation_output:
            parts = []
            if validation_error:
                parts.append(f"Validation error: {validation_error}")
            if validation_output:
                parts.append(f"Validation output: {validation_output}")
            error_msg = "\n".join(parts)

    return llm_pb2.SessionResponse(
        session_id=session_id,
        phase=_phase_to_enum(phase),
        clarification_question=state.get("clarification_question") or None,
        code=state.get("code") or None,
        error=error_msg or None,
        repair_count=max(0, state.get("generation_attempt", 0) - 1),
        validation_output=state.get("validation_output") or None,
        validation_error=state.get("validation_error") or None,
    )


def _make_initial_state(session_id: str, request_text: str,
                        context: str | None) -> PipelineState:
    """Build a fresh ``PipelineState`` for a brand-new session.

    The *context* string is normalised through the shared layer so that the
    pipeline always receives a well-formed ``{"wf":{"vars":{},"initVariables":{}}}``
    structure regardless of what the caller sent.
    """
    dialog_language = detect_language(request_text)
    normalised_context = normalize_context_safe(context)
    return {
        "session_id": session_id,
        "request": request_text,
        "context": normalised_context,
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
        "dialog_language": dialog_language,
    }


def _resume_with_clarification(
    prev: dict,
    answer: str,
    graph,
    session_id: str,
    context,
) -> llm_pb2.SessionResponse:
    """Shared resume logic used by both ``StartOrContinue`` and ``AnswerClarification``.

    1. Append the Q/A pair to ``clarification_history``.
    2. Set ``clarification_answer`` and ``clarifying=True`` so the graph
       routes through ``update_spec_node``.
    3. Invoke the pipeline, persist the result, and always return a
       ``SessionResponse`` even on failure.
    """
    hist = list(prev.get("clarification_history") or [])
    hist.append({
        "question": prev.get("clarification_question"),
        "answer": answer,
    })

    resumed: PipelineState = {
        **prev,
        "clarification_answer": answer,
        "clarification_history": hist,
        "clarifying": True,
        "phase": "running",
    }

    try:
        result = graph.invoke(resumed)
        _save_session(session_id, result)
        return _state_to_response(session_id, result)
    except Exception as e:
        logger.exception("Pipeline failed after clarification answer")
        error_state = {**resumed, "phase": "error", "error": str(e)}
        _save_session(session_id, error_state)
        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details(str(e))
        return _state_to_response(session_id, error_state)


class LLMServiceServicer(llm_pb2_grpc.LLMServiceServicer):
    """Implements the stateful LangGraph LLMService."""

    def StartOrContinue(self, request, context):
        session_id = request.session_id or uuid.uuid4().hex
        prev = _get_session(session_id)

        # ── Existing session ──────────────────────────────────────────
        if prev:
            phase = prev.get("phase", "error")

            if phase == "clarification_needed":
                return _resume_with_clarification(
                    prev, request.request, pipeline_graph, session_id, context,
                )

            if phase in ("done", "error"):
                return _state_to_response(session_id, prev)

            # Any other phase — re-run the graph with the existing state.
            try:
                result = pipeline_graph.invoke(prev)
                _save_session(session_id, result)
                return _state_to_response(session_id, result)
            except Exception as e:
                logger.exception("Pipeline re-run failed")
                error_state = {**prev, "phase": "error", "error": str(e)}
                _save_session(session_id, error_state)
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return _state_to_response(session_id, error_state)

        # ── New session ───────────────────────────────────────────────
        session_id = session_id or uuid.uuid4().hex
        initial_state = _make_initial_state(session_id, request.request, request.context)

        try:
            result = pipeline_graph.invoke(initial_state)
            _save_session(session_id, result)
            return _state_to_response(session_id, result)
        except Exception as e:
            logger.exception("Pipeline failed")
            error_state = {**initial_state, "phase": "error", "error": str(e)}
            _save_session(session_id, error_state)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return _state_to_response(session_id, error_state)

    def AnswerClarification(self, request, context):
        session_id = request.session_id
        prev = _get_session(session_id)
        if not prev:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Session {session_id} not found")
            return llm_pb2.SessionResponse()

        if prev.get("phase") != "clarification_needed":
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details("Session is not waiting for clarification")
            return llm_pb2.SessionResponse()

        return _resume_with_clarification(
            prev, request.answer, pipeline_graph, session_id, context,
        )

    def GetSessionState(self, request, context):
        state = _get_session(request.session_id)
        if not state:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Session {request.session_id} not found")
            return llm_pb2.SessionResponse()
        return _state_to_response(request.session_id, state)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    llm_pb2_grpc.add_LLMServiceServicer_to_server(LLMServiceServicer(), server)

    SERVICE_NAMES = (
        llm_pb2.DESCRIPTOR.services_by_name["LLMService"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(SERVICE_NAMES, server)

    server.add_insecure_port("[::]:50051")
    logger.info("Starting LLM gRPC server on [::]:50051")
    server.start()
    logger.info("LLM gRPC server started")
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
