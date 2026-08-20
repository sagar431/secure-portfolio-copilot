"""Add approved-version embedding lifecycle and pgvector index.

Revision ID: 20260821_0005
Revises: 20260821_0004
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa

from alembic import op

revision: str = "20260821_0005"
down_revision: str | None = "20260821_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=768), nullable=True),
    )
    op.add_column(
        "document_chunks", sa.Column("embedding_model_name", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedding_model_version", sa.String(length=64), nullable=True),
    )
    op.add_column("document_chunks", sa.Column("embedding_dimensions", sa.Integer(), nullable=True))
    op.add_column(
        "document_chunks", sa.Column("embedding_chunk_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "embedding_status",
            sa.String(length=16),
            server_default="PENDING",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_document_chunks_embedding_status",
        "document_chunks",
        "embedding_status IN ('PENDING', 'READY', 'FAILED', 'STALE')",
    )
    op.create_check_constraint(
        "ck_document_chunks_embedding_ready",
        "document_chunks",
        "(embedding_status = 'READY' AND embedding IS NOT NULL "
        "AND embedding_model_name IS NOT NULL AND embedding_model_version IS NOT NULL "
        "AND embedding_dimensions = 768 AND embedding_chunk_hash = content_hash) OR "
        "(embedding_status <> 'READY' AND embedding IS NULL)",
    )
    op.create_index("ix_document_chunks_embedding_status", "document_chunks", ["embedding_status"])
    op.create_index(
        "ix_document_chunks_embedding_cosine",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_embedding_cosine", table_name="document_chunks")
    op.drop_index("ix_document_chunks_embedding_status", table_name="document_chunks")
    op.drop_constraint("ck_document_chunks_embedding_ready", "document_chunks", type_="check")
    op.drop_constraint("ck_document_chunks_embedding_status", "document_chunks", type_="check")
    op.drop_column("document_chunks", "embedding_status")
    op.drop_column("document_chunks", "embedding_chunk_hash")
    op.drop_column("document_chunks", "embedding_dimensions")
    op.drop_column("document_chunks", "embedding_model_version")
    op.drop_column("document_chunks", "embedding_model_name")
    op.drop_column("document_chunks", "embedding")
