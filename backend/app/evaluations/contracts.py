from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvaluationCategory(StrEnum):
    AUTHORIZED_POSITIVE = "authorized_positive"
    EXPLICIT_DENIAL = "explicit_denial"
    MEMORY_ISOLATION = "memory_isolation"
    DETERMINISTIC_CALCULATION = "deterministic_calculation"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EvaluationRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SECURITY_FAILED = "SECURITY_FAILED"
    ERROR = "ERROR"


class EvaluationCaseStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class EvaluationOperation(StrEnum):
    RETRIEVAL = "retrieval"
    GROUNDED_CHAT = "grounded_chat"
    DENIAL = "denial"
    MEMORY = "memory"
    CALCULATION = "calculation"
    ABSTENTION = "abstention"


class CaseExpectation(StrictModel):
    outcome: Literal["answer", "deny", "isolated", "calculation", "abstain"]
    reason_code: str
    document_ids: tuple[str, ...] = ()
    forbidden_document_ids: tuple[str, ...] = ()
    memory_ids: tuple[str, ...] = ()
    metric_value: float | None = None
    tolerance: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    citation_required: bool = False


class EvaluationCase(StrictModel):
    id: Annotated[str, Field(pattern=r"^EV-[0-9]{3}$")]
    category: EvaluationCategory
    operation: EvaluationOperation
    identity_key: Literal["nora", "alice", "leo", "maya", "amir", "lina"]
    workspace_slug: Literal["orion", "atlas", "platform"]
    company_slug: Literal["orion-main", "atlas-main"] | None = None
    department: Literal["finance", "legal", "shared", "administration"] | None = None
    question: Annotated[str, Field(min_length=3, max_length=500)]
    expected: CaseExpectation
    calculation_metric: Literal["ebitda_margin", "revenue_growth", "net_profit_margin"] | None = (
        None
    )
    period: Annotated[str, Field(pattern=r"^FY[0-9]{4}$")] | None = None

    @model_validator(mode="after")
    def operation_fields_are_consistent(self) -> EvaluationCase:
        if self.operation is EvaluationOperation.CALCULATION:
            if self.calculation_metric is None or self.period is None or self.company_slug is None:
                raise ValueError("calculation cases require metric, period, and company")
        elif self.calculation_metric is not None or self.period is not None:
            raise ValueError("calculation fields are allowed only for calculation cases")
        return self


class EvaluationManifest(StrictModel):
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    cases: tuple[EvaluationCase, ...]


class EvaluationRunRequest(StrictModel):
    suite_version: Literal["1.0.0"] = "1.0.0"
    enable_advisory_judge: bool = False
    max_judged_cases: Annotated[int, Field(ge=0, le=2)] = 0

    @model_validator(mode="after")
    def judge_limit_matches_toggle(self) -> EvaluationRunRequest:
        if not self.enable_advisory_judge and self.max_judged_cases != 0:
            raise ValueError("max_judged_cases must be zero when the judge is disabled")
        if self.enable_advisory_judge and self.max_judged_cases == 0:
            raise ValueError("max_judged_cases must be one or two when the judge is enabled")
        return self


class SafeCaseResult(StrictModel):
    case_id: str
    category: EvaluationCategory
    status: EvaluationCaseStatus
    reason_code: str
    expected_identifiers: tuple[str, ...]
    actual_identifiers: tuple[str, ...]
    metrics: dict[str, float | int | bool | str | None]
    duration_ms: int
    model_route: str | None = None
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    retry_count: int = 0
    fallback_used: bool = False
    fallback_reason_code: str | None = None
    started_at: datetime
    completed_at: datetime


class EvaluationMetrics(StrictModel):
    total: int
    passed: int
    failed: int
    errors: int
    cross_tenant_deny_pass_rate: float
    cross_department_deny_pass_rate: float
    memory_isolation_pass_rate: float
    calculation_exactness: float
    retrieval_recall_at_5: float
    citation_presence_rate: float
    citation_support_precision: float
    abstention_correctness: float
    average_latency_ms: float
    p95_latency_ms: float
    input_tokens: int
    output_tokens: int
    provider_cost_usd: float
    estimated_cost_usd: float
    model_route_distribution: dict[str, int]
    fallback_count: int
    retry_count: int


class ReleaseGate(StrictModel):
    name: str
    value: float
    threshold: float
    passed: bool


class EvaluationRunSummary(StrictModel):
    id: UUID
    status: EvaluationRunStatus
    manifest_version: str
    manifest_hash: str
    advisory_judge_enabled: bool
    advisory_judge_label: Literal["ADVISORY_ONLY"] = "ADVISORY_ONLY"
    metrics: EvaluationMetrics | None
    release_gates: tuple[ReleaseGate, ...]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class EvaluationRunDetail(EvaluationRunSummary):
    results: tuple[SafeCaseResult, ...]


class EvaluationRunList(StrictModel):
    runs: tuple[EvaluationRunSummary, ...]
