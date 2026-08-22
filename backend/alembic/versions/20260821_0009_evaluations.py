"""Add secure evaluation run persistence.

Revision ID: 20260821_0009
Revises: 20260821_0008
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260821_0009"
down_revision: str | None = "20260821_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_version", sa.String(32), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("advisory_judge_enabled", sa.Boolean(), nullable=False),
        sa.Column("max_judged_cases", sa.Integer(), nullable=False),
        sa.Column("safe_reason_code", sa.String(96), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("release_gates", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','PASSED','FAILED','SECURITY_FAILED','ERROR')",
            name="ck_evaluation_runs_status",
        ),
        sa.CheckConstraint("char_length(manifest_hash) = 64", name="ck_evaluation_runs_hash"),
        sa.CheckConstraint(
            "max_judged_cases BETWEEN 0 AND 2", name="ck_evaluation_runs_judge_limit"
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_runs_requested_by_user_id", "evaluation_runs", ["requested_by_user_id"]
    )
    op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"])
    op.create_table(
        "evaluation_case_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(16), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("manifest_version", sa.String(32), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("safe_reason_code", sa.String(96), nullable=False),
        sa.Column("expected_identifiers", sa.JSON(), nullable=False),
        sa.Column("actual_identifiers", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("model_route", sa.String(64), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("fallback_reason_code", sa.String(96), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PASS','FAIL','ERROR')", name="ck_evaluation_case_results_status"
        ),
        sa.CheckConstraint("duration_ms >= 0", name="ck_evaluation_case_results_duration"),
        sa.CheckConstraint("retry_count >= 0", name="ck_evaluation_case_results_retry"),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_evaluation_case_input"
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_evaluation_case_output"
        ),
        sa.CheckConstraint("cost_usd IS NULL OR cost_usd >= 0", name="ck_evaluation_case_cost"),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "case_id", name="uq_evaluation_case_results_run_case"),
    )
    op.create_index("ix_evaluation_case_results_run_id", "evaluation_case_results", ["run_id"])
    op.create_index("ix_evaluation_case_results_category", "evaluation_case_results", ["category"])
    op.create_index("ix_evaluation_case_results_status", "evaluation_case_results", ["status"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_case_results_status", table_name="evaluation_case_results")
    op.drop_index("ix_evaluation_case_results_category", table_name="evaluation_case_results")
    op.drop_index("ix_evaluation_case_results_run_id", table_name="evaluation_case_results")
    op.drop_table("evaluation_case_results")
    op.drop_index("ix_evaluation_runs_status", table_name="evaluation_runs")
    op.drop_index("ix_evaluation_runs_requested_by_user_id", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
