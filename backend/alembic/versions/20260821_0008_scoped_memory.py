"""Add source-inheriting scoped memory.

Revision ID: 20260821_0008
Revises: 20260821_0007
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260821_0008"
down_revision: str | None = "20260821_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "scope IN ('PRIVATE_USER', 'FINANCE', 'LEGAL', 'SHARED')",
            name="ck_memories_scope",
        ),
        sa.CheckConstraint(
            "(scope = 'PRIVATE_USER' AND owner_user_id IS NOT NULL) OR "
            "(scope <> 'PRIVATE_USER' AND owner_user_id IS NULL)",
            name="ck_memories_private_owner",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "(department = 'finance' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'FINANCE_ONLY') OR "
            "(department = 'legal' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'LEGAL_ONLY_CONFIDENTIAL') OR "
            "(department = 'shared' AND visibility = 'TENANT_SHARED' "
            "AND classification = 'TENANT_SHARED')",
            name="ck_memories_acl",
        ),
        sa.CheckConstraint("char_length(content) BETWEEN 1 AND 1000", name="ck_memories_content"),
        sa.CheckConstraint("char_length(content_hash) = 64", name="ck_memories_content_hash"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "tenant_id",
        "company_id",
        "scope",
        "owner_user_id",
        "created_by_user_id",
        "content_hash",
        "expires_at",
        "deleted_at",
    ):
        op.create_index(f"ix_memories_{column}", "memories", [column])
    op.create_index(
        "ix_memories_scope_filter",
        "memories",
        [
            "tenant_id",
            "company_id",
            "scope",
            "department",
            "classification",
            "expires_at",
            "deleted_at",
        ],
    )
    op.create_index(
        "ix_memories_search_vector", "memories", ["search_vector"], postgresql_using="gin"
    )
    op.create_table(
        "memory_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "(department = 'finance' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'FINANCE_ONLY') OR "
            "(department = 'legal' AND visibility = 'DEPARTMENT_PRIVATE' "
            "AND classification = 'LEGAL_ONLY_CONFIDENTIAL') OR "
            "(department = 'shared' AND visibility = 'TENANT_SHARED' "
            "AND classification = 'TENANT_SHARED')",
            name="ck_memory_sources_acl",
        ),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_id", "chunk_id", name="uq_memory_sources_memory_chunk"),
    )
    op.create_index("ix_memory_sources_memory_id", "memory_sources", ["memory_id"])
    op.create_index("ix_memory_sources_chunk_id", "memory_sources", ["chunk_id"])


def downgrade() -> None:
    op.drop_table("memory_sources")
    op.drop_table("memories")
