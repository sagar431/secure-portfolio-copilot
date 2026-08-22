from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.models import (
    AgentRunOutcome,
    Plan,
    SafeObservationSnapshot,
    SafeStepSnapshot,
    StoppingReason,
    TerminalStatus,
)
from app.agent.run_state import validate_agent_run_transition
from app.mcp_gateway.contracts import APPROVED_TOOL_NAMES
from app.models.agent_runs import (
    AgentObservationRecord,
    AgentPlanVersion,
    AgentRun,
    AgentRunStatus,
    AgentStep,
)
from app.models.documents import DocumentChunk
from app.policies.models import AuthorizationScope
from app.retrieval.repository import authorized_chunks_statement


class AgentHistoryIntegrityError(ValueError):
    """Safe persistence metadata violated an ordering or authorization invariant."""


async def create_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    conversation_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    response_mode: str,
    agent_control_mode: str,
    selected_model_tier: str | None,
    selected_model_name: str | None,
    policy_decision: str,
    policy_reason_code: str,
) -> AgentRun:
    run = AgentRun(
        id=run_id,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        user_id=user_id,
        response_mode=response_mode,
        agent_control_mode=agent_control_mode,
        selected_model_tier=selected_model_tier,
        selected_model_name=selected_model_name,
        status=AgentRunStatus.CREATED.value,
        safe_reason_code="RUN_CREATED",
        perception_status="NOT_STARTED",
        perception_reason_code="PERCEPTION_NOT_STARTED",
        policy_decision=policy_decision,
        policy_reason_code=policy_reason_code,
        plan_version_count=0,
        step_count=0,
        observation_count=0,
        retry_count=0,
        duration_ms=0,
    )
    session.add(run)
    await session.flush()
    return run


def transition_run(
    run: AgentRun,
    target: AgentRunStatus,
    *,
    reason_code: str,
    now: datetime | None = None,
) -> None:
    current = AgentRunStatus(run.status)
    validate_agent_run_transition(current, target)
    changed_at = now or datetime.now(UTC)
    run.status = target.value
    run.safe_reason_code = reason_code
    if target == AgentRunStatus.RUNNING and run.started_at is None:
        run.started_at = changed_at
    if target not in {
        AgentRunStatus.CREATED,
        AgentRunStatus.RUNNING,
        AgentRunStatus.AWAITING_APPROVAL,
    }:
        run.completed_at = changed_at


async def _validate_authorized_observations(
    session: AsyncSession,
    scope: AuthorizationScope,
    outcome: AgentRunOutcome,
) -> None:
    references = tuple(
        (document_id, chunk_id)
        for observation in outcome.safe_observations
        for document_id, chunk_id in zip(
            observation.document_ids, observation.chunk_ids, strict=True
        )
    )
    if not references:
        return
    chunk_ids = tuple(chunk_id for _, chunk_id in references)
    rows = (
        await session.execute(
            authorized_chunks_statement(scope)
            .with_only_columns(DocumentChunk.document_id, DocumentChunk.id)
            .where(DocumentChunk.id.in_(chunk_ids))
        )
    ).all()
    if {tuple(row) for row in rows} != set(references):
        raise AgentHistoryIntegrityError("Observation references failed authorization validation")


