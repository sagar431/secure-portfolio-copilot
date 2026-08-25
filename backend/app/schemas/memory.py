from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MemoryScopeValue = Literal["PRIVATE_USER", "FINANCE", "LEGAL", "SHARED"]
MemoryTypeValue = Literal["SEMANTIC", "EPISODIC", "CONVERSATION_SUMMARY"]
MemoryOriginValue = Literal["EXPLICIT_USER", "AUTOMATIC_EXTRACTOR", "SYSTEM_SUMMARY"]
MemoryStatusValue = Literal["PENDING_CONFIRMATION", "ACTIVE", "SUPERSEDED", "EXPIRED", "DELETED"]
UUIDInput = Annotated[UUID, Field(strict=False)]


class CreateMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    content: str = Field(min_length=1, max_length=1000)
    company_id: UUIDInput
    scope: MemoryScopeValue
    source_chunk_ids: list[UUIDInput] = Field(default_factory=list, max_length=8)
    expires_in_days: int = Field(default=90, ge=1, le=365)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Memory content must not be blank")
        return normalized

    @field_validator("source_chunk_ids")
    @classmethod
    def unique_sources(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Memory sources must be unique")
        return value


class SearchMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: str = Field(min_length=1, max_length=300)
    top_k: int = Field(default=10, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Memory query must not be blank")
        return normalized


class MemorySourceData(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_name: str


class MemoryData(BaseModel):
    id: UUID
    company_id: UUID
    scope: MemoryScopeValue
    memory_type: MemoryTypeValue
    origin: MemoryOriginValue
    status: MemoryStatusValue
    owner_user_id: UUID | None
    department: Literal["finance", "legal", "shared"]
    visibility: Literal["DEPARTMENT_PRIVATE", "TENANT_SHARED"]
    classification: Literal["FINANCE_ONLY", "LEGAL_ONLY_CONFIDENTIAL", "TENANT_SHARED"]
    content: str
    normalized_key: str | None
    reason: str
    confidence: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    owner_display: str
    tenant_display: str
    company_display: str
    source_conversation: str | None
    expires_at: datetime
    created_at: datetime
    can_delete: bool
    can_confirm: bool
    sources: tuple[MemorySourceData, ...]


class MemoryListData(BaseModel):
    memories: tuple[MemoryData, ...]


class DeletedMemoryData(BaseModel):
    memory_id: UUID
    deleted: Literal[True] = True


class MemoryMutationData(BaseModel):
    memory: MemoryData
