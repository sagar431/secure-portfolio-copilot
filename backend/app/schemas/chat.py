from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.model_routing import ResponseMode
from app.models.agent_runs import AgentControlMode
from app.openrouter_vertex import OPENROUTER_HEAVY_MODEL, OPENROUTER_SIMPLE_MODEL


def _normalize(value: str) -> str:
    return " ".join(value.split())


SafeModelName = Literal["Gemini 3.1 Flash Lite", "Gemini 3.7 Flash"]


def safe_model_name(model_name: str) -> SafeModelName | None:
    if model_name == OPENROUTER_SIMPLE_MODEL:
        return "Gemini 3.1 Flash Lite"
    if model_name == OPENROUTER_HEAVY_MODEL:
        return "Gemini 3.7 Flash"
    return None


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
    response_mode: ResponseMode = Field(default=ResponseMode.AUTO, strict=False)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = _normalize(value)
        if not normalized:
            raise ValueError("Message must not be blank")
        return normalized


class CreateAgentRunRequest(CreateMessageRequest):
    agent_control_mode: AgentControlMode = Field(default=AgentControlMode.BALANCED, strict=False)


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
    model_name: SafeModelName | None
    route_reason: str | None
    fallback_used: bool
    requested_response_mode: ResponseMode
    resolved_response_mode: ResponseMode | None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int = Field(ge=0)
    estimated_model_cost_usd: str | None = None
    pricing_snapshot_date: str | None = None


class CalculationInputData(BaseModel):
    name: str
    period: str
    value: float
    unit: Literal["INR crore"]
    citation_id: str


class CalculationData(BaseModel):
    calculation_id: UUID
    metric: Literal["ebitda_margin", "revenue_growth", "net_profit_margin"]
    company_slug: str
    period: str
    formula: str
    trusted_inputs: tuple[CalculationInputData, ...]
    result: float
    unit: Literal["percent"]
    citation_ids: tuple[str, ...]


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
    calculations: tuple[CalculationData, ...]
    step_count: int = Field(ge=0)
    replan_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    trace: tuple[AgentTraceEventData, ...]
    model_name: SafeModelName | None
    route_reason: str | None
    requested_response_mode: ResponseMode
    resolved_response_mode: ResponseMode | None
