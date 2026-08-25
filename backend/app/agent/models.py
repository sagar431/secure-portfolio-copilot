from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.calculations.contracts import CalculationResult
from app.chat.contracts import GroundedEvidence
from app.mcp_gateway.contracts import (
    CalculateCagrInput,
    CalculateFinancialMetricInput,
    GetDocumentExcerptInput,
    MemoryToolItem,
    PermittedToolDescriptor,
    ProposeMemoryInput,
    QueryFinancialMetricsInput,
    SearchAuthorizedDocumentsInput,
    SearchMemoryInput,
)
from app.policies.models import AuthorizationContext
from app.schemas.chat import CalculationData, GroundedCitationData, GroundedClaimData


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


class PerceptionIntent(StrEnum):
    FINANCIAL_LOOKUP = "financial_lookup"
    LEGAL_LOOKUP = "legal_lookup"
    CROSS_DOMAIN_ANALYSIS = "cross_domain_analysis"
    PORTFOLIO_COMPARISON = "portfolio_comparison"
    CALCULATION_REQUIRED = "calculation_required"
    MEMORY_RECALL = "memory_recall"
    MEMORY_WRITE = "memory_write"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"


class ResultRequirement(StrEnum):
    AUTHORIZED_EVIDENCE = "authorized_evidence"
    GROUNDED_ANSWER = "grounded_answer"
    CLARIFICATION = "clarification"
    CONTROLLED_REFUSAL = "controlled_refusal"


class RequiredEvidence(StrEnum):
    FINANCIAL_DOCUMENT = "financial_document"
    LEGAL_DOCUMENT = "legal_document"
    SHARED_DOCUMENT = "shared_document"
    COMPARISON_DOCUMENTS = "comparison_documents"
    CALCULATION_INPUTS = "calculation_inputs"
    MEMORY_CONTEXT = "memory_context"


class PerceptionRiskFlag(StrEnum):
    SCOPE_HINT_PRESENT = "scope_hint_present"
    CROSS_TENANT_HINT = "cross_tenant_hint"
    CROSS_DEPARTMENT_HINT = "cross_department_hint"
    PROMPT_INJECTION = "prompt_injection"
    CALCULATION_UNAVAILABLE = "calculation_unavailable"
    AMBIGUOUS_TARGET = "ambiguous_target"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"


EntityText = Annotated[str, Field(min_length=1, max_length=80)]
SummaryText = Annotated[str, Field(min_length=1, max_length=300)]
ClarificationText = Annotated[str, Field(min_length=1, max_length=240)]


class PerceptionEntities(StrictModel):
    companies: tuple[EntityText, ...] = Field(default=(), max_length=6)
    departments: tuple[EntityText, ...] = Field(default=(), max_length=6)
    documents: tuple[EntityText, ...] = Field(default=(), max_length=6)
    financial_metrics: tuple[EntityText, ...] = Field(default=(), max_length=8)
    legal_terms: tuple[EntityText, ...] = Field(default=(), max_length=8)
    reporting_periods: tuple[EntityText, ...] = Field(default=(), max_length=6)
    currencies: tuple[EntityText, ...] = Field(default=(), max_length=4)


class MentionedScopeHints(StrictModel):
    """Untrusted language observations; never executable authorization input."""

    tenants: tuple[EntityText, ...] = Field(default=(), max_length=4)
    companies: tuple[EntityText, ...] = Field(default=(), max_length=6)
    departments: tuple[EntityText, ...] = Field(default=(), max_length=6)


class RemainingBudgets(StrictModel):
    tool_steps: int = Field(ge=0, le=4)
    retrieval_rewrites: int = Field(ge=0, le=1)
    replans: int = Field(ge=0, le=1)
    latest_tool_retries: int = Field(ge=0, le=1)
    duration_ms: int = Field(ge=0, le=120_000)


class PerceptionSnapshot(StrictModel):
    mode: PerceptionMode
    intent: PerceptionIntent
    domain: Literal["portfolio_documents"]
    entities: PerceptionEntities = Field(default_factory=PerceptionEntities)
    mentioned_scope_hints: MentionedScopeHints = Field(default_factory=MentionedScopeHints)
    result_requirement: ResultRequirement
    required_evidence: tuple[RequiredEvidence, ...] = Field(default=(), max_length=5)
    required_capabilities: tuple[Literal["QUERY_DOCUMENTS"], ...] = ()
    ambiguities: tuple[EntityText, ...] = Field(default=(), max_length=5)
    risk_flags: tuple[PerceptionRiskFlag, ...] = Field(default=(), max_length=5)
    evidence_status: EvidenceStatus
    local_goal_status: GoalStatus
    global_goal_status: GoalStatus
    confidence: float = Field(ge=0, le=1)
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    clarification_question: ClarificationText | None = None
    rationale_summary: SummaryText | None = Field(default=None, exclude=True)


