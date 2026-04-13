from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
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

class SessionRequest(_message.Message):
    __slots__ = ("session_id", "request", "context")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    request: str
    context: str
    def __init__(self, session_id: _Optional[str] = ..., request: _Optional[str] = ..., context: _Optional[str] = ...) -> None: ...

class AnswerRequest(_message.Message):
    __slots__ = ("session_id", "answer")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    ANSWER_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    answer: str
    def __init__(self, session_id: _Optional[str] = ..., answer: _Optional[str] = ...) -> None: ...

class GetStateRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class SessionResponse(_message.Message):
    __slots__ = ("session_id", "phase", "clarification_question", "code", "error", "repair_count", "validation_output", "validation_error")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    CLARIFICATION_QUESTION_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    REPAIR_COUNT_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_OUTPUT_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_ERROR_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    phase: SessionPhase
    clarification_question: str
    code: str
    error: str
    repair_count: int
    validation_output: str
    validation_error: str
    def __init__(self, session_id: _Optional[str] = ..., phase: _Optional[_Union[SessionPhase, str]] = ..., clarification_question: _Optional[str] = ..., code: _Optional[str] = ..., error: _Optional[str] = ..., repair_count: _Optional[int] = ..., validation_output: _Optional[str] = ..., validation_error: _Optional[str] = ...) -> None: ...
