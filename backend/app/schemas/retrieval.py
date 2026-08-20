from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.retrieval.limits import DEFAULT_TOP_K, MAX_QUERY_CHARACTERS, MAX_TOP_K


class AuthorizedSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARACTERS)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Query must not be blank")
        return normalized


class SearchWorkspaceData(BaseModel):
    id: UUID
    slug: str
    name: str


class SearchScopeGrantData(BaseModel):
    workspace: SearchWorkspaceData
    company_ids: tuple[UUID, ...]
    company_slugs: tuple[str, ...]
    query_departments: tuple[str, ...]


class SearchScopeData(BaseModel):
    grants: tuple[SearchScopeGrantData, ...]


class SearchIndexingData(BaseModel):
    status: Literal["ready", "indexing"] = "ready"
    active_chunk_count: int = Field(ge=0)
    indexed_document_count: int = Field(ge=0)


class SearchSourceData(BaseModel):
    page_number: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    cell_start: str | None
    cell_end: str | None


class SearchDocumentData(BaseModel):
    filename: str
    source_type: Literal["PDF", "XLSX", "CSV", "UNKNOWN"]
    document_type: str
    reporting_period: str | None
    tenant_slug: str
    company_slug: str
    department: str
    visibility: str
    classification: str


class AuthorizedSearchResultData(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int = Field(ge=1)
    excerpt: str
    score: float = Field(ge=0)
    source: SearchSourceData
    document: SearchDocumentData


class AuthorizedSearchData(BaseModel):
    status: Literal["ready", "indexing"] = "ready"
    query: str
    top_k: int
    result_count: int = Field(ge=0)
    authorized_scope: SearchScopeData
    indexing: SearchIndexingData
    results: tuple[AuthorizedSearchResultData, ...]
