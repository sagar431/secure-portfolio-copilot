from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.identity import TimestampMixin

if TYPE_CHECKING:
    from app.models.chat import Conversation
    from app.models.documents import DocumentVersion


class MemoryScope(StrEnum):
    PRIVATE_USER = "PRIVATE_USER"
    FINANCE = "FINANCE"
    LEGAL = "LEGAL"
    SHARED = "SHARED"


class MemoryType(StrEnum):
    SEMANTIC = "SEMANTIC"
    EPISODIC = "EPISODIC"
    CONVERSATION_SUMMARY = "CONVERSATION_SUMMARY"


class MemoryOrigin(StrEnum):
    EXPLICIT_USER = "EXPLICIT_USER"
    AUTOMATIC_EXTRACTOR = "AUTOMATIC_EXTRACTOR"
    SYSTEM_SUMMARY = "SYSTEM_SUMMARY"


class MemoryStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class Memory(TimestampMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('PRIVATE_USER', 'FINANCE', 'LEGAL', 'SHARED')",
            name="ck_memories_scope",
        ),
        CheckConstraint(
            "memory_type IN ('SEMANTIC', 'EPISODIC', 'CONVERSATION_SUMMARY')",
            name="ck_memories_type",
        ),
        CheckConstraint(
            "origin IN ('EXPLICIT_USER', 'AUTOMATIC_EXTRACTOR', 'SYSTEM_SUMMARY')",
            name="ck_memories_origin",
        ),
        CheckConstraint(
            "status IN ('PENDING_CONFIRMATION', 'ACTIVE', 'SUPERSEDED', 'EXPIRED', 'DELETED')",
            name="ck_memories_status",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_memories_confidence"),
        CheckConstraint("importance BETWEEN 0 AND 1", name="ck_memories_importance"),
        CheckConstraint(
            "memory_type <> 'CONVERSATION_SUMMARY' OR conversation_id IS NOT NULL",
            name="ck_memories_summary_conversation",
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
        Index(
            "ix_memories_authorized_retrieval",
            "tenant_id",
            "owner_user_id",
            "company_id",
            "memory_type",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    memory_type: Mapped[str] = mapped_column(
        String(32), default=MemoryType.SEMANTIC.value, nullable=False, index=True
    )
    origin: Mapped[str] = mapped_column(
        String(32), default=MemoryOrigin.EXPLICIT_USER.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default=MemoryStatus.ACTIVE.value, nullable=False, index=True
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    source_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    department: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    normalized_key: Mapped[str | None] = mapped_column(String(160), index=True)
    reason: Mapped[str] = mapped_column(String(240), default="User-created memory", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), index=True
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    conversation: Mapped[Conversation | None] = relationship(foreign_keys=[conversation_id])


class MemoryAuditEvent(Base):
    """Metadata-only durable audit event; memory content is intentionally excluded."""

    __tablename__ = "memory_audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('CREATE', 'CONFIRM', 'DISMISS', 'SUPERSEDE', "
            "'REFRESH', 'DELETE', 'EXPIRE')",
            name="ck_memory_audit_events_action",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
    document_version: Mapped[DocumentVersion] = relationship(foreign_keys=[document_version_id])
