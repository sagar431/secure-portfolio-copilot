"""Add sanitized deterministic model-routing metadata.

Revision ID: 20260821_0007
Revises: 20260821_0006
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_0007"
down_revision: str | None = "20260821_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_request_traces",
        sa.Column(
            "route_reason_code",
            sa.String(length=64),
            server_default="NO_MODEL_CALL",
            nullable=False,
        ),
    )
    op.add_column(
        "chat_request_traces",
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "chat_request_traces",
        sa.Column("fallback_reason_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_request_traces", "fallback_reason_code")
    op.drop_column("chat_request_traces", "fallback_used")
    op.drop_column("chat_request_traces", "route_reason_code")
