from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AgentRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    LIMIT_REACHED = "LIMIT_REACHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentControlMode(StrEnum):
    GUIDED = "guided"
    BALANCED = "balanced"
    AUTONOMOUS = "autonomous"


class ApprovalRiskClass(StrEnum):
    LOW_READ_ONLY = "LOW_READ_ONLY"
    SENSITIVE = "SENSITIVE"
    EXPENSIVE = "EXPENSIVE"
    STATE_CHANGING = "STATE_CHANGING"
    BUDGET_EXPANDING = "BUDGET_EXPANDING"
    ALWAYS_REQUIRE_APPROVAL = "ALWAYS_REQUIRE_APPROVAL"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    CONSUMED = "CONSUMED"


class AgentRun(Base):
    """Safe run metadata only; user/model content and authorization objects are forbidden."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED','RUNNING','AWAITING_APPROVAL','COMPLETED','REFUSED',"
            "'CLARIFICATION_REQUIRED','INSUFFICIENT_EVIDENCE','LIMIT_REACHED','FAILED',"
            "'CANCELLED')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint("response_mode IN ('fast','auto','deep')", name="ck_agent_runs_mode"),
        CheckConstraint(
            "agent_control_mode IN ('guided','balanced','autonomous')",
            name="ck_agent_runs_control_mode",
        ),
        CheckConstraint(
            "selected_model_tier IS NULL OR selected_model_tier IN ('fast','deep')",
            name="ck_agent_runs_model_tier",
        ),
        CheckConstraint(
            "policy_decision IN ('NOT_EVALUATED','ALLOWED','DENIED')",
            name="ck_agent_runs_policy_decision",
        ),
        CheckConstraint(
            "perception_status IN ('NOT_STARTED','COMPLETED','FAILED')",
            name="ck_agent_runs_perception_status",
        ),
        CheckConstraint("plan_version_count BETWEEN 0 AND 2", name="ck_agent_runs_plan_count"),
        CheckConstraint("step_count BETWEEN 0 AND 4", name="ck_agent_runs_step_count"),
        CheckConstraint(
            "observation_count BETWEEN 0 AND 4", name="ck_agent_runs_observation_count"
        ),
        CheckConstraint("retry_count BETWEEN 0 AND 4", name="ck_agent_runs_retry_count"),
        CheckConstraint(
            "duration_ms >= 0 AND duration_ms <= 120000", name="ck_agent_runs_duration"
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens BETWEEN 0 AND 1000000",
            name="ck_agent_runs_input_tokens",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens BETWEEN 0 AND 1000000",
            name="ck_agent_runs_output_tokens",
        ),
        Index(
            "ix_agent_runs_owner_created",
            "tenant_id",
            "user_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    response_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    agent_control_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AgentControlMode.BALANCED.value
    )
    selected_model_tier: Mapped[str | None] = mapped_column(String(16))
    selected_model_name: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    perception_status: Mapped[str] = mapped_column(
        String(24), default="NOT_STARTED", nullable=False
    )
    perception_reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    policy_decision: Mapped[str] = mapped_column(
        String(24), default="NOT_EVALUATED", nullable=False
    )
    policy_reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    plan_version_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    final_assistant_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), unique=True
    )
    initial_user_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan_versions: Mapped[list[AgentPlanVersion]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentPlanVersion.version"
    )
    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentStep.step_number"
    )
    observations: Mapped[list[AgentObservationRecord]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentObservationRecord.step_number",
    )
    approval_requests: Mapped[list[AgentApprovalRequest]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentApprovalRequest.created_at",
    )


class AgentPlanVersion(Base):
    __tablename__ = "agent_plan_versions"
    __table_args__ = (
        UniqueConstraint("run_id", "version", name="uq_agent_plan_versions_run_version"),
        CheckConstraint("version BETWEEN 1 AND 2", name="ck_agent_plan_versions_version"),
        CheckConstraint(
            "planned_step_count BETWEEN 1 AND 3", name="ck_agent_plan_versions_step_count"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    planned_step_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[AgentRun] = relationship(back_populates="plan_versions")


@event.listens_for(AgentPlanVersion, "before_update", propagate=True)
def _prevent_plan_version_update(*_: object) -> None:
    raise ValueError("Agent plan versions are immutable")


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "step_number", name="uq_agent_steps_run_step"),
        UniqueConstraint(
            "run_id",
            "plan_version",
            "plan_step_index",
            name="uq_agent_steps_plan_position",
        ),
        CheckConstraint("step_number BETWEEN 1 AND 4", name="ck_agent_steps_number"),
        CheckConstraint("plan_version BETWEEN 1 AND 2", name="ck_agent_steps_plan_version"),
        CheckConstraint("plan_step_index BETWEEN 0 AND 2", name="ck_agent_steps_plan_index"),
        CheckConstraint("action_name = 'TOOL_CALL'", name="ck_agent_steps_action"),
        CheckConstraint("length(action_argument_hash) = 64", name="ck_agent_steps_action_hash"),
        CheckConstraint(
            "tool_name IN ('portfolio.search_authorized_documents',"
            "'portfolio.get_document_excerpt','portfolio.calculate_ebitda_margin',"
            "'portfolio.calculate_revenue_growth','portfolio.calculate_net_profit_margin',"
            "'portfolio.query_financial_metrics','portfolio.calculate_debt_to_equity',"
            "'portfolio.calculate_cash_runway','portfolio.calculate_cagr',"
            "'portfolio.search_memory','portfolio.propose_memory')",
            name="ck_agent_steps_tool",
        ),
        CheckConstraint(
            "status IN ('COMPLETED','DENIED','TIMEOUT','FAILED')",
            name="ck_agent_steps_status",
        ),
        CheckConstraint("policy_decision IN ('ALLOWED','DENIED')", name="ck_agent_steps_policy"),
        CheckConstraint(
            "duration_ms >= 0 AND duration_ms <= 120000", name="ck_agent_steps_duration"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_plan_versions.id", ondelete="CASCADE"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    action_name: Mapped[str] = mapped_column(String(32), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(96), nullable=False)
    action_argument_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    policy_decision: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[AgentRun] = relationship(back_populates="steps")
    plan_version_record: Mapped[AgentPlanVersion] = relationship()
    observation: Mapped[AgentObservationRecord | None] = relationship(
        back_populates="step", cascade="all, delete-orphan", uselist=False
    )


class AgentObservationRecord(Base):
    __tablename__ = "agent_observation_records"
    __table_args__ = (
        UniqueConstraint("run_id", "step_number", name="uq_agent_observations_run_step"),
        CheckConstraint(
            "status IN ('SUCCESS','DENIED','TIMEOUT','ERROR')",
            name="ck_agent_observations_status",
        ),
        CheckConstraint(
            "evidence_count BETWEEN 0 AND 8", name="ck_agent_observations_evidence_count"
        ),
        CheckConstraint("retry_count BETWEEN 0 AND 1", name="ck_agent_observations_retry"),
        CheckConstraint(
            "duration_ms >= 0 AND duration_ms <= 120000",
            name="ck_agent_observations_duration",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_steps.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    authorized_document_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    authorized_chunk_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    citation_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[AgentRun] = relationship(back_populates="observations")
    step: Mapped[AgentStep] = relationship(back_populates="observation")


class AgentApprovalRequest(Base):
    """Content-free, single-use approval binding owned by the host."""

    __tablename__ = "agent_approval_requests"
    __table_args__ = (
        CheckConstraint("plan_version BETWEEN 1 AND 2", name="ck_agent_approvals_plan_version"),
        CheckConstraint("proposed_step_number BETWEEN 1 AND 4", name="ck_agent_approvals_step"),
        CheckConstraint(
            "approval_risk_class IN ('LOW_READ_ONLY','SENSITIVE','EXPENSIVE','STATE_CHANGING',"
            "'BUDGET_EXPANDING','ALWAYS_REQUIRE_APPROVAL')",
            name="ck_agent_approvals_risk",
        ),
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','SUPERSEDED','EXPIRED',"
            "'CANCELLED','CONSUMED')",
            name="ck_agent_approvals_status",
        ),
        CheckConstraint("length(action_argument_hash) = 64", name="ck_agent_approvals_action_hash"),
        CheckConstraint(
            "length(authorization_scope_fingerprint) = 64",
            name="ck_agent_approvals_scope_hash",
        ),
        Index(
            "uq_agent_approvals_one_pending_per_run",
            "run_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposed_step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action_name: Mapped[str] = mapped_column(String(96), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(96), nullable=False)
    action_argument_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_scope_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_risk_class: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ApprovalStatus.PENDING.value
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolver_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[AgentRun] = relationship(back_populates="approval_requests")
