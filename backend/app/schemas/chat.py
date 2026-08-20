from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize(value: str) -> str:
    return " ".join(value.split())


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize(value)
        if not normalized:
            raise ValueError("Title must not be blank")
        return normalized


class ConversationData(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class CreatedConversationData(BaseModel):
    conversation: ConversationData


class ConversationListData(BaseModel):
    conversations: tuple[ConversationData, ...]


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    content: str = Field(min_length=1, max_length=1000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = _normalize(value)
        if not normalized:
            raise ValueError("Message must not be blank")
        return normalized


class GroundedClaimData(BaseModel):
    text: str
    citation_ids: tuple[str, ...]


class GroundedCitationData(BaseModel):
    citation_id: str
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    document_title: str
    version_number: int = Field(ge=1)
    excerpt: str
    page_number: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    cell_start: str | None
    cell_end: str | None


class GroundedMessageData(BaseModel):
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    status: Literal["grounded", "insufficient_evidence"]
    answer: str
    claims: tuple[GroundedClaimData, ...]
    citations: tuple[GroundedCitationData, ...]
    limitations: tuple[str, ...]


class AgentTraceEventData(BaseModel):
    event_id: UUID
    event_type: Literal[
        "perception",
        "policy",
        "decision",
        "gateway",
        "tool",
        "observation",
        "finalization",
        "terminal",
    ]
    action_name: str | None
    status: Literal["started", "completed", "denied", "timeout", "failed", "terminated"]
    duration_ms: int = Field(ge=0)
    evidence_reference_ids: tuple[str, ...]
    reason_code: str


class AgentRunMessageData(BaseModel):
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    agent_session_id: UUID
    terminal_status: Literal[
        "completed",
        "refused",
        "needs_clarification",
        "insufficient_evidence",
        "limit_reached",
        "failed",
    ]
    stopping_reason: str
    answer: str
    claims: tuple[GroundedClaimData, ...]
    citations: tuple[GroundedCitationData, ...]
    limitations: tuple[str, ...]
    step_count: int = Field(ge=0)
    replan_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    trace: tuple[AgentTraceEventData, ...]
