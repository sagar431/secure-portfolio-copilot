"""Add governed document ingestion tables.

Revision ID: 20260821_0003
Revises: 20260820_0002
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_0003"
down_revision: str | None = "20260820_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = (
    "'UPLOADED', 'VALIDATING', 'PARSING', 'PREVIEW_READY', 'APPROVED', "
    "'REJECTED', 'VALIDATION_FAILED', 'PARSING_FAILED', 'DELETED'"
)


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("reporting_period", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("current_approved_version_id", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "visibility IN ('DEPARTMENT_PRIVATE', 'TENANT_SHARED')",
            name="ck_documents_visibility",
        ),
        sa.CheckConstraint(
            "classification IN ('FINANCE_ONLY', 'LEGAL_ONLY_CONFIDENTIAL', 'TENANT_SHARED')",
            name="ck_documents_classification",
        ),
        sa.CheckConstraint(
            "document_type IN ('FINANCIAL_REPORT', 'LEGAL_AGREEMENT', 'POLICY', "
            "'EMAIL', 'SPREADSHEET', 'OTHER')",
            name="ck_documents_document_type",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_company_id"), "documents", ["company_id"], unique=False)
    op.create_index(
        op.f("ix_documents_department_id"), "documents", ["department_id"], unique=False
    )
    op.create_index(op.f("ix_documents_tenant_id"), "documents", ["tenant_id"], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("safe_filename", sa.String(length=255), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("declared_media_type", sa.String(length=160), nullable=False),
        sa.Column("detected_media_type", sa.String(length=160), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("sheet_count", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("cell_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_document_versions_status"),
        sa.CheckConstraint("version_number > 0", name="ck_document_versions_number_positive"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_document_versions_size_nonnegative"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rejected_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "uploaded_by_user_id",
            "idempotency_key",
            name="uq_document_versions_actor_idempotency_key",
        ),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        op.f("ix_document_versions_checksum_sha256"),
        "document_versions",
        ["checksum_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_versions_document_id"),
        "document_versions",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_versions_status"), "document_versions", ["status"], unique=False
    )
    op.create_foreign_key(
        "fk_documents_current_approved_version",
        "documents",
        "document_versions",
        ["current_approved_version_id"],
        ["id"],
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_ingestion_jobs_status"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ingestion_jobs_document_version_id"),
        "ingestion_jobs",
        ["document_version_id"],
        unique=True,
    )
    op.create_index(op.f("ix_ingestion_jobs_status"), "ingestion_jobs", ["status"], unique=False)

    op.create_table(
        "parsed_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("page_number > 0", name="ck_parsed_pages_number_positive"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id", "page_number", name="uq_parsed_pages_version_page"
        ),
    )
    op.create_index(
        op.f("ix_parsed_pages_document_version_id"),
        "parsed_pages",
        ["document_version_id"],
        unique=False,
    )

    op.create_table(
        "parsed_sheets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("sheet_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("sheet_index >= 0", name="ck_parsed_sheets_index_nonnegative"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id", "sheet_index", name="uq_parsed_sheets_version_index"
        ),
        sa.UniqueConstraint("document_version_id", "name", name="uq_parsed_sheets_version_name"),
    )
    op.create_index(
        op.f("ix_parsed_sheets_document_version_id"),
        "parsed_sheets",
        ["document_version_id"],
        unique=False,
    )

    op.create_table(
        "parsed_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sheet_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("row_number > 0", name="ck_parsed_rows_number_positive"),
        sa.ForeignKeyConstraint(["sheet_id"], ["parsed_sheets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sheet_id", "row_number", name="uq_parsed_rows_sheet_row"),
    )
    op.create_index(op.f("ix_parsed_rows_sheet_id"), "parsed_rows", ["sheet_id"], unique=False)

    op.create_table(
        "parsed_cells",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("row_id", sa.Uuid(), nullable=False),
        sa.Column("column_number", sa.Integer(), nullable=False),
        sa.Column("coordinate", sa.String(length=24), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column("value_kind", sa.String(length=32), nullable=False),
        sa.Column("formula_like", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("column_number > 0", name="ck_parsed_cells_column_positive"),
        sa.ForeignKeyConstraint(["row_id"], ["parsed_rows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("row_id", "column_number", name="uq_parsed_cells_row_column"),
    )
    op.create_index(op.f("ix_parsed_cells_row_id"), "parsed_cells", ["row_id"], unique=False)

    op.create_table(
        "document_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("ingestion_job_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("event_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "outcome IN ('allow', 'deny', 'error')", name="ck_document_audit_outcome"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["ingestion_job_id"], ["ingestion_jobs.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_audit_events_actor_user_id"),
        "document_audit_events",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_audit_events_company_id"),
        "document_audit_events",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_audit_events_document_id"),
        "document_audit_events",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_audit_events_document_version_id"),
        "document_audit_events",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_audit_events_tenant_id"),
        "document_audit_events",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_audit_events_tenant_id"), table_name="document_audit_events")
    op.drop_index(
        op.f("ix_document_audit_events_document_version_id"),
        table_name="document_audit_events",
    )
    op.drop_index(op.f("ix_document_audit_events_document_id"), table_name="document_audit_events")
    op.drop_index(op.f("ix_document_audit_events_company_id"), table_name="document_audit_events")
    op.drop_index(
        op.f("ix_document_audit_events_actor_user_id"), table_name="document_audit_events"
    )
    op.drop_table("document_audit_events")
    op.drop_index(op.f("ix_parsed_cells_row_id"), table_name="parsed_cells")
    op.drop_table("parsed_cells")
    op.drop_index(op.f("ix_parsed_rows_sheet_id"), table_name="parsed_rows")
    op.drop_table("parsed_rows")
    op.drop_index(op.f("ix_parsed_sheets_document_version_id"), table_name="parsed_sheets")
    op.drop_table("parsed_sheets")
    op.drop_index(op.f("ix_parsed_pages_document_version_id"), table_name="parsed_pages")
    op.drop_table("parsed_pages")
    op.drop_index(op.f("ix_ingestion_jobs_status"), table_name="ingestion_jobs")
    op.drop_index(op.f("ix_ingestion_jobs_document_version_id"), table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_constraint("fk_documents_current_approved_version", "documents", type_="foreignkey")
    op.drop_index(op.f("ix_document_versions_status"), table_name="document_versions")
    op.drop_index(op.f("ix_document_versions_document_id"), table_name="document_versions")
    op.drop_index(op.f("ix_document_versions_checksum_sha256"), table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index(op.f("ix_documents_tenant_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_department_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_company_id"), table_name="documents")
    op.drop_table("documents")
