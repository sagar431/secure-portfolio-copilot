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


class EmbeddingReindexData(BaseModel):
    status: Literal["ready"] = "ready"
    processed_chunk_count: int = Field(ge=0)


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


class SearchEmbeddingData(BaseModel):
    status: Literal["ready", "indexing", "degraded", "unavailable"]
    model: str
    dimensions: int = Field(ge=1)
    embedded_chunk_count: int = Field(ge=0)
    pending_chunk_count: int = Field(ge=0)
    failed_chunk_count: int = Field(ge=0)


class SearchIndexingData(BaseModel):
    status: Literal["ready", "indexing", "degraded"] = "ready"
    active_chunk_count: int = Field(ge=0)
    indexed_document_count: int = Field(ge=0)
    embedding: SearchEmbeddingData


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
    scores: "SearchScoresData"
    citation: "SearchCitationData"
    source: SearchSourceData
    document: SearchDocumentData


class SearchScoresData(BaseModel):
    keyword: float = Field(ge=0, le=1)
    vector: float = Field(ge=0, le=1)
    final: float = Field(ge=0, le=1)


class SearchCitationData(BaseModel):
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


class RetrievalEvaluationNotRun(BaseModel):
    status: Literal["not_run"] = "not_run"


class RetrievalEvaluationComplete(BaseModel):
    status: Literal["complete"] = "complete"
    dataset_name: str
    curated_query_count: int = Field(ge=0)
    recall_at_5: float = Field(ge=0, le=1)
    expected_top_5_hits: int = Field(ge=0)
    authorization_leak_count: int = Field(ge=0)


class AuthorizedSearchData(BaseModel):
    status: Literal["ready", "indexing", "degraded"] = "ready"
    query: str
    top_k: int
    result_count: int = Field(ge=0)
    authorized_scope: SearchScopeData
    indexing: SearchIndexingData
    evaluation_summary: RetrievalEvaluationNotRun | RetrievalEvaluationComplete = (
        RetrievalEvaluationNotRun()
    )
    results: tuple[AuthorizedSearchResultData, ...]
