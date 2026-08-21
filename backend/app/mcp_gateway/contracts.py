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


class PermittedToolInputField(StrictGatewayModel):
    name: Literal[
        "query",
        "top_k",
        "document_id",
        "chunk_id",
        "company_slug",
        "reporting_period",
    ]
    value_type: Literal["string", "integer"]
    required: bool
    minimum: int | None = None
    maximum: int | None = None
    min_length: int | None = None
    max_length: int | None = None
    format: Literal["uuid"] | None = None


class PermittedToolInputSchema(StrictGatewayModel):
    fields: Annotated[tuple[PermittedToolInputField, ...], Field(min_length=2, max_length=2)]
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

    @model_validator(mode="after")
    def enforce_payload_shape(self) -> StructuredToolObservation:
        if self.status != "completed" and (self.evidence or self.calculations):
            raise ValueError("Failed tool observations cannot carry payload content")
        if self.evidence and self.calculations:
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
