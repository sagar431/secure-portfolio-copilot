"""Add secure document chunks and PostgreSQL full-text index.

Revision ID: 20260821_0004
Revises: 20260821_0003
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260821_0004"
down_revision: str | None = "20260821_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("version_status", sa.String(length=32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("document_deleted", sa.Boolean(), nullable=False),
        sa.Column("version_deleted", sa.Boolean(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("sheet_name", sa.String(length=128), nullable=True),
        sa.Column("row_start", sa.Integer(), nullable=True),
        sa.Column("row_end", sa.Integer(), nullable=True),
        sa.Column("cell_start", sa.String(length=24), nullable=True),
        sa.Column("cell_end", sa.String(length=24), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(content, ''))", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_document_chunks_ordinal_nonnegative"),
        sa.CheckConstraint("version_number > 0", name="ck_document_chunks_version_number_positive"),
        sa.CheckConstraint(
            "source_type IN ('pdf', 'xlsx', 'csv')", name="ck_document_chunks_source_type"
        ),
        sa.CheckConstraint(
            "version_status IN ('APPROVED', 'REJECTED', 'DELETED')",
            name="ck_document_chunks_version_status",
        ),
        sa.CheckConstraint(
            "NOT active OR (version_status = 'APPROVED' "
            "AND NOT document_deleted AND NOT version_deleted)",
            name="ck_document_chunks_active_lifecycle",
        ),
        sa.CheckConstraint(
            "(department = 'finance' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'FINANCE_ONLY') OR "
            "(department = 'legal' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'LEGAL_ONLY_CONFIDENTIAL') OR "
            "(department = 'shared' AND visibility = 'TENANT_SHARED' "
            "AND classification = 'TENANT_SHARED')",
            name="ck_document_chunks_acl_metadata",
        ),
        sa.CheckConstraint(
            "char_length(content) BETWEEN 1 AND 2000",
            name="ck_document_chunks_content_length",
        ),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_document_chunks_content_hash_length",
        ),
        sa.CheckConstraint(
            "(source_type = 'pdf' AND page_number IS NOT NULL "
            "AND sheet_name IS NULL AND row_start IS NULL AND row_end IS NULL "
            "AND cell_start IS NULL AND cell_end IS NULL) OR "
            "(source_type IN ('xlsx', 'csv') AND page_number IS NULL "
            "AND sheet_name IS NOT NULL AND row_start IS NOT NULL AND row_end IS NOT NULL "
            "AND cell_start IS NOT NULL AND cell_end IS NOT NULL)",
            name="ck_document_chunks_provenance",
        ),
        sa.CheckConstraint(
            "(page_number IS NULL OR page_number > 0) AND "
            "(row_start IS NULL OR row_start > 0) AND "
            "(row_end IS NULL OR row_end >= row_start)",
            name="ck_document_chunks_location_ranges",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id", "ordinal", name="uq_document_chunks_version_ordinal"
        ),
    )
    for column in (
        "document_id",
        "document_version_id",
        "tenant_id",
        "company_id",
        "department_id",
        "version_status",
        "active",
        "content_hash",
    ):
        op.create_index(op.f(f"ix_document_chunks_{column}"), "document_chunks", [column])
    op.create_index(
        "ix_document_chunks_acl_lifecycle",
        "document_chunks",
        [
            "tenant_id",
            "company_id",
            "department",
            "visibility",
            "active",
            "version_status",
        ],
    )
    op.create_index(
        "ix_document_chunks_search_vector",
        "document_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_search_vector", table_name="document_chunks")
    op.drop_index("ix_document_chunks_acl_lifecycle", table_name="document_chunks")
    for column in reversed(
        (
            "document_id",
            "document_version_id",
            "tenant_id",
            "company_id",
            "department_id",
            "version_status",
            "active",
            "content_hash",
        )
    ):
        op.drop_index(op.f(f"ix_document_chunks_{column}"), table_name="document_chunks")
    op.drop_table("document_chunks")
