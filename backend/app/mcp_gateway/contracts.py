from __future__ import annotations

from enum import StrEnum
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from openpyxl.utils.cell import coordinate_to_tuple
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.calculations.contracts import CalculationResult
from app.retrieval.limits import (
    MAX_EXCERPT_CHARACTERS,
    MAX_QUERY_CHARACTERS,
    MAX_TOP_K,
)


class StrictGatewayModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ApprovedToolName(StrEnum):
    SEARCH_AUTHORIZED_DOCUMENTS = "portfolio.search_authorized_documents"
    GET_DOCUMENT_EXCERPT = "portfolio.get_document_excerpt"
    CALCULATE_EBITDA_MARGIN = "portfolio.calculate_ebitda_margin"
    CALCULATE_REVENUE_GROWTH = "portfolio.calculate_revenue_growth"
    CALCULATE_NET_PROFIT_MARGIN = "portfolio.calculate_net_profit_margin"
    QUERY_FINANCIAL_METRICS = "portfolio.query_financial_metrics"
    CALCULATE_DEBT_TO_EQUITY = "portfolio.calculate_debt_to_equity"
    CALCULATE_CASH_RUNWAY = "portfolio.calculate_cash_runway"
    CALCULATE_CAGR = "portfolio.calculate_cagr"
    SEARCH_MEMORY = "portfolio.search_memory"
    PROPOSE_MEMORY = "portfolio.propose_memory"


APPROVED_TOOL_NAMES: frozenset[str] = frozenset(item.value for item in ApprovedToolName)


class GatewayReasonCode(StrEnum):
    TOOL_COMPLETED = "TOOL_COMPLETED"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    TOOL_NOT_SHORTLISTED = "TOOL_NOT_SHORTLISTED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    INPUT_SCHEMA_REJECTED = "INPUT_SCHEMA_REJECTED"
    OUTPUT_SCHEMA_REJECTED = "OUTPUT_SCHEMA_REJECTED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_TRANSIENT_FAILURE = "TOOL_TRANSIENT_FAILURE"
    TOOL_FAILED_SAFE = "TOOL_FAILED_SAFE"
    CALCULATION_INPUTS_MISSING = "CALCULATION_INPUTS_MISSING"
    CALCULATION_INPUTS_INVALID = "CALCULATION_INPUTS_INVALID"
    CALCULATION_DIVISION_BY_ZERO = "CALCULATION_DIVISION_BY_ZERO"


class SearchAuthorizedDocumentsInput(StrictGatewayModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARACTERS)
    top_k: int = Field(ge=1, le=MAX_TOP_K)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Query must not be blank")
        return normalized


class GetDocumentExcerptInput(StrictGatewayModel):
    document_id: UUID
    chunk_id: UUID


class CalculateFinancialMetricInput(StrictGatewayModel):
    company_slug: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    reporting_period: str = Field(pattern=r"^FY[0-9]{4}$")


class FinancialMetricName(StrEnum):
    REVENUE = "revenue"
    EBITDA = "ebitda"
    NET_PROFIT = "net_profit"
    CLOSING_CASH = "closing_cash"
    BANK_DEBT = "bank_debt"


class QueryFinancialMetricsInput(CalculateFinancialMetricInput):
    metric: FinancialMetricName


class CalculateCagrInput(StrictGatewayModel):
    company_slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    start_period: str = Field(pattern=r"^FY[0-9]{4}$")
    end_period: str = Field(pattern=r"^FY[0-9]{4}$")
    metric: Literal["revenue"] = "revenue"

    @model_validator(mode="after")
    def ordered_periods(self) -> CalculateCagrInput:
        if int(self.end_period[2:]) <= int(self.start_period[2:]):
            raise ValueError("CAGR end period must follow start period")
        return self


class SearchMemoryInput(StrictGatewayModel):
    query: str = Field(min_length=1, max_length=300)
    mode: Literal["relevant", "latest_episode"]
    top_k: int = Field(default=3, ge=1, le=5)


class ProposeMemoryInput(StrictGatewayModel):
    content: str = Field(min_length=1, max_length=500)
    normalized_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    memory_type: Literal["SEMANTIC"] = "SEMANTIC"
    explicit: bool


class PermittedToolInputField(StrictGatewayModel):
    name: Literal[
        "query",
        "top_k",
        "document_id",
        "chunk_id",
        "company_slug",
        "reporting_period",
        "metric",
        "start_period",
        "end_period",
        "mode",
        "content",
        "normalized_key",
        "memory_type",
        "explicit",
    ]
    value_type: Literal["string", "integer", "boolean"]
    required: bool
    minimum: int | None = None
    maximum: int | None = None
    min_length: int | None = None
    max_length: int | None = None
    format: Literal["uuid"] | None = None


class PermittedToolInputSchema(StrictGatewayModel):
    fields: Annotated[tuple[PermittedToolInputField, ...], Field(min_length=1, max_length=5)]
    additional_properties: Literal[False] = False

    @model_validator(mode="after")
    def unique_fields(self) -> PermittedToolInputSchema:
        names = tuple(item.name for item in self.fields)
        if len(set(names)) != len(names):
            raise ValueError("Tool input fields must be unique")
        return self


class PermittedToolDescriptor(StrictGatewayModel):
    """Sanitized Decision-facing projection of one trusted manifest entry."""

    name: ApprovedToolName
    purpose: str = Field(min_length=1, max_length=180)
    input_schema: PermittedToolInputSchema
    safe_result_description: str = Field(min_length=1, max_length=180)


