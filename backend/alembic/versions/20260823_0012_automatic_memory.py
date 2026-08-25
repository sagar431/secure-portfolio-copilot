"""Add typed automatic user-isolated memory lifecycle.

Revision ID: 20260823_0012
Revises: 20260822_0011
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260823_0012"
down_revision: str | None = "20260822_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("memory_type", sa.String(32), server_default="SEMANTIC", nullable=False),
    )
    op.add_column(
        "memories",
        sa.Column("origin", sa.String(32), server_default="EXPLICIT_USER", nullable=False),
    )
    op.add_column(
        "memories", sa.Column("status", sa.String(32), server_default="ACTIVE", nullable=False)
    )
    op.add_column("memories", sa.Column("conversation_id", sa.Uuid(), nullable=True))
    op.add_column("memories", sa.Column("agent_run_id", sa.Uuid(), nullable=True))
    op.add_column("memories", sa.Column("source_message_id", sa.Uuid(), nullable=True))
    op.add_column("memories", sa.Column("normalized_key", sa.String(160), nullable=True))
    op.add_column(
        "memories",
        sa.Column("reason", sa.String(240), server_default="User-created memory", nullable=False),
    )
    op.add_column(
        "memories", sa.Column("confidence", sa.Float(), server_default="1", nullable=False)
    )
    op.add_column(
        "memories", sa.Column("importance", sa.Float(), server_default="0.5", nullable=False)
    )
    op.add_column("memories", sa.Column("superseded_by_id", sa.Uuid(), nullable=True))
    op.add_column("memories", sa.Column("last_accessed_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_memories_conversation",
        "memories",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_memories_agent_run",
        "memories",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_memories_source_message",
        "memories",
        "messages",
        ["source_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_memories_superseded_by",
        "memories",
        "memories",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_memories_type",
        "memories",
        "memory_type IN ('SEMANTIC','EPISODIC','CONVERSATION_SUMMARY')",
    )
    op.create_check_constraint(
        "ck_memories_origin",
        "memories",
        "origin IN ('EXPLICIT_USER','AUTOMATIC_EXTRACTOR','SYSTEM_SUMMARY')",
    )
    op.create_check_constraint(
        "ck_memories_status",
        "memories",
        "status IN ('PENDING_CONFIRMATION','ACTIVE','SUPERSEDED','EXPIRED','DELETED')",
    )
    op.create_check_constraint("ck_memories_confidence", "memories", "confidence BETWEEN 0 AND 1")
    op.create_check_constraint("ck_memories_importance", "memories", "importance BETWEEN 0 AND 1")
    op.create_check_constraint(
        "ck_memories_summary_conversation",
        "memories",
        "memory_type <> 'CONVERSATION_SUMMARY' OR conversation_id IS NOT NULL",
    )
    for column in (
        "memory_type",
        "status",
        "conversation_id",
        "agent_run_id",
        "source_message_id",
        "normalized_key",
        "superseded_by_id",
    ):
        op.create_index(f"ix_memories_{column}", "memories", [column])
    op.create_index(
        "ix_memories_authorized_retrieval",
        "memories",
        ["tenant_id", "owner_user_id", "company_id", "memory_type", "status", "expires_at"],
    )

    op.create_table(
        "memory_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "action IN ('CREATE','CONFIRM','DISMISS','SUPERSEDE','REFRESH','DELETE','EXPIRE')",
            name="ck_memory_audit_events_action",
        ),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("memory_id", "tenant_id", "actor_user_id"):
        op.create_index(f"ix_memory_audit_events_{column}", "memory_audit_events", [column])

    # These triggers make copied scope/provenance and ownership relationships fail closed even
    # when a future code path bypasses the service layer.
    op.execute("""
        CREATE FUNCTION validate_memory_scope_links() RETURNS trigger AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM companies c
            WHERE c.id = NEW.company_id AND c.tenant_id = NEW.tenant_id
          ) THEN
            RAISE EXCEPTION 'memory company must belong to tenant';
          END IF;
          IF NEW.conversation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM conversations c WHERE c.id = NEW.conversation_id
              AND c.tenant_id = NEW.tenant_id AND c.user_id = NEW.owner_user_id
          ) THEN RAISE EXCEPTION 'memory conversation scope mismatch'; END IF;
          IF NEW.source_message_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM messages m WHERE m.id = NEW.source_message_id
              AND m.tenant_id = NEW.tenant_id AND m.user_id = NEW.owner_user_id
              AND (NEW.conversation_id IS NULL OR m.conversation_id = NEW.conversation_id)
          ) THEN RAISE EXCEPTION 'memory source message scope mismatch'; END IF;
          IF NEW.agent_run_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM agent_runs r WHERE r.id = NEW.agent_run_id
              AND r.tenant_id = NEW.tenant_id AND r.user_id = NEW.owner_user_id
              AND (NEW.conversation_id IS NULL OR r.conversation_id = NEW.conversation_id)
          ) THEN RAISE EXCEPTION 'memory agent run scope mismatch'; END IF;
          IF NEW.superseded_by_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM memories m WHERE m.id = NEW.superseded_by_id
              AND m.tenant_id = NEW.tenant_id AND m.company_id = NEW.company_id
              AND m.owner_user_id IS NOT DISTINCT FROM NEW.owner_user_id
              AND m.memory_type = NEW.memory_type
              AND m.normalized_key IS NOT DISTINCT FROM NEW.normalized_key
          ) THEN RAISE EXCEPTION 'superseding memory scope mismatch'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_validate_memory_scope_links BEFORE INSERT OR UPDATE ON memories
          FOR EACH ROW EXECUTE FUNCTION validate_memory_scope_links()
    """)
    op.execute("""
        CREATE FUNCTION validate_memory_source_links() RETURNS trigger AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM memories m JOIN document_chunks c ON c.id = NEW.chunk_id
            WHERE m.id = NEW.memory_id
              AND m.tenant_id = NEW.tenant_id AND m.company_id = NEW.company_id
              AND c.document_id = NEW.document_id
              AND c.document_version_id = NEW.document_version_id
              AND c.tenant_id = NEW.tenant_id AND c.company_id = NEW.company_id
              AND c.department = NEW.department AND c.visibility = NEW.visibility
              AND c.classification = NEW.classification
          ) THEN RAISE EXCEPTION 'memory source provenance mismatch'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_validate_memory_source_links BEFORE INSERT OR UPDATE ON memory_sources
          FOR EACH ROW EXECUTE FUNCTION validate_memory_source_links()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_validate_memory_source_links ON memory_sources")
    op.execute("DROP FUNCTION IF EXISTS validate_memory_source_links")
    op.execute("DROP TRIGGER IF EXISTS trg_validate_memory_scope_links ON memories")
    op.execute("DROP FUNCTION IF EXISTS validate_memory_scope_links")
    op.drop_table("memory_audit_events")
    op.drop_index("ix_memories_authorized_retrieval", table_name="memories")
    for column in reversed(
        (
            "memory_type",
            "status",
            "conversation_id",
            "agent_run_id",
            "source_message_id",
            "normalized_key",
            "superseded_by_id",
        )
    ):
        op.drop_index(f"ix_memories_{column}", table_name="memories")
    for name in (
        "ck_memories_summary_conversation",
        "ck_memories_importance",
        "ck_memories_confidence",
        "ck_memories_status",
        "ck_memories_origin",
        "ck_memories_type",
    ):
        op.drop_constraint(name, "memories", type_="check")
    for name in (
        "fk_memories_superseded_by",
        "fk_memories_source_message",
        "fk_memories_agent_run",
        "fk_memories_conversation",
    ):
        op.drop_constraint(name, "memories", type_="foreignkey")
    for column in (
        "last_accessed_at",
        "superseded_by_id",
        "importance",
        "confidence",
        "reason",
        "normalized_key",
        "source_message_id",
        "agent_run_id",
        "conversation_id",
        "status",
        "origin",
        "memory_type",
    ):
        op.drop_column("memories", column)
