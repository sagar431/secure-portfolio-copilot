from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.chat.contracts import GroundedEvidence
from app.policies.models import AuthorizationContext
from app.schemas.chat import GroundedCitationData, GroundedClaimData


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TerminalStatus(StrEnum):
    COMPLETED = "completed"
    REFUSED = "refused"
    NEEDS_CLARIFICATION = "needs_clarification"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"


class StoppingReason(StrEnum):
    COMPLETED = "completed"
    REQUEST_REFUSED = "request_refused"
    CLARIFICATION_REQUIRED = "clarification_required"
    INSUFFICIENT_AUTHORIZED_EVIDENCE = "insufficient_authorized_evidence"
    SCOPE_DENIED = "scope_denied"
    MAX_STEPS = "max_steps"
    MAX_RETRIEVAL_REWRITES = "max_retrieval_rewrites"
    MAX_REPLANS = "max_replans"
    MAX_DURATION = "duration"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_ERROR = "tool_error"
    MODEL_ERROR = "model_error"
    MALFORMED_ACTION = "malformed_action"
    PLAN_EXHAUSTED = "plan_exhausted"
    CITATION_VALIDATION_FAILED = "citation_validation_failed"


class TraceEventType(StrEnum):
    PERCEPTION = "perception"
    POLICY = "policy"
    DECISION = "decision"
    GATEWAY = "gateway"
    TOOL = "tool"
    OBSERVATION = "observation"
    FINALIZATION = "finalization"
    TERMINAL = "terminal"


class TraceStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    DENIED = "denied"
    TIMEOUT = "timeout"
    FAILED = "failed"
    TERMINATED = "terminated"


class TraceEvent(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: TraceEventType
    action_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    status: TraceStatus
    duration_ms: int = Field(ge=0)
    evidence_reference_ids: tuple[str, ...] = ()
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")


class PerceptionMode(StrEnum):
    USER_QUERY = "user_query"
    STEP_RESULT = "step_result"


class EvidenceStatus(StrEnum):
    NONE = "none"
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    DENIED = "denied"
    ERROR = "error"


class GoalStatus(StrEnum):
    PENDING = "pending"
    ADVANCED = "advanced"
    SATISFIED = "satisfied"
    BLOCKED = "blocked"


class PerceptionSnapshot(StrictModel):
    mode: PerceptionMode
    intent: Literal["document_lookup", "clarification", "unsupported"]
    domain: Literal["portfolio_documents"]
    entities: tuple[str, ...] = Field(default=(), max_length=10)
    result_requirement: Literal["evidence", "grounded_answer", "clarification"]
    required_capabilities: tuple[Literal["QUERY_DOCUMENTS"], ...] = ()
    ambiguities: tuple[str, ...] = Field(default=(), max_length=5)
    risk_flags: tuple[str, ...] = Field(default=(), max_length=5)
    evidence_status: EvidenceStatus
    local_goal_status: GoalStatus
    global_goal_status: GoalStatus
    confidence: float = Field(ge=0, le=1)
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")


class ActionType(StrEnum):
    TOOL_CALL = "TOOL_CALL"
    FINALIZE = "FINALIZE"
    CLARIFY = "CLARIFY"
    REFUSE = "REFUSE"


ActionArgument = str | int | float | bool | None | list[str]
_FORBIDDEN_ARGUMENT_PARTS = (
    "tenant",
    "company",
    "department",
    "user",
    "role",
    "permission",
    "authorization",
    "scope",
    "shell",
    "sql",
    "python",
    "code",
    "url",
    "path",
)


class Action(StrictModel):
    type: ActionType
    action_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    arguments: dict[str, ActionArgument] = Field(default_factory=dict)
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")

    @field_validator("arguments")
    @classmethod
    def reject_scope_and_execution_arguments(
        cls, value: dict[str, ActionArgument]
    ) -> dict[str, ActionArgument]:
        for key in value:
            normalized = key.casefold().replace("-", "_")
            if any(part in normalized for part in _FORBIDDEN_ARGUMENT_PARTS):
                raise ValueError("Authorization and unrestricted execution arguments are forbidden")
        return value

    @model_validator(mode="after")
    def enforce_action_shape(self) -> Action:
        if self.type == ActionType.TOOL_CALL:
            if self.action_name is None:
                raise ValueError("A tool action requires one namespaced action name")
        elif self.action_name is not None or self.arguments:
            raise ValueError("Non-tool actions cannot carry a tool name or arguments")
        return self


class StepStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class Step(StrictModel):
    step_index: int = Field(ge=0, le=2)
    action_type: ActionType
    action_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    status: StepStatus = StepStatus.PENDING
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")


class Plan(StrictModel):
    version: int = Field(ge=1)
    steps: tuple[Step, ...] = Field(min_length=1, max_length=3)
    change_reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")

    @field_validator("steps")
    @classmethod
    def unique_ordered_steps(cls, value: tuple[Step, ...]) -> tuple[Step, ...]:
        if tuple(item.step_index for item in value) != tuple(range(len(value))):
            raise ValueError("Plan steps must be unique and ordered from zero")
        return value


class DecisionResult(StrictModel):
    plan: Plan
    next_action: Action
    replan: bool = False


class ObservationStatus(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    TIMEOUT = "timeout"
    ERROR = "error"


class StructuredObservation(StrictModel):
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    status: ObservationStatus
    evidence: tuple[GroundedEvidence, ...] = ()
    duration_ms: int = Field(ge=0)
    retryable: bool = False
    retry_count: int = Field(default=0, ge=0, le=1)
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")

    @model_validator(mode="after")
    def enforce_failure_shape(self) -> StructuredObservation:
        if self.status != ObservationStatus.SUCCESS and self.evidence:
            raise ValueError("Failed observations cannot expose evidence")
        if self.status == ObservationStatus.DENIED and self.retryable:
            raise ValueError("Authorization denials cannot be retried")
        return self

    @property
    def evidence_reference_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.evidence)


class AgentSession(StrictModel):
    session_id: UUID = Field(default_factory=uuid4)
    request_id: str = Field(min_length=1, max_length=128, exclude=True)
    original_query: str = Field(min_length=1, max_length=1000, exclude=True)
    authorization_context: AuthorizationContext = Field(exclude=True)
    permitted_tools: frozenset[str]
    perceptions: tuple[PerceptionSnapshot, ...] = ()
    plans: tuple[Plan, ...] = ()
    completed_steps: tuple[Step, ...] = ()
    observations: tuple[StructuredObservation, ...] = Field(default=(), exclude=True)
    terminal_status: TerminalStatus | None = None
    stopping_reason: StoppingReason | None = None
    step_count: int = Field(default=0, ge=0)
    replan_count: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    trace: tuple[TraceEvent, ...] = ()


class AgentRunOutcome(StrictModel):
    agent_session_id: UUID
    terminal_status: TerminalStatus
    stopping_reason: StoppingReason
    answer: str
    claims: tuple[GroundedClaimData, ...] = ()
    citations: tuple[GroundedCitationData, ...] = ()
    limitations: tuple[str, ...] = ()
    step_count: int = Field(ge=0)
    replan_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    trace: tuple[TraceEvent, ...]


BoundedSeconds = Annotated[float, Field(gt=0, le=300)]


class AgentLoopLimits(StrictModel):
    max_steps: int = Field(default=4, ge=1, le=8)
    max_retrieval_rewrites: int = Field(default=1, ge=0, le=1)
    max_replans: int = Field(default=1, ge=0, le=2)
    max_duration_seconds: BoundedSeconds = 30.0
