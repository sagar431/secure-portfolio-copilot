from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.agent_runs import AgentControlMode, AgentRunStatus, ApprovalRiskClass

SafeReasonCode = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{1,95}$")]
SafeToolName = Annotated[
    str,
    Field(
        pattern=r"^portfolio\.(search_authorized_documents|get_document_excerpt|calculate_(ebitda_margin|revenue_growth|net_profit_margin))$"
    ),
]


class AgentRunHistorySummaryData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    response_mode: Literal["fast", "auto", "deep"]
    agent_control_mode: AgentControlMode
    selected_model_tier: Literal["fast", "deep"] | None
    selected_model_name: Literal["Gemini 3.1 Flash Lite", "Gemini 3.7 Flash"] | None
    status: AgentRunStatus
    safe_reason_code: SafeReasonCode
    step_count: int = Field(ge=0, le=4)
    retry_count: int = Field(ge=0, le=4)
    duration_ms: int = Field(ge=0, le=120_000)
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AgentRunHistoryListData(BaseModel):
    runs: tuple[AgentRunHistorySummaryData, ...]
    next_cursor: str | None


class AgentPlanVersionData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int = Field(ge=1, le=2)
    change_reason_code: SafeReasonCode
    planned_step_count: int = Field(ge=1, le=3)
    created_at: datetime


class AgentObservationData(BaseModel):
    status: Literal["SUCCESS", "DENIED", "TIMEOUT", "ERROR"]
    safe_reason_code: SafeReasonCode
    authorized_document_ids: tuple[UUID, ...] = Field(max_length=8)
    authorized_chunk_ids: tuple[UUID, ...] = Field(max_length=8)
    citation_ids: tuple[Annotated[str, Field(pattern=r"^ev_[1-9][0-9]*$")], ...] = Field(
        max_length=8
    )
    evidence_count: int = Field(ge=0, le=8)
    retry_count: int = Field(ge=0, le=1)
    duration_ms: int = Field(ge=0, le=120_000)


class AgentStepData(BaseModel):
    step_number: int = Field(ge=1, le=4)
    plan_version: int = Field(ge=1, le=2)
    plan_step_index: int = Field(ge=0, le=2)
    action_name: Literal["TOOL_CALL"]
    tool_name: SafeToolName
    status: Literal["COMPLETED", "DENIED", "TIMEOUT", "FAILED"]
    policy_decision: Literal["ALLOWED", "DENIED"]
    safe_reason_code: SafeReasonCode
    duration_ms: int = Field(ge=0, le=120_000)
    observation: AgentObservationData | None


class AgentTimelineEventData(BaseModel):
    sequence: int = Field(ge=1, le=20)
    stage: Literal["perception", "policy", "decision", "tool", "observation", "final"]
    status: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{1,31}$")]
    safe_reason_code: SafeReasonCode
    summary: Annotated[str, Field(min_length=1, max_length=160)]
    tool_name: SafeToolName | None = None
    step_number: int | None = Field(default=None, ge=1, le=4)
    duration_ms: int = Field(ge=0, le=120_000)


class AgentRunHistoryDetailData(AgentRunHistorySummaryData):
    final_assistant_message_id: UUID | None
    input_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    perception_status: Literal["NOT_STARTED", "COMPLETED", "FAILED"]
    perception_reason_code: SafeReasonCode
    policy_decision: Literal["NOT_EVALUATED", "ALLOWED", "DENIED"]
    policy_reason_code: SafeReasonCode
    plan_versions: tuple[AgentPlanVersionData, ...] = Field(max_length=2)
    steps: tuple[AgentStepData, ...] = Field(max_length=4)
    timeline: tuple[AgentTimelineEventData, ...] = Field(max_length=20)


class RemainingApprovalBudgetData(BaseModel):
    steps: int = Field(ge=0, le=4)
    tools: int = Field(ge=0, le=4)


class ApprovalStateData(BaseModel):
    approval_id: UUID
    run_id: UUID
    status: Literal[
        "PENDING", "APPROVED", "REJECTED", "SUPERSEDED", "EXPIRED", "CANCELLED", "CONSUMED"
    ]
    action_label: Annotated[str, Field(min_length=1, max_length=80)]
    safe_explanation: Annotated[str, Field(min_length=1, max_length=180)]
    tool_name: SafeToolName
    risk_level: ApprovalRiskClass
    resource_type: Literal["authorized portfolio documents", "authorized financial data"]
    estimated_cost_class: Literal["low", "standard"]
    safe_scope_summary: Annotated[str, Field(min_length=1, max_length=160)]
    remaining_budget: RemainingApprovalBudgetData
    expires_at: datetime


class AwaitingApprovalData(BaseModel):
    outcome: Literal["awaiting_approval"] = "awaiting_approval"
    conversation_id: UUID
    user_message_id: UUID
    agent_session_id: UUID
    agent_control_mode: AgentControlMode
    approval: ApprovalStateData


class SafelyTerminatedData(BaseModel):
    outcome: Literal["terminated"] = "terminated"
    run_id: UUID
    status: Literal["REJECTED", "CANCELLED", "FAILED", "EXPIRED"]
    safe_message: Annotated[str, Field(min_length=1, max_length=180)]


class ResolveApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["approve_once", "reject"]


class ChangeAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Change request must not be blank")
        return normalized
