from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SessionPhase(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PHASE_UNSPECIFIED: _ClassVar[SessionPhase]
    CLARIFICATION_NEEDED: _ClassVar[SessionPhase]
    CODE_GENERATED: _ClassVar[SessionPhase]
    DONE: _ClassVar[SessionPhase]
    ERROR: _ClassVar[SessionPhase]
PHASE_UNSPECIFIED: SessionPhase
CLARIFICATION_NEEDED: SessionPhase
CODE_GENERATED: SessionPhase
DONE: SessionPhase
ERROR: SessionPhase

class ClarificationEntry(_message.Message):
    __slots__ = ("question", "answer")
    QUESTION_FIELD_NUMBER: _ClassVar[int]
    ANSWER_FIELD_NUMBER: _ClassVar[int]
    question: str
    answer: str
    def __init__(self, question: _Optional[str] = ..., answer: _Optional[str] = ...) -> None: ...

class PipelineState(_message.Message):
    __slots__ = ("session_id", "request", "context", "raw_context_json", "dialog_language", "clarification_answer", "clarification_question", "clarification_history", "is_ambiguous", "clarifying", "spec_json", "spec_approved", "code", "generation_attempt", "validation_success", "validation_output", "validation_error", "phase", "error")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    RAW_CONTEXT_JSON_FIELD_NUMBER: _ClassVar[int]
    DIALOG_LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    CLARIFICATION_ANSWER_FIELD_NUMBER: _ClassVar[int]
    CLARIFICATION_QUESTION_FIELD_NUMBER: _ClassVar[int]
    CLARIFICATION_HISTORY_FIELD_NUMBER: _ClassVar[int]
    IS_AMBIGUOUS_FIELD_NUMBER: _ClassVar[int]
    CLARIFYING_FIELD_NUMBER: _ClassVar[int]
    SPEC_JSON_FIELD_NUMBER: _ClassVar[int]
    SPEC_APPROVED_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    GENERATION_ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_SUCCESS_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_OUTPUT_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_ERROR_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    request: str
    context: str
    raw_context_json: str
    dialog_language: str
    clarification_answer: str
    clarification_question: str
    clarification_history: _containers.RepeatedCompositeFieldContainer[ClarificationEntry]
    is_ambiguous: bool
    clarifying: bool
    spec_json: str
    spec_approved: bool
    code: str
    generation_attempt: int
    validation_success: bool
    validation_output: str
    validation_error: str
    phase: str
    error: str
    def __init__(self, session_id: _Optional[str] = ..., request: _Optional[str] = ..., context: _Optional[str] = ..., raw_context_json: _Optional[str] = ..., dialog_language: _Optional[str] = ..., clarification_answer: _Optional[str] = ..., clarification_question: _Optional[str] = ..., clarification_history: _Optional[_Iterable[_Union[ClarificationEntry, _Mapping]]] = ..., is_ambiguous: bool = ..., clarifying: bool = ..., spec_json: _Optional[str] = ..., spec_approved: bool = ..., code: _Optional[str] = ..., generation_attempt: _Optional[int] = ..., validation_success: bool = ..., validation_output: _Optional[str] = ..., validation_error: _Optional[str] = ..., phase: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class SessionRequest(_message.Message):
    __slots__ = ("pipeline_state",)
    PIPELINE_STATE_FIELD_NUMBER: _ClassVar[int]
    pipeline_state: PipelineState
    def __init__(self, pipeline_state: _Optional[_Union[PipelineState, _Mapping]] = ...) -> None: ...

class AnswerRequest(_message.Message):
    __slots__ = ("session_id", "answer", "pipeline_state")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    ANSWER_FIELD_NUMBER: _ClassVar[int]
    PIPELINE_STATE_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    answer: str
    pipeline_state: PipelineState
    def __init__(self, session_id: _Optional[str] = ..., answer: _Optional[str] = ..., pipeline_state: _Optional[_Union[PipelineState, _Mapping]] = ...) -> None: ...

class GetStateRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class SessionResponse(_message.Message):
    __slots__ = ("pipeline_state",)
    PIPELINE_STATE_FIELD_NUMBER: _ClassVar[int]
    pipeline_state: PipelineState
    def __init__(self, pipeline_state: _Optional[_Union[PipelineState, _Mapping]] = ...) -> None: ...
