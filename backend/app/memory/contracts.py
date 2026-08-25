from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class CandidateAction(StrEnum):
    ADD = "ADD"
    NOOP = "NOOP"
    SUPERSEDE = "SUPERSEDE"
    EXPIRE = "EXPIRE"
    DELETE = "DELETE"


@dataclass(frozen=True, slots=True)
class MemoryExtractionRequest:
    user_text: str
    assistant_text: str
    conversation_id: UUID
    source_message_id: UUID


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    memory_type: str
    action: CandidateAction
    content: str
    normalized_key: str
    confidence: float
    importance: float
    sensitivity: str
    reason: str
    explicit: bool
    candidate_superseded_memory_id: UUID | None = None


class MemoryCandidateExtractor(Protocol):
    async def extract(self, request: MemoryExtractionRequest) -> tuple[MemoryCandidate, ...]: ...


@dataclass(frozen=True, slots=True)
class ConversationSummaryRequest:
    messages: tuple[tuple[str, str], ...]
    previous_summary: str | None = None


class ConversationSummarizer(Protocol):
    async def summarize(self, request: ConversationSummaryRequest) -> str: ...