class ActionType(StrEnum):
    TOOL_CALL = "TOOL_CALL"
    FINALIZE = "FINALIZE"
    CLARIFY = "CLARIFY"
    REFUSE = "REFUSE"


class NoActionArguments(StrictModel):
    pass


ActionArguments = (
    SearchAuthorizedDocumentsInput
    | GetDocumentExcerptInput
    | CalculateFinancialMetricInput
    | QueryFinancialMetricsInput
    | CalculateCagrInput
    | SearchMemoryInput
    | ProposeMemoryInput
    | NoActionArguments
)


class Action(StrictModel):
    type: ActionType
    action_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    arguments: ActionArguments = Field(default_factory=NoActionArguments)
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")

    @model_validator(mode="after")
    def enforce_action_shape(self) -> Action:
        if self.type == ActionType.TOOL_CALL:
            if self.action_name is None:
                raise ValueError("A tool action requires one namespaced action name")
            if self.action_name == "portfolio.search_authorized_documents" and not isinstance(
                self.arguments, SearchAuthorizedDocumentsInput
            ):
                raise ValueError("Search actions require the exact search input schema")
            if self.action_name == "portfolio.get_document_excerpt" and not isinstance(
                self.arguments, GetDocumentExcerptInput
            ):
                raise ValueError("Excerpt actions require the exact excerpt input schema")
            if self.action_name in {
                "portfolio.calculate_ebitda_margin",
                "portfolio.calculate_revenue_growth",
                "portfolio.calculate_net_profit_margin",
                "portfolio.calculate_debt_to_equity",
                "portfolio.calculate_cash_runway",
            } and not isinstance(self.arguments, CalculateFinancialMetricInput):
                raise ValueError("Calculation actions require the exact calculation input schema")
            if self.action_name == "portfolio.query_financial_metrics" and not isinstance(
                self.arguments, QueryFinancialMetricsInput
            ):
                raise ValueError("Metric queries require the exact metric input schema")
            if self.action_name == "portfolio.calculate_cagr" and not isinstance(
                self.arguments, CalculateCagrInput
            ):
                raise ValueError("CAGR actions require the exact CAGR input schema")
            if self.action_name == "portfolio.search_memory" and not isinstance(
                self.arguments, SearchMemoryInput
            ):
                raise ValueError("Memory searches require the exact memory search schema")
            if self.action_name == "portfolio.propose_memory" and not isinstance(
                self.arguments, ProposeMemoryInput
            ):
                raise ValueError("Memory proposals require the exact proposal schema")
        elif self.action_name is not None or not isinstance(self.arguments, NoActionArguments):
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
    plan_text: tuple[Annotated[str, Field(min_length=1, max_length=160)], ...] = Field(
        min_length=1, max_length=3
    )
    steps: tuple[Step, ...] = Field(min_length=1, max_length=3)
    change_reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")

    @field_validator("steps")
    @classmethod
    def unique_ordered_steps(cls, value: tuple[Step, ...]) -> tuple[Step, ...]:
        if tuple(item.step_index for item in value) != tuple(range(len(value))):
            raise ValueError("Plan steps must be unique and ordered from zero")
        return value

    @model_validator(mode="after")
    def plan_text_matches_steps(self) -> Plan:
        if len(self.plan_text) != len(self.steps):
            raise ValueError("Plan text must have exactly one entry per structured step")
        return self


class DecisionResult(StrictModel):
    plan: Plan
    next_action: Action
    replan: bool = False


class CompletedStep(StrictModel):
    plan_version: int = Field(ge=1)
    step_index: int = Field(ge=0, le=2)
    action_type: ActionType
    action_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    status: Literal[StepStatus.COMPLETED] = StepStatus.COMPLETED
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")


class ObservationStatus(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    TIMEOUT = "timeout"
    ERROR = "error"


class StructuredObservation(StrictModel):
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    status: ObservationStatus
    evidence: tuple[GroundedEvidence, ...] = ()
    calculations: tuple[CalculationResult, ...] = Field(default=(), exclude=True)
    memory_context: tuple[MemoryToolItem, ...] = ()
    memory_notification: str | None = Field(default=None, max_length=120)
    duration_ms: int = Field(ge=0)
    retryable: bool = False
    retry_count: int = Field(default=0, ge=0, le=1)
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")

    @model_validator(mode="after")
    def enforce_failure_shape(self) -> StructuredObservation:
        if self.status != ObservationStatus.SUCCESS and (
            self.evidence or self.calculations or self.memory_context or self.memory_notification
        ):
            raise ValueError("Failed observations cannot expose evidence or calculations")
        if self.status == ObservationStatus.DENIED and self.retryable:
            raise ValueError("Authorization denials cannot be retried")
        return self

    @property
    def evidence_reference_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.evidence)


