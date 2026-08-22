"""Add persistent agent approval controls.

Revision ID: 20260822_0011
Revises: 20260822_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0011"
down_revision: str | None = "20260822_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "agent_control_mode",
            sa.String(16),
            server_default="balanced",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_agent_runs_control_mode",
        "agent_runs",
        "agent_control_mode IN ('guided','balanced','autonomous')",
    )
    op.alter_column("agent_runs", "agent_control_mode", server_default=None)
    op.add_column("agent_runs", sa.Column("initial_user_message_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_agent_runs_initial_user_message",
        "agent_runs",
        "messages",
        ["initial_user_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_agent_runs_initial_user_message", "agent_runs", ["initial_user_message_id"]
    )
    op.add_column(
        "agent_steps",
        sa.Column(
            "action_argument_hash",
            sa.String(64),
            server_default="0000000000000000000000000000000000000000000000000000000000000000",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_agent_steps_action_hash",
        "agent_steps",
        "length(action_argument_hash) = 64",
    )
    op.alter_column("agent_steps", "action_argument_hash", server_default=None)

    op.create_table(
        "agent_approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("proposed_step_number", sa.Integer(), nullable=False),
        sa.Column("action_name", sa.String(96), nullable=False),
        sa.Column("tool_name", sa.String(96), nullable=False),
        sa.Column("action_argument_hash", sa.String(64), nullable=False),
        sa.Column("authorization_scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("approval_risk_class", sa.String(32), nullable=False),
        sa.Column("safe_reason_code", sa.String(96), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolver_user_id", sa.Uuid(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("plan_version BETWEEN 1 AND 2", name="ck_agent_approvals_plan_version"),
        sa.CheckConstraint("proposed_step_number BETWEEN 1 AND 4", name="ck_agent_approvals_step"),
        sa.CheckConstraint(
            "approval_risk_class IN ('LOW_READ_ONLY','SENSITIVE','EXPENSIVE','STATE_CHANGING',"
            "'BUDGET_EXPANDING','ALWAYS_REQUIRE_APPROVAL')",
            name="ck_agent_approvals_risk",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','SUPERSEDED','EXPIRED',"
            "'CANCELLED','CONSUMED')",
            name="ck_agent_approvals_status",
        ),
        sa.CheckConstraint(
            "length(action_argument_hash) = 64", name="ck_agent_approvals_action_hash"
        ),
        sa.CheckConstraint(
            "length(authorization_scope_fingerprint) = 64",
            name="ck_agent_approvals_scope_hash",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolver_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_approval_requests_run_id", "agent_approval_requests", ["run_id"])
    op.create_index(
        "uq_agent_approvals_one_pending_per_run",
        "agent_approval_requests",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_approvals_one_pending_per_run", table_name="agent_approval_requests")
    op.drop_index("ix_agent_approval_requests_run_id", table_name="agent_approval_requests")
    op.drop_table("agent_approval_requests")
    op.drop_constraint("ck_agent_steps_action_hash", "agent_steps", type_="check")
    op.drop_column("agent_steps", "action_argument_hash")
    op.drop_constraint("uq_agent_runs_initial_user_message", "agent_runs", type_="unique")
    op.drop_constraint("fk_agent_runs_initial_user_message", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "initial_user_message_id")
    op.drop_constraint("ck_agent_runs_control_mode", "agent_runs", type_="check")
    op.drop_column("agent_runs", "agent_control_mode")
