"""Persist the safe selected request intent in chat traces.

Revision ID: 20260823_0013
Revises: 20260823_0012
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260823_0013"
down_revision: str | None = "20260823_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_request_traces",
        sa.Column(
            "intent_route",
            sa.String(32),
            server_default="DOCUMENT_QUESTION",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_chat_request_traces_intent_route",
        "chat_request_traces",
        "intent_route IN ('CASUAL','DOCUMENT_QUESTION','CONVERSATION_FOLLOW_UP',"
        "'MEMORY_RECALL','MEMORY_WRITE','CALCULATION','CLARIFICATION','REFUSE','AGENT')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_chat_request_traces_intent_route", "chat_request_traces", type_="check")
    op.drop_column("chat_request_traces", "intent_route")
