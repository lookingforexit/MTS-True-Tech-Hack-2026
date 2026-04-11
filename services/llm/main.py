"""gRPC server for the LangGraph LLM pipeline service."""

import logging
import uuid
from concurrent import futures
from threading import Lock

import grpc

import llm_pb2
import llm_pb2_grpc
from graph import graph as pipeline_graph
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
        "code_generated": llm_pb2.CODE_GENERATED,
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


class LLMServiceServicer(llm_pb2_grpc.LLMServiceServicer):
    """Implements the stateful LangGraph LLMService."""

    def StartOrContinue(self, request, context):
        session_id = request.session_id or uuid.uuid4().hex
        initial_state: PipelineState = {
            "session_id": session_id,
            "request": request.request,
            "context": request.context if request.HasField("context") else None,
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
        }

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
    server.add_insecure_port("[::]:50051")
    logger.info("Starting LLM gRPC server on [::]:50051")
    server.start()
    logger.info("LLM gRPC server started")
    server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
