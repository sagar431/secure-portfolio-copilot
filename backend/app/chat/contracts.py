from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class GroundedEvidence:
    evidence_id: str
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    document_title: str
    excerpt: str
    page_number: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    cell_start: str | None
    cell_end: str | None


@dataclass(frozen=True, slots=True)
class GroundedGenerationRequest:
    question: str
    evidence: tuple[GroundedEvidence, ...]


@dataclass(frozen=True, slots=True)
class GroundedClaimDraft:
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroundedAnswerDraft:
    status: Literal["supported", "insufficient_evidence"]
    claims: tuple[GroundedClaimDraft, ...]
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class LLMGeneration:
    answer: GroundedAnswerDraft
    usage: LLMUsage


class LLMErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    TRANSIENT = "TRANSIENT"
    REJECTED = "REJECTED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"


class LLMProviderError(RuntimeError):
    """Content-free provider failure safe to map at the HTTP boundary."""

    def __init__(
        self, code: LLMErrorCode, *, transient: bool = False, retry_count: int = 0
    ) -> None:
        super().__init__("Language model provider is unavailable.")
        self.code = code
        self.transient = transient
        self.retry_count = retry_count


class LLMProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration: ...
