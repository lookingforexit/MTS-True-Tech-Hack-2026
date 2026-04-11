"""gRPC server for the LangGraph LLM pipeline service.

Session semantics
-----------------
* **New session** — ``StartOrContinue`` with an unknown (or empty) ``session_id``
  creates a fresh pipeline, detects ``dialog_language`` from the request, and
  stores the resulting state.
* **Existing session waiting for clarification** — ``StartOrContinue`` with the
  same ``session_id`` treats ``request.request`` as the user's answer to the
  pending clarification question and resumes the pipeline (equivalent to calling
  ``AnswerClarification``).
* **Existing session already finished** (``done`` / ``error``) — the saved state
  is returned as-is; the pipeline is **not** restarted implicitly.  Clients that
  want a fresh run must generate a new ``session_id``.
"""

import logging
import uuid
from concurrent import futures
from threading import Lock

import grpc
from grpc_reflection.v1alpha import reflection

import llm_pb2
import llm_pb2_grpc
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
    return llm_pb2.SessionResponse(
        session_id=session_id,
        phase=_phase_to_enum(phase),
        clarification_question=state.get("clarification_question") or None,
        code=state.get("code") or None,
        error=state.get("error") or None,
        repair_count=state.get("repair_count", 0),
        validation_output=state.get("validation_output") or None,
    )


def _make_initial_state(session_id: str, request_text: str,
                        context: str | None) -> PipelineState:
    """Build a fresh ``PipelineState`` for a brand-new session."""
    dialog_language = detect_language(request_text)
    return {
        "session_id": session_id,
        "request": request_text,
        "context": context,
        "clarification_answer": None,
        "is_ambiguous": False,
        "clarification_question": None,
        "code": None,
        "validation_success": False,
        "validation_output": None,
        "validation_error": None,
        "repair_count": 0,
        "last_error": None,
        "phase": "running",
        "error": None,
        "dialog_language": dialog_language,
        "original_request": request_text,
        "clarification_history": [],
    }


class LLMServiceServicer(llm_pb2_grpc.LLMServiceServicer):
    """Implements the stateful LangGraph LLMService."""

    def StartOrContinue(self, request, context):
        session_id = request.session_id or uuid.uuid4().hex
        prev = _get_session(session_id)

        # ── Existing session ──────────────────────────────────────────
        if prev:
            phase = prev.get("phase", "error")

            if phase == "clarification_needed":
                # Treat request.request as the clarification answer and resume.
                resumed: PipelineState = {
                    **prev,
                    "clarification_answer": request.request,
                    "phase": "running",
                }
                # Append to clarification history
                hist = list(prev.get("clarification_history") or [])
                hist.append({
                    "question": prev.get("clarification_question"),
                    "answer": request.request,
                })
                resumed["clarification_history"] = hist
                try:
                    result = pipeline_graph.invoke(resumed)
                    _save_session(session_id, result)
                    return _state_to_response(session_id, result)
                except Exception as e:
                    logger.exception("Pipeline failed after clarification")
                    error_state = {**resumed, "phase": "error", "error": str(e)}
                    _save_session(session_id, error_state)
                    context.set_code(grpc.StatusCode.INTERNAL)
                    context.set_details(str(e))
                    return _state_to_response(session_id, error_state)

            if phase in ("done", "error"):
                # Session is finished — return saved state, do NOT restart.
                return _state_to_response(session_id, prev)

            # Any other phase (e.g. "running") — re-run the graph with the
            # existing state (should not happen in normal flow, but handle it).
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
        ctx = request.context if request.HasField("context") else None
        initial_state = _make_initial_state(session_id, request.request, ctx)

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

        # Resume with the answer
        resumed: PipelineState = {
            **prev,
            "clarification_answer": request.answer,
            "phase": "running",
        }
        # Append to clarification history
        hist = list(prev.get("clarification_history") or [])
        hist.append({
            "question": prev.get("clarification_question"),
            "answer": request.answer,
        })
        resumed["clarification_history"] = hist

        try:
            result = pipeline_graph.invoke(resumed)
            _save_session(session_id, result)
            return _state_to_response(session_id, result)
        except Exception as e:
            logger.exception("Pipeline failed after clarification")
            error_state = {**resumed, "phase": "error", "error": str(e)}
            _save_session(session_id, error_state)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return _state_to_response(session_id, error_state)

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

    # Enable gRPC reflection so tools like grpcurl can discover the service.
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
