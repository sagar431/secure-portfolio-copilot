from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.identity import Company, Department, Tenant, TimestampMixin


class IngestionStatus(StrEnum):
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    PARSING = "PARSING"
    PREVIEW_READY = "PREVIEW_READY"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    PARSING_FAILED = "PARSING_FAILED"
    DELETED = "DELETED"


class DocumentVisibility(StrEnum):
    DEPARTMENT_PRIVATE = "DEPARTMENT_PRIVATE"
    TENANT_SHARED = "TENANT_SHARED"


class DocumentClassification(StrEnum):
    FINANCE_ONLY = "FINANCE_ONLY"
    LEGAL_ONLY_CONFIDENTIAL = "LEGAL_ONLY_CONFIDENTIAL"
    TENANT_SHARED = "TENANT_SHARED"


class DocumentType(StrEnum):
    FINANCIAL_REPORT = "FINANCIAL_REPORT"
    LEGAL_AGREEMENT = "LEGAL_AGREEMENT"
    POLICY = "POLICY"
    EMAIL = "EMAIL"
    SPREADSHEET = "SPREADSHEET"
    OTHER = "OTHER"


INGESTION_STATUS_VALUES = ", ".join(f"'{item.value}'" for item in IngestionStatus)
VISIBILITY_VALUES = ", ".join(f"'{item.value}'" for item in DocumentVisibility)
CLASSIFICATION_VALUES = ", ".join(f"'{item.value}'" for item in DocumentClassification)
DOCUMENT_TYPE_VALUES = ", ".join(f"'{item.value}'" for item in DocumentType)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"visibility IN ({VISIBILITY_VALUES})", name="ck_documents_visibility"),
        CheckConstraint(
            f"classification IN ({CLASSIFICATION_VALUES})",
            name="ck_documents_classification",
        ),
        CheckConstraint(
            f"document_type IN ({DOCUMENT_TYPE_VALUES})", name="ck_documents_document_type"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id"), nullable=False, index=True
    )
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reporting_period: Mapped[str | None] = mapped_column(String(64))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    current_approved_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "document_versions.id",
            name="fk_documents_current_approved_version",
            use_alter=True,
        )
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(foreign_keys=[tenant_id])
    company: Mapped[Company] = relationship(foreign_keys=[company_id])
    department: Mapped[Department] = relationship(foreign_keys=[department_id])
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        foreign_keys="DocumentVersion.document_id",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number",
    )


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
        UniqueConstraint(
            "uploaded_by_user_id",
            "idempotency_key",
            name="uq_document_versions_actor_idempotency_key",
        ),
        CheckConstraint(
            f"status IN ({INGESTION_STATUS_VALUES})", name="ck_document_versions_status"
        ),
        CheckConstraint("version_number > 0", name="ck_document_versions_number_positive"),
        CheckConstraint("size_bytes >= 0", name="ck_document_versions_size_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    declared_media_type: Mapped[str] = mapped_column(String(160), nullable=False)
    detected_media_type: Mapped[str] = mapped_column(String(160), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(
        String(32), default=IngestionStatus.UPLOADED, nullable=False, index=True
    )
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sheet_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cell_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uploaded_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="versions", foreign_keys=[document_id])
    ingestion_job: Mapped[IngestionJob] = relationship(
        back_populates="document_version", cascade="all, delete-orphan", uselist=False
    )
    pages: Mapped[list[ParsedPage]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
        order_by="ParsedPage.page_number",
    )
    sheets: Mapped[list[ParsedSheet]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
        order_by="ParsedSheet.sheet_index",
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.ordinal",
    )


class IngestionJob(TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(f"status IN ({INGESTION_STATUS_VALUES})", name="ck_ingestion_jobs_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), default=IngestionStatus.UPLOADED, nullable=False, index=True
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document_version: Mapped[DocumentVersion] = relationship(back_populates="ingestion_job")


class ParsedPage(TimestampMixin, Base):
    __tablename__ = "parsed_pages"
    __table_args__ = (
        UniqueConstraint("document_version_id", "page_number", name="uq_parsed_pages_version_page"),
        CheckConstraint("page_number > 0", name="ck_parsed_pages_number_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="pages")


class ParsedSheet(TimestampMixin, Base):
    __tablename__ = "parsed_sheets"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "sheet_index", name="uq_parsed_sheets_version_index"
        ),
        UniqueConstraint("document_version_id", "name", name="uq_parsed_sheets_version_name"),
        CheckConstraint("sheet_index >= 0", name="ck_parsed_sheets_index_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sheet_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="sheets")
    rows: Mapped[list[ParsedRow]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", order_by="ParsedRow.row_number"
    )


class ParsedRow(TimestampMixin, Base):
    __tablename__ = "parsed_rows"
    __table_args__ = (
        UniqueConstraint("sheet_id", "row_number", name="uq_parsed_rows_sheet_row"),
        CheckConstraint("row_number > 0", name="ck_parsed_rows_number_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sheet_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_sheets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)

    sheet: Mapped[ParsedSheet] = relationship(back_populates="rows")
    cells: Mapped[list[ParsedCell]] = relationship(
        back_populates="row", cascade="all, delete-orphan", order_by="ParsedCell.column_number"
    )


class ParsedCell(TimestampMixin, Base):
    __tablename__ = "parsed_cells"
    __table_args__ = (
        UniqueConstraint("row_id", "column_number", name="uq_parsed_cells_row_column"),
        CheckConstraint("column_number > 0", name="ck_parsed_cells_column_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    row_id: Mapped[UUID] = mapped_column(
        ForeignKey("parsed_rows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    column_number: Mapped[int] = mapped_column(Integer, nullable=False)
    coordinate: Mapped[str] = mapped_column(String(24), nullable=False)
    value_text: Mapped[str] = mapped_column(Text, nullable=False)
    value_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    formula_like: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    row: Mapped[ParsedRow] = relationship(back_populates="cells")


class DocumentChunk(TimestampMixin, Base):
    """Searchable content with copied ACL, lifecycle, and source metadata."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "ordinal", name="uq_document_chunks_version_ordinal"
        ),
        CheckConstraint("ordinal >= 0", name="ck_document_chunks_ordinal_nonnegative"),
        CheckConstraint("version_number > 0", name="ck_document_chunks_version_number_positive"),
        CheckConstraint(
            "source_type IN ('pdf', 'xlsx', 'csv')", name="ck_document_chunks_source_type"
        ),
        CheckConstraint(
            "version_status IN ('APPROVED', 'REJECTED', 'DELETED')",
            name="ck_document_chunks_version_status",
        ),
        CheckConstraint(
            "NOT active OR (version_status = 'APPROVED' "
            "AND NOT document_deleted AND NOT version_deleted)",
            name="ck_document_chunks_active_lifecycle",
        ),
        CheckConstraint(
            "(department = 'finance' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'FINANCE_ONLY') OR "
            "(department = 'legal' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'LEGAL_ONLY_CONFIDENTIAL') OR "
            "(department = 'shared' AND visibility = 'TENANT_SHARED' "
            "AND classification = 'TENANT_SHARED')",
            name="ck_document_chunks_acl_metadata",
        ),
        CheckConstraint(
            "char_length(content) BETWEEN 1 AND 2000",
            name="ck_document_chunks_content_length",
        ),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_document_chunks_content_hash_length",
        ),
        CheckConstraint(
            "embedding_status IN ('PENDING', 'READY', 'FAILED', 'STALE')",
            name="ck_document_chunks_embedding_status",
        ),
        CheckConstraint(
            "(embedding_status = 'READY' AND embedding IS NOT NULL "
            "AND embedding_model_name IS NOT NULL AND embedding_model_version IS NOT NULL "
            "AND embedding_dimensions = 768 AND embedding_chunk_hash = content_hash) OR "
            "(embedding_status <> 'READY' AND embedding IS NULL)",
            name="ck_document_chunks_embedding_ready",
        ),
        CheckConstraint(
            "(source_type = 'pdf' AND page_number IS NOT NULL "
            "AND sheet_name IS NULL AND row_start IS NULL AND row_end IS NULL "
            "AND cell_start IS NULL AND cell_end IS NULL) OR "
            "(source_type IN ('xlsx', 'csv') AND page_number IS NULL "
            "AND sheet_name IS NOT NULL AND row_start IS NOT NULL AND row_end IS NOT NULL "
            "AND cell_start IS NOT NULL AND cell_end IS NOT NULL)",
            name="ck_document_chunks_provenance",
        ),
        CheckConstraint(
            "(page_number IS NULL OR page_number > 0) AND "
            "(row_start IS NULL OR row_start > 0) AND "
            "(row_end IS NULL OR row_end >= row_start)",
            name="ck_document_chunks_location_ranges",
        ),
        Index(
            "ix_document_chunks_acl_lifecycle",
            "tenant_id",
            "company_id",
            "department",
            "visibility",
            "active",
            "version_status",
        ),
        Index("ix_document_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_document_chunks_embedding_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id"), nullable=False, index=True
    )
    department: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    document_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(128))
    row_start: Mapped[int | None] = mapped_column(Integer)
    row_end: Mapped[int | None] = mapped_column(Integer)
    cell_start: Mapped[str | None] = mapped_column(String(24))
    cell_end: Mapped[str | None] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    embedding_model_name: Mapped[str | None] = mapped_column(String(128))
    embedding_model_version: Mapped[str | None] = mapped_column(String(64))
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    embedding_chunk_hash: Mapped[str | None] = mapped_column(String(64))
    embedding_status: Mapped[str] = mapped_column(
        String(16), default="PENDING", nullable=False, index=True
    )
    search_vector: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(content, ''))", persisted=True),
        nullable=False,
    )

    document: Mapped[Document] = relationship(foreign_keys=[document_id])
    document_version: Mapped[DocumentVersion] = relationship(
        back_populates="chunks", foreign_keys=[document_version_id]
    )
    tenant: Mapped[Tenant] = relationship(foreign_keys=[tenant_id])
    company: Mapped[Company] = relationship(foreign_keys=[company_id])
    source_department: Mapped[Department] = relationship(foreign_keys=[department_id])


class DocumentAuditEvent(Base):
    __tablename__ = "document_audit_events"
    __table_args__ = (
        CheckConstraint("outcome IN ('allow', 'deny', 'error')", name="ck_document_audit_outcome"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    company_id: Mapped[UUID | None] = mapped_column(ForeignKey("companies.id"), index=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"), index=True)
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id"), index=True
    )
    ingestion_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("ingestion_jobs.id"))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
