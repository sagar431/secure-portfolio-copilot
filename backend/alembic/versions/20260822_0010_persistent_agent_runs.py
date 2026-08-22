"""Add safe persistent agent run history.

Revision ID: 20260822_0010
Revises: 20260821_0009
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0010"
down_revision: str | None = "20260821_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("response_mode", sa.String(16), nullable=False),
        sa.Column("selected_model_tier", sa.String(16), nullable=True),
        sa.Column("selected_model_name", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("safe_reason_code", sa.String(96), nullable=False),
        sa.Column("perception_status", sa.String(24), nullable=False),
        sa.Column("perception_reason_code", sa.String(96), nullable=False),
        sa.Column("policy_decision", sa.String(24), nullable=False),
        sa.Column("policy_reason_code", sa.String(96), nullable=False),
        sa.Column("plan_version_count", sa.Integer(), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("final_assistant_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('CREATED','RUNNING','AWAITING_APPROVAL','COMPLETED','REFUSED',"
            "'CLARIFICATION_REQUIRED','INSUFFICIENT_EVIDENCE','LIMIT_REACHED','FAILED',"
            "'CANCELLED')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint("response_mode IN ('fast','auto','deep')", name="ck_agent_runs_mode"),
        sa.CheckConstraint(
            "selected_model_tier IS NULL OR selected_model_tier IN ('fast','deep')",
            name="ck_agent_runs_model_tier",
        ),
        sa.CheckConstraint(
            "policy_decision IN ('NOT_EVALUATED','ALLOWED','DENIED')",
            name="ck_agent_runs_policy_decision",
        ),
        sa.CheckConstraint(
            "perception_status IN ('NOT_STARTED','COMPLETED','FAILED')",
            name="ck_agent_runs_perception_status",
        ),
        sa.CheckConstraint("plan_version_count BETWEEN 0 AND 2", name="ck_agent_runs_plan_count"),
        sa.CheckConstraint("step_count BETWEEN 0 AND 4", name="ck_agent_runs_step_count"),
        sa.CheckConstraint(
            "observation_count BETWEEN 0 AND 4", name="ck_agent_runs_observation_count"
        ),
        sa.CheckConstraint("retry_count BETWEEN 0 AND 4", name="ck_agent_runs_retry_count"),
        sa.CheckConstraint(
            "duration_ms >= 0 AND duration_ms <= 120000", name="ck_agent_runs_duration"
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens BETWEEN 0 AND 1000000",
            name="ck_agent_runs_input_tokens",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens BETWEEN 0 AND 1000000",
            name="ck_agent_runs_output_tokens",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["final_assistant_message_id"], ["messages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("final_assistant_message_id"),
    )
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index(
        "ix_agent_runs_owner_created",
        "agent_runs",
        ["tenant_id", "user_id", "created_at", "id"],
    )

    op.create_table(
        "agent_plan_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("change_reason_code", sa.String(96), nullable=False),
        sa.Column("planned_step_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version BETWEEN 1 AND 2", name="ck_agent_plan_versions_version"),
        sa.CheckConstraint(
            "planned_step_count BETWEEN 1 AND 3", name="ck_agent_plan_versions_step_count"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "version", name="uq_agent_plan_versions_run_version"),
    )
    op.create_index("ix_agent_plan_versions_run_id", "agent_plan_versions", ["run_id"])
    op.execute(
        """
        CREATE FUNCTION prevent_agent_plan_version_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'agent plan versions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_plan_versions_immutable
        BEFORE UPDATE ON agent_plan_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_agent_plan_version_update()
        """
    )

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version_id", sa.Uuid(), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("plan_step_index", sa.Integer(), nullable=False),
        sa.Column("action_name", sa.String(32), nullable=False),
        sa.Column("tool_name", sa.String(96), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("policy_decision", sa.String(16), nullable=False),
        sa.Column("safe_reason_code", sa.String(96), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("step_number BETWEEN 1 AND 4", name="ck_agent_steps_number"),
        sa.CheckConstraint("plan_version BETWEEN 1 AND 2", name="ck_agent_steps_plan_version"),
        sa.CheckConstraint("plan_step_index BETWEEN 0 AND 2", name="ck_agent_steps_plan_index"),
        sa.CheckConstraint("action_name = 'TOOL_CALL'", name="ck_agent_steps_action"),
        sa.CheckConstraint(
            "tool_name IN ('portfolio.search_authorized_documents',"
            "'portfolio.get_document_excerpt','portfolio.calculate_ebitda_margin',"
            "'portfolio.calculate_revenue_growth','portfolio.calculate_net_profit_margin')",
            name="ck_agent_steps_tool",
        ),
        sa.CheckConstraint(
            "status IN ('COMPLETED','DENIED','TIMEOUT','FAILED')",
            name="ck_agent_steps_status",
        ),
        sa.CheckConstraint("policy_decision IN ('ALLOWED','DENIED')", name="ck_agent_steps_policy"),
        sa.CheckConstraint(
            "duration_ms >= 0 AND duration_ms <= 120000", name="ck_agent_steps_duration"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["plan_version_id"], ["agent_plan_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "step_number", name="uq_agent_steps_run_step"),
        sa.UniqueConstraint(
            "run_id", "plan_version", "plan_step_index", name="uq_agent_steps_plan_position"
        ),
    )
    op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])

    op.create_table(
        "agent_observation_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("safe_reason_code", sa.String(96), nullable=False),
        sa.Column("authorized_document_ids", sa.JSON(), nullable=False),
        sa.Column("authorized_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("citation_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('SUCCESS','DENIED','TIMEOUT','ERROR')",
            name="ck_agent_observations_status",
        ),
        sa.CheckConstraint(
            "evidence_count BETWEEN 0 AND 8", name="ck_agent_observations_evidence_count"
        ),
        sa.CheckConstraint("retry_count BETWEEN 0 AND 1", name="ck_agent_observations_retry"),
        sa.CheckConstraint(
            "duration_ms >= 0 AND duration_ms <= 120000",
            name="ck_agent_observations_duration",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["agent_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("step_id"),
        sa.UniqueConstraint("run_id", "step_number", name="uq_agent_observations_run_step"),
    )
    op.create_index("ix_agent_observation_records_run_id", "agent_observation_records", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_observation_records_run_id", table_name="agent_observation_records")
    op.drop_table("agent_observation_records")
    op.drop_index("ix_agent_steps_run_id", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.execute("DROP TRIGGER trg_agent_plan_versions_immutable ON agent_plan_versions")
    op.execute("DROP FUNCTION prevent_agent_plan_version_update()")
    op.drop_index("ix_agent_plan_versions_run_id", table_name="agent_plan_versions")
    op.drop_table("agent_plan_versions")
    op.drop_index("ix_agent_runs_owner_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_tenant_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_table("agent_runs")