class EvidenceLocation(StrictGatewayModel):
    page_number: int | None = Field(default=None, ge=1)
    sheet_name: str | None = Field(default=None, max_length=128)
    row_start: int | None = Field(default=None, ge=1)
    row_end: int | None = Field(default=None, ge=1)
    cell_start: str | None = Field(default=None, max_length=32)
    cell_end: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def validate_provenance(self) -> EvidenceLocation:
        if (self.page_number is None) == (self.sheet_name is None):
            raise ValueError("Evidence must identify exactly one source location")
        if (self.row_start is None) != (self.row_end is None):
            raise ValueError("Spreadsheet row bounds must be paired")
        if (self.cell_start is None) != (self.cell_end is None):
            raise ValueError("Spreadsheet cell bounds must be paired")
        if self.page_number is not None and any(
            item is not None
            for item in (self.row_start, self.row_end, self.cell_start, self.cell_end)
        ):
            raise ValueError("PDF evidence cannot carry spreadsheet coordinates")
        if self.sheet_name is None and any(
            item is not None
            for item in (self.row_start, self.row_end, self.cell_start, self.cell_end)
        ):
            raise ValueError("Spreadsheet coordinates require a sheet")
        if (
            self.row_start is not None
            and self.row_end is not None
            and self.row_end < self.row_start
        ):
            raise ValueError("Spreadsheet row range is inverted")
        if self.cell_start is not None and self.cell_end is not None:
            try:
                start_row, start_column = coordinate_to_tuple(self.cell_start)
                end_row, end_column = coordinate_to_tuple(self.cell_end)
            except ValueError as exc:
                raise ValueError("Spreadsheet cell range is invalid") from exc
            if end_row < start_row or end_column < start_column:
                raise ValueError("Spreadsheet cell range is inverted")
        return self


class ToolEvidence(StrictGatewayModel):
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    document_title: str = Field(min_length=1, max_length=255)
    version_number: int = Field(ge=1)
    excerpt: str = Field(min_length=1, max_length=MAX_EXCERPT_CHARACTERS)
    location: EvidenceLocation

    @property
    def reference(self) -> str:
        return f"{self.document_id}:{self.document_version_id}:{self.chunk_id}"


class ToolPayload(StrictGatewayModel):
    evidence: Annotated[tuple[ToolEvidence, ...], Field(max_length=MAX_TOP_K)]


class CalculationPayload(StrictGatewayModel):
    calculations: Annotated[tuple[CalculationResult, ...], Field(min_length=1, max_length=1)]


class MemoryToolItem(StrictGatewayModel):
    memory_id: UUID
    memory_type: str = Field(pattern=r"^(?:SEMANTIC|EPISODIC|CONVERSATION_SUMMARY)$")
    scope: str = Field(pattern=r"^(?:PRIVATE_USER|DEPARTMENT|COMPANY)$")
    summary: str = Field(min_length=1, max_length=500)
    source_count: int = Field(ge=0, le=16)


class MemorySearchPayload(StrictGatewayModel):
    memories: Annotated[tuple[MemoryToolItem, ...], Field(max_length=5)]


class MemoryProposalPayload(StrictGatewayModel):
    proposed: Literal[True] = True
    policy_action: Literal["REVIEW_REQUIRED"] = "REVIEW_REQUIRED"
    notification: Literal["Memory proposal sent to host policy"] = (
        "Memory proposal sent to host policy"
    )


class StructuredToolObservation(StrictGatewayModel):
    """Typed gateway result. Only successful results may carry authorized evidence content."""

    schema_version: ClassVar[Literal["1"]] = "1"

    trace_id: UUID
    tool_name: ApprovedToolName | None
    status: Literal["completed", "denied", "failed"]
    reason_code: GatewayReasonCode
    retry_count: Annotated[int, Field(ge=0, le=1)] = 0
    duration_ms: Annotated[int, Field(ge=0)] = 0
    evidence: tuple[ToolEvidence, ...] = ()
    calculations: tuple[CalculationResult, ...] = ()
    memories: tuple[MemoryToolItem, ...] = ()
    memory_proposal: MemoryProposalPayload | None = None

    @model_validator(mode="after")
    def enforce_payload_shape(self) -> StructuredToolObservation:
        if self.status != "completed" and (
            self.evidence or self.calculations or self.memories or self.memory_proposal
        ):
            raise ValueError("Failed tool observations cannot carry payload content")
        payload_kinds = sum(
            bool(item)
            for item in (self.evidence, self.calculations, self.memories, self.memory_proposal)
        )
        if payload_kinds > 1:
            raise ValueError("A tool observation has exactly one payload kind")
        return self


class SanitizedToolTrace(StrictGatewayModel):
    """Content-free trace projection safe for logs and the user-visible timeline."""

    trace_id: UUID
    tool_name: ApprovedToolName | None
    status: Literal["completed", "denied", "failed"]
    reason_code: GatewayReasonCode
    retry_count: Annotated[int, Field(ge=0, le=1)]
    duration_ms: Annotated[int, Field(ge=0)]
    evidence_refs: tuple[str, ...]


def sanitize_observation(observation: StructuredToolObservation) -> SanitizedToolTrace:
    return SanitizedToolTrace(
        trace_id=observation.trace_id,
        tool_name=observation.tool_name,
        status=observation.status,
        reason_code=observation.reason_code,
        retry_count=observation.retry_count,
        duration_ms=observation.duration_ms,
        evidence_refs=tuple(item.reference for item in observation.evidence),
    )
