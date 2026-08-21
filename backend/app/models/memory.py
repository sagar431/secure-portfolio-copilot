from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.identity import TimestampMixin


class MemoryScope(StrEnum):
    PRIVATE_USER = "PRIVATE_USER"
    FINANCE = "FINANCE"
    LEGAL = "LEGAL"
    SHARED = "SHARED"


class Memory(TimestampMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('PRIVATE_USER', 'FINANCE', 'LEGAL', 'SHARED')",
            name="ck_memories_scope",
        ),
        CheckConstraint(
            "(scope = 'PRIVATE_USER' AND owner_user_id IS NOT NULL) OR "
            "(scope <> 'PRIVATE_USER' AND owner_user_id IS NULL)",
            name="ck_memories_private_owner",
        ),
        CheckConstraint(
            "(scope = 'FINANCE' AND department = 'finance' "
            "AND visibility = 'DEPARTMENT_PRIVATE' AND classification = 'FINANCE_ONLY') OR "
            "(scope = 'LEGAL' AND department = 'legal' "
            "AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'LEGAL_ONLY_CONFIDENTIAL') OR "
            "(scope = 'SHARED' AND department = 'shared' "
            "AND visibility = 'TENANT_SHARED' AND classification = 'TENANT_SHARED') OR "
            "scope = 'PRIVATE_USER'",
            name="ck_memories_scope_acl",
        ),
        CheckConstraint(
            "(department = 'finance' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'FINANCE_ONLY') OR "
            "(department = 'legal' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'LEGAL_ONLY_CONFIDENTIAL') OR "
            "(department = 'shared' AND visibility = 'TENANT_SHARED' "
            "AND classification = 'TENANT_SHARED')",
            name="ck_memories_acl",
        ),
        CheckConstraint("char_length(content) BETWEEN 1 AND 1000", name="ck_memories_content"),
        CheckConstraint("char_length(content_hash) = 64", name="ck_memories_content_hash"),
        Index(
            "ix_memories_scope_filter",
            "tenant_id",
            "company_id",
            "scope",
            "department",
            "classification",
            "expires_at",
            "deleted_at",
        ),
        Index("ix_memories_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    department: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    search_vector: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(content, ''))", persisted=True),
        nullable=False,
    )

    sources: Mapped[list[MemorySource]] = relationship(
        back_populates="memory", cascade="all, delete-orphan", order_by="MemorySource.id"
    )


class MemorySource(Base):
    __tablename__ = "memory_sources"
    __table_args__ = (
        UniqueConstraint("memory_id", "chunk_id", name="uq_memory_sources_memory_chunk"),
        CheckConstraint(
            "(department = 'finance' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'FINANCE_ONLY') OR "
            "(department = 'legal' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'LEGAL_ONLY_CONFIDENTIAL') OR "
            "(department = 'shared' AND visibility = 'TENANT_SHARED' "
            "AND classification = 'TENANT_SHARED')",
            name="ck_memory_sources_acl",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), nullable=False)
    department: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)

    memory: Mapped[Memory] = relationship(back_populates="sources")