class SafeStepSnapshot(StrictModel):
    """Content-free step metadata approved for persistence."""

    plan_version: int = Field(ge=1, le=2)
    plan_step_index: int = Field(ge=0, le=2)
    action_name: Literal["TOOL_CALL"] = "TOOL_CALL"
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    action_argument_hash: str = Field(default="0" * 64, pattern=r"^[0-9a-f]{64}$")
    status: Literal["COMPLETED", "DENIED", "TIMEOUT", "FAILED"]
    policy_decision: Literal["ALLOWED", "DENIED"]
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,95}$")
    duration_ms: int = Field(ge=0, le=120_000)


class SafeObservationSnapshot(StrictModel):
    """Authorized identifiers and bounded counts only; evidence content is excluded."""

    status: Literal["SUCCESS", "DENIED", "TIMEOUT", "ERROR"]
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,95}$")
    document_ids: tuple[UUID, ...] = Field(default=(), max_length=8)
    chunk_ids: tuple[UUID, ...] = Field(default=(), max_length=8)
    citation_ids: tuple[Annotated[str, Field(pattern=r"^ev_[1-9][0-9]*$")], ...] = Field(
        default=(), max_length=8
    )
    retry_count: int = Field(default=0, ge=0, le=1)
    duration_ms: int = Field(ge=0, le=120_000)

    @model_validator(mode="after")
    def identifiers_describe_the_same_evidence(self) -> SafeObservationSnapshot:
        lengths = {len(self.document_ids), len(self.chunk_ids), len(self.citation_ids)}
        if len(lengths) != 1:
            raise ValueError("Safe observation identifier counts must match")
        return self


class AgentSession(StrictModel):
    session_id: UUID = Field(default_factory=uuid4)
    request_id: str = Field(min_length=1, max_length=128, exclude=True)
    original_query: str = Field(min_length=1, max_length=1000, exclude=True)
    authorization_context: AuthorizationContext = Field(exclude=True)
    permitted_tool_catalog: tuple[PermittedToolDescriptor, ...]
    perceptions: tuple[PerceptionSnapshot, ...] = ()
    plans: tuple[Plan, ...] = ()
    completed_steps: tuple[CompletedStep, ...] = ()
    observations: tuple[StructuredObservation, ...] = Field(default=(), exclude=True)
    safe_steps: tuple[SafeStepSnapshot, ...] = Field(default=(), exclude=True)
    safe_observations: tuple[SafeObservationSnapshot, ...] = Field(default=(), exclude=True)
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
    calculations: tuple[CalculationData, ...] = ()
    memory_proposal: ProposeMemoryInput | None = Field(default=None, exclude=True)
    step_count: int = Field(ge=0)
    replan_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    trace: tuple[TraceEvent, ...]
    selected_intent: PerceptionIntent | None = Field(default=None, exclude=True)
    policy_decision: Literal["NOT_EVALUATED", "ALLOWED", "DENIED"] = Field(
        default="NOT_EVALUATED", exclude=True
    )
    tool_shortlist: tuple[str, ...] = Field(default=(), max_length=11, exclude=True)
    plan_version: int | None = Field(default=None, ge=1, le=2, exclude=True)
    evidence_advanced_goal: bool = Field(default=False, exclude=True)
    plan_versions: tuple[Plan, ...] = Field(default=(), exclude=True)
    safe_steps: tuple[SafeStepSnapshot, ...] = Field(default=(), exclude=True)
    safe_observations: tuple[SafeObservationSnapshot, ...] = Field(default=(), exclude=True)
    input_tokens: int | None = Field(default=None, ge=0, le=1_000_000, exclude=True)
    output_tokens: int | None = Field(default=None, ge=0, le=1_000_000, exclude=True)


BoundedSeconds = Annotated[float, Field(gt=0, le=300)]


class AgentLoopLimits(StrictModel):
    max_steps: int = Field(default=4, ge=1, le=4)
    max_retrieval_rewrites: int = Field(default=1, ge=0, le=1)
    max_replans: int = Field(default=1, ge=0, le=1)
    max_duration_seconds: BoundedSeconds = 30.0
