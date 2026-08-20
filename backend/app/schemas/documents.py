from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.documents import (
    DocumentClassification,
    DocumentType,
    DocumentVisibility,
    IngestionStatus,
)


class DocumentUploadMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: UUID
    company_id: UUID
    department: str = Field(pattern=r"^(finance|legal|shared)$")
    visibility: DocumentVisibility
    classification: DocumentClassification
    document_type: DocumentType
    reporting_period: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$",
    )

    @model_validator(mode="after")
    def validate_classification(self) -> "DocumentUploadMetadata":
        required_pair = {
            "finance": (
                DocumentVisibility.DEPARTMENT_PRIVATE,
                DocumentClassification.FINANCE_ONLY,
            ),
            "legal": (
                DocumentVisibility.DEPARTMENT_PRIVATE,
                DocumentClassification.LEGAL_ONLY_CONFIDENTIAL,
            ),
            "shared": (
                DocumentVisibility.TENANT_SHARED,
                DocumentClassification.TENANT_SHARED,
            ),
        }[self.department]
        if (self.visibility, self.classification) != required_pair:
            raise ValueError("Department, visibility, and classification are inconsistent")
        if (
            self.document_type in {DocumentType.FINANCIAL_REPORT, DocumentType.SPREADSHEET}
            and self.reporting_period is None
        ):
            raise ValueError("Reporting period is required for financial reports and spreadsheets")
        return self


class WarningData(BaseModel):
    code: str
    message: str


class DocumentScopeData(BaseModel):
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    company_id: UUID
    company_slug: str
    company_name: str
    department: str
    visibility: DocumentVisibility
    classification: DocumentClassification


class DocumentVersionData(BaseModel):
    id: UUID
    version_number: int
    original_filename: str
    media_type: str
    source_type: Literal["PDF", "XLSX", "CSV", "UNKNOWN"]
    checksum_sha256: str
    size_bytes: int
    status: IngestionStatus
    page_count: int
    sheet_count: int
    row_count: int
    cell_count: int
    warnings: tuple[WarningData, ...]
    uploaded_by_user_id: UUID
    approved_by_user_id: UUID | None
    created_at: datetime


class DocumentData(BaseModel):
    id: UUID
    scope: DocumentScopeData
    document_type: DocumentType
    reporting_period: str | None
    current_approved_version_id: UUID | None
    version: DocumentVersionData
    ingestion_job_id: UUID


class UploadResultData(BaseModel):
    document: DocumentData
    deduplicated: bool


class IngestionStatusData(BaseModel):
    ingestion_job_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    status: IngestionStatus
    safe_error_code: str | None
    warnings: tuple[WarningData, ...]
    page_count: int
    sheet_count: int
    row_count: int
    cell_count: int
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class ParsedPageData(BaseModel):
    page_number: int
    text: str


class ParsedCellData(BaseModel):
    row_number: int
    column_number: int
    coordinate: str
    value: str
    value_kind: str
    formula_like: bool


class ParsedRowData(BaseModel):
    row_number: int
    cells: tuple[ParsedCellData, ...]


class ParsedSheetData(BaseModel):
    sheet_index: int
    name: str
    row_count: int
    column_count: int
    rows: tuple[ParsedRowData, ...]


class DocumentPreviewData(BaseModel):
    document: DocumentData
    pages: tuple[ParsedPageData, ...]
    sheets: tuple[ParsedSheetData, ...]


class VersionActionData(BaseModel):
    document_id: UUID
    document_version_id: UUID
    status: IngestionStatus
    current_approved_version_id: UUID | None


class DeleteDocumentData(BaseModel):
    document_id: UUID
    status: IngestionStatus = IngestionStatus.DELETED


class DocumentListData(BaseModel):
    items: tuple[DocumentData, ...]
    total: int
    limit: int
    offset: int


class CompanyOptionData(BaseModel):
    id: UUID
    slug: str
    name: str


class TenantOptionData(BaseModel):
    id: UUID
    slug: str
    name: str
    companies: tuple[CompanyOptionData, ...]


class ClassificationPairData(BaseModel):
    department: str
    visibility: DocumentVisibility
    classification: DocumentClassification
    label: str


class DocumentTypeOptionData(BaseModel):
    value: DocumentType
    label: str
    reporting_period_required: bool


class UploadLimitsData(BaseModel):
    max_upload_bytes: int
    extensions: tuple[str, ...]
    mime_types: tuple[str, ...]


class DocumentOptionsData(BaseModel):
    tenants: tuple[TenantOptionData, ...]
    classification_pairs: tuple[ClassificationPairData, ...]
    document_types: tuple[DocumentTypeOptionData, ...]
    limits: UploadLimitsData
