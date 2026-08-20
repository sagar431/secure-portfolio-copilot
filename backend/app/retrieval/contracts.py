from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    excerpt: str
    score: float
    page_number: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    cell_start: str | None
    cell_end: str | None
    filename: str
    source_type: str
    document_type: str
    reporting_period: str | None
    tenant_slug: str
    company_slug: str
    department: str
    visibility: str
    classification: str


@dataclass(frozen=True, slots=True)
class AuthorizedIndexStatus:
    active_chunk_count: int
    indexed_document_count: int
