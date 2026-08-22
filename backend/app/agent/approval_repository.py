from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.approval_security import APPROVAL_LIFETIME
from app.agent.models import Plan
from app.models.agent_runs import (
    AgentApprovalRequest,
    AgentPlanVersion,
    AgentRun,
    ApprovalRiskClass,
    ApprovalStatus,
)


async def create_pending_approval(
    session: AsyncSession,
    *,
    run: AgentRun,
    plans: tuple[Plan, ...],
    plan_version: int,
    proposed_step_number: int,
    tool_name: str,
    action_hash: str,
    scope_fingerprint: str,
    risk_class: ApprovalRiskClass,
    now: datetime | None = None,
) -> AgentApprovalRequest:
    created = now or datetime.now(UTC)
    existing_plans = set(
        (
            await session.scalars(
                select(AgentPlanVersion.version).where(AgentPlanVersion.run_id == run.id)
            )
        ).all()
    )
    for plan in plans:
        if plan.version not in existing_plans:
            session.add(
                AgentPlanVersion(
                    run_id=run.id,
                    version=plan.version,
                    change_reason_code=plan.change_reason_code,
                    planned_step_count=len(plan.steps),
                )
            )
    approval = AgentApprovalRequest(
        id=uuid4(),
        run_id=run.id,
        plan_version=plan_version,
        proposed_step_number=proposed_step_number,
        action_name=tool_name,
        tool_name=tool_name,
        action_argument_hash=action_hash,
        authorization_scope_fingerprint=scope_fingerprint,
        approval_risk_class=risk_class.value,
        safe_reason_code="USER_APPROVAL_REQUIRED",
        status=ApprovalStatus.PENDING.value,
        expires_at=created + APPROVAL_LIFETIME,
    )
    session.add(approval)
    await session.flush()
    run.plan_version_count = max(run.plan_version_count, len(plans))
    return approval
