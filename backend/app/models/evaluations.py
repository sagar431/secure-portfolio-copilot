from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','PASSED','FAILED','SECURITY_FAILED','ERROR')",
            name="ck_evaluation_runs_status",
        ),
        CheckConstraint("char_length(manifest_hash) = 64", name="ck_evaluation_runs_hash"),
        CheckConstraint("max_judged_cases BETWEEN 0 AND 2", name="ck_evaluation_runs_judge_limit"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    manifest_version: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)
    advisory_judge_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_judged_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_reason_code: Mapped[str | None] = mapped_column(String(96))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    release_gates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    results: Mapped[list[EvaluationCaseResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="EvaluationCaseResult.case_id"
    )


class EvaluationCaseResult(Base):
    __tablename__ = "evaluation_case_results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", name="uq_evaluation_case_results_run_case"),
        CheckConstraint(
            "status IN ('PASS','FAIL','ERROR')", name="ck_evaluation_case_results_status"
        ),
        CheckConstraint("duration_ms >= 0", name="ck_evaluation_case_results_duration"),
        CheckConstraint("retry_count >= 0", name="ck_evaluation_case_results_retry"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_evaluation_case_input"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_evaluation_case_output"
        ),
        CheckConstraint("cost_usd IS NULL OR cost_usd >= 0", name="ck_evaluation_case_cost"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    manifest_version: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    safe_reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    expected_identifiers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    actual_identifiers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    model_route: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason_code: Mapped[str | None] = mapped_column(String(96))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[EvaluationRun] = relationship(back_populates="results")
