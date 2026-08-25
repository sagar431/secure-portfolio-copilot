import json
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.chat.intent import RequestIntent
from app.schemas.chat import GroundedCitationData, GroundedMessageData


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MessageStarted(_Event):
    type: Literal["message.started"] = "message.started"


class RouteSelected(_Event):
    type: Literal["route.selected"] = "route.selected"
    intent: RequestIntent


class RetrievalStarted(_Event):
    type: Literal["retrieval.started"] = "retrieval.started"


class RetrievalCompleted(_Event):
    type: Literal["retrieval.completed"] = "retrieval.completed"
    citation_count: int = Field(ge=0, le=8)


class MemoryLoaded(_Event):
    type: Literal["memory.loaded"] = "memory.loaded"
    memory_count: int = Field(ge=0, le=5)


class AnswerDelta(_Event):
    type: Literal["answer.delta"] = "answer.delta"
    delta: str = Field(min_length=1, max_length=240)


class CitationEvent(_Event):
    type: Literal["citation"] = "citation"
    citation: GroundedCitationData


class MemoryNotification(_Event):
    type: Literal["memory.notification"] = "memory.notification"
    message: str = Field(min_length=1, max_length=120)


class MessageCompleted(_Event):
    type: Literal["message.completed"] = "message.completed"
    result: GroundedMessageData


class SafeError(_Event):
    type: Literal["error"] = "error"
    code: Literal["stream_failed"] = "stream_failed"
    message: Literal["The response could not be completed safely."] = (
        "The response could not be completed safely."
    )


ChatStreamEvent = Annotated[
    MessageStarted
    | RouteSelected
    | RetrievalStarted
    | RetrievalCompleted
    | MemoryLoaded
    | AnswerDelta
    | CitationEvent
    | MemoryNotification
    | MessageCompleted
    | SafeError,
    Field(discriminator="type"),
]
type ChatProgressEvent = RouteSelected | RetrievalStarted | RetrievalCompleted | MemoryLoaded
type ChatProgressCallback = Callable[[ChatProgressEvent], None]
_EVENT_ADAPTER: TypeAdapter[ChatStreamEvent] = TypeAdapter(ChatStreamEvent)


def encode_event(event: ChatStreamEvent) -> bytes:
    validated = _EVENT_ADAPTER.validate_python(event, strict=True)
    return (
        json.dumps(validated.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def validated_answer_deltas(answer: str, *, maximum: int = 160) -> tuple[str, ...]:
    """Split only a fully validated answer; raw provider output never enters this function."""
    words = answer.split(" ")
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= maximum:
            current = candidate
            continue
        if current:
            chunks.append(current + " ")
        while len(word) > maximum:
            chunks.append(word[:maximum])
            word = word[maximum:]
        current = word
    if current:
        chunks.append(current)
    return tuple(chunks)
