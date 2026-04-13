"""Stateless gRPC server for the LangGraph LLM pipeline service.

The backend owns session persistence in Redis and sends the latest
``PipelineState`` on every request. This service only computes the next state
and returns it to the backend for persistence.
"""

from __future__ import annotations

import json
import logging
from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection

from gen.api.llm.v1 import llm_pb2
from gen.api.llm.v1 import llm_pb2_grpc
from context_normalizer import normalize_context_safe
from graph import detect_language, graph as pipeline_graph
from state import PipelineState

logger = logging.getLogger(__name__)


def _proto_state_to_dict(msg) -> PipelineState:
    return {
        "session_id": msg.session_id,
        "request": msg.request,
        "context": msg.context if msg.HasField("context") else None,
        "raw_context": json.loads(msg.raw_context_json) if msg.HasField("raw_context_json") else None,
        "dialog_language": msg.dialog_language,
        "clarification_answer": msg.clarification_answer if msg.HasField("clarification_answer") else None,
        "clarification_question": msg.clarification_question if msg.HasField("clarification_question") else None,
        "clarification_history": [{"question": item.question, "answer": item.answer} for item in msg.clarification_history],
        "is_ambiguous": msg.is_ambiguous,
        "clarifying": msg.clarifying,
        "spec_json": msg.spec_json if msg.HasField("spec_json") else None,
        "spec_approved": msg.spec_approved,
        "code": msg.code if msg.HasField("code") else None,
        "generation_attempt": msg.generation_attempt,
        "validation_success": msg.validation_success,
        "validation_output": msg.validation_output if msg.HasField("validation_output") else None,
        "validation_error": msg.validation_error if msg.HasField("validation_error") else None,
        "phase": msg.phase,
        "error": msg.error if msg.HasField("error") else None,
    }


def _dict_to_proto_state(state: dict) -> llm_pb2.PipelineState:
    msg = llm_pb2.PipelineState(
        session_id=state.get("session_id", ""),
        request=state.get("request", ""),
        dialog_language=state.get("dialog_language", ""),
        is_ambiguous=bool(state.get("is_ambiguous", False)),
        clarifying=bool(state.get("clarifying", False)),
        spec_approved=bool(state.get("spec_approved", False)),
        generation_attempt=int(state.get("generation_attempt", 0)),
        validation_success=bool(state.get("validation_success", False)),
        phase=state.get("phase", ""),
    )

    for field in (
        "context",
        "clarification_answer",
        "clarification_question",
        "spec_json",
        "code",
        "validation_output",
        "validation_error",
        "error",
    ):
        value = state.get(field)
        if value is not None:
            setattr(msg, field, value)

    raw_context = state.get("raw_context")
    if raw_context is not None:
        msg.raw_context_json = json.dumps(raw_context, ensure_ascii=False)

    for item in state.get("clarification_history") or []:
        msg.clarification_history.append(
            llm_pb2.ClarificationEntry(
                question=item.get("question") or "",
                answer=item.get("answer") or "",
            )
        )

    return msg


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

    response_state = {**state, "session_id": session_id}
    if error_msg:
        response_state["error"] = error_msg

    return llm_pb2.SessionResponse(
        pipeline_state=_dict_to_proto_state(response_state),
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
    3. Invoke the pipeline and always return a ``SessionResponse`` even on
       failure so the backend can persist the resulting state.
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
        return _state_to_response(session_id, result)
    except Exception as e:
        logger.exception("Pipeline failed after clarification answer")
        error_state = {**resumed, "phase": "error", "error": str(e)}
        return _state_to_response(session_id, error_state)


class LLMServiceServicer(llm_pb2_grpc.LLMServiceServicer):
    """Implements the stateless LangGraph LLMService."""

    def StartOrContinue(self, request, context):
        if not request.HasField("pipeline_state"):
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("pipeline_state is required")
            return llm_pb2.SessionResponse()

        incoming_state = _proto_state_to_dict(request.pipeline_state)
        session_id = incoming_state.get("session_id")
        if not session_id:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("pipeline_state.session_id is required")
            return llm_pb2.SessionResponse()

        prev = incoming_state if incoming_state.get("phase") else None

        # ── Existing session ──────────────────────────────────────────
        if prev:
            phase = prev.get("phase", "error")

            if phase == "clarification_needed":
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                context.set_details("Session is waiting for AnswerClarification")
                return llm_pb2.SessionResponse()

            if phase in ("done", "error"):
                return _state_to_response(session_id, prev)

            # Any other phase — re-run the graph with the existing state.
            try:
                result = pipeline_graph.invoke(prev)
                return _state_to_response(session_id, result)
            except Exception as e:
                logger.exception("Pipeline re-run failed")
                error_state = {**prev, "phase": "error", "error": str(e)}
                return _state_to_response(session_id, error_state)

        # ── New session ───────────────────────────────────────────────
        request_text = incoming_state.get("request", "")
        context_text = incoming_state.get("context")
        initial_state = _make_initial_state(session_id, request_text, context_text)

        try:
            result = pipeline_graph.invoke(initial_state)
            return _state_to_response(session_id, result)
        except Exception as e:
            logger.exception("Pipeline failed")
            error_state = {**initial_state, "phase": "error", "error": str(e)}
            return _state_to_response(session_id, error_state)

    def AnswerClarification(self, request, context):
        if not request.HasField("pipeline_state"):
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("pipeline_state is required")
            return llm_pb2.SessionResponse()

        prev = _proto_state_to_dict(request.pipeline_state)
        session_id = request.session_id or prev.get("session_id")
        if not session_id:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("session_id is required")
            return llm_pb2.SessionResponse()

        if prev.get("phase") != "clarification_needed":
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details("Session is not waiting for clarification")
            return llm_pb2.SessionResponse()

        return _resume_with_clarification(
            prev, request.answer, pipeline_graph, session_id, context,
        )


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