async def persist_outcome_history(
    session: AsyncSession,
    *,
    run: AgentRun,
    scope: AuthorizationScope,
    outcome: AgentRunOutcome,
) -> None:
    existing_plan_rows = tuple(
        (
            await session.scalars(
                select(AgentPlanVersion)
                .where(AgentPlanVersion.run_id == run.id)
                .order_by(AgentPlanVersion.version)
            )
        ).all()
    )
    existing_steps = tuple(
        (
            await session.scalars(
                select(AgentStep)
                .where(AgentStep.run_id == run.id)
                .order_by(AgentStep.step_number)
                .options(selectinload(AgentStep.observation))
            )
        ).all()
    )
    versions = tuple(plan.version for plan in outcome.plan_versions)
    if versions != tuple(range(1, len(versions) + 1)):
        raise AgentHistoryIntegrityError("Plan versions must be immutable and contiguous")
    if len(outcome.safe_steps) > 4 or len(outcome.safe_observations) > 4:
        raise AgentHistoryIntegrityError("Run history exceeds bounded persistence limits")
    if len(outcome.safe_observations) > len(outcome.safe_steps):
        raise AgentHistoryIntegrityError("An observation must belong to an ordered step")
    if len(existing_steps) > len(outcome.safe_steps):
        raise AgentHistoryIntegrityError(
            "Unsafe replay: reconstructed history is missing completed steps"
        )
    await _validate_authorized_observations(session, scope, outcome)

    plan_rows: dict[int, AgentPlanVersion] = {item.version: item for item in existing_plan_rows}
    for plan in outcome.plan_versions:
        record = plan_rows.get(plan.version)
        if record is not None:
            if (
                record.change_reason_code != plan.change_reason_code
                or record.planned_step_count != len(plan.steps)
            ):
                raise AgentHistoryIntegrityError("Reconstructed plan metadata changed")
        else:
            record = AgentPlanVersion(
                run_id=run.id,
                version=plan.version,
                change_reason_code=plan.change_reason_code,
                planned_step_count=len(plan.steps),
            )
            session.add(record)
            plan_rows[plan.version] = record
    await session.flush()

    for index, existing in enumerate(existing_steps):
        snapshot = outcome.safe_steps[index]
        if (
            existing.step_number != index + 1
            or existing.plan_version != snapshot.plan_version
            or existing.plan_step_index != snapshot.plan_step_index
            or existing.tool_name != snapshot.tool_name
            or existing.action_argument_hash != snapshot.action_argument_hash
            or existing.status != snapshot.status
            or existing.policy_decision != snapshot.policy_decision
            or existing.safe_reason_code != snapshot.reason_code
        ):
            raise AgentHistoryIntegrityError("Reconstructed completed step metadata changed")
        expected_observation = (
            outcome.safe_observations[index] if index < len(outcome.safe_observations) else None
        )
        if expected_observation is None or existing.observation is None:
            if expected_observation is not None or existing.observation is not None:
                raise AgentHistoryIntegrityError("Reconstructed observation history changed")
            continue
        if (
            existing.observation.status != expected_observation.status
            or existing.observation.safe_reason_code != expected_observation.reason_code
            or existing.observation.authorized_document_ids
            != [str(item) for item in expected_observation.document_ids]
            or existing.observation.authorized_chunk_ids
            != [str(item) for item in expected_observation.chunk_ids]
            or existing.observation.citation_ids != list(expected_observation.citation_ids)
        ):
            raise AgentHistoryIntegrityError("Reconstructed observation metadata changed")

    for step_number, snapshot in enumerate(outcome.safe_steps, start=1):
        if step_number <= len(existing_steps):
            continue
        if snapshot.tool_name not in APPROVED_TOOL_NAMES:
            raise AgentHistoryIntegrityError("Only approved tools may be persisted")
        plan_record = plan_rows.get(snapshot.plan_version)
        if plan_record is None:
            raise AgentHistoryIntegrityError("A step must reference an immutable plan version")
        step = AgentStep(
            run_id=run.id,
            plan_version_id=plan_record.id,
            step_number=step_number,
            plan_version=snapshot.plan_version,
            plan_step_index=snapshot.plan_step_index,
            action_name=snapshot.action_name,
            tool_name=snapshot.tool_name,
            action_argument_hash=snapshot.action_argument_hash,
            status=snapshot.status,
            policy_decision=snapshot.policy_decision,
            safe_reason_code=snapshot.reason_code,
            duration_ms=snapshot.duration_ms,
        )
        session.add(step)
        await session.flush()
        if step_number <= len(outcome.safe_observations):
            observation = outcome.safe_observations[step_number - 1]
            session.add(
                AgentObservationRecord(
                    run_id=run.id,
                    step_id=step.id,
                    step_number=step_number,
                    status=observation.status,
                    safe_reason_code=observation.reason_code,
                    authorized_document_ids=[str(item) for item in observation.document_ids],
                    authorized_chunk_ids=[str(item) for item in observation.chunk_ids],
                    citation_ids=list(observation.citation_ids),
                    evidence_count=len(observation.chunk_ids),
                    retry_count=observation.retry_count,
                    duration_ms=observation.duration_ms,
                )
            )

    run.plan_version_count = len(outcome.plan_versions)
    run.step_count = len(outcome.safe_steps)
    run.observation_count = len(outcome.safe_observations)
    run.retry_count = min(outcome.retry_count, 4)
    run.input_tokens = outcome.input_tokens
    run.output_tokens = outcome.output_tokens


async def persist_checkpoint_history(
    session: AsyncSession,
    *,
    run: AgentRun,
    scope: AuthorizationScope,
    plans: tuple[Plan, ...],
    safe_steps: tuple[SafeStepSnapshot, ...],
    safe_observations: tuple[SafeObservationSnapshot, ...],
) -> None:
    """Append only content-free completed history before a durable pause."""
    await persist_outcome_history(
        session,
        run=run,
        scope=scope,
        outcome=AgentRunOutcome(
            agent_session_id=run.id,
            terminal_status=TerminalStatus.FAILED,
            stopping_reason=StoppingReason.MODEL_ERROR,
            answer="The agent paused safely.",
            step_count=len(safe_steps),
            replan_count=max(0, len(plans) - 1),
            retry_count=sum(item.retry_count for item in safe_observations),
            trace=(),
            plan_versions=plans,
            safe_steps=safe_steps,
            safe_observations=safe_observations,
        ),
    )


async def list_owned_runs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    limit: int,
    cursor_created_at: datetime | None,
    cursor_id: UUID | None,
) -> tuple[AgentRun, ...]:
    filters = [AgentRun.tenant_id == tenant_id, AgentRun.user_id == user_id]
    if cursor_created_at is not None and cursor_id is not None:
        filters.append(
            or_(
                AgentRun.created_at < cursor_created_at,
                and_(AgentRun.created_at == cursor_created_at, AgentRun.id < cursor_id),
            )
        )
    rows = (
        (
            await session.execute(
                select(AgentRun)
                .where(*filters)
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


async def get_owned_run(
    session: AsyncSession, *, run_id: UUID, tenant_id: UUID, user_id: UUID
) -> AgentRun | None:
    return (
        (
            await session.execute(
                select(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.user_id == user_id,
                )
                .options(
                    selectinload(AgentRun.plan_versions),
                    selectinload(AgentRun.steps).selectinload(AgentStep.observation),
                )
            )
        )
        .scalars()
        .one_or_none()
    )
