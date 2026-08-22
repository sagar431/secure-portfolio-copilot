from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.evaluations.contracts import (
    EvaluationCaseStatus,
    EvaluationCategory,
    EvaluationRunDetail,
    EvaluationRunList,
    EvaluationRunStatus,
    EvaluationRunSummary,
    ReleaseGate,
    SafeCaseResult,
)
from app.models.evaluations import EvaluationCaseResult, EvaluationRun

EVALUATION_LOCK_KEY = 4_205_042


class EvaluationAlreadyRunningError(RuntimeError):
    pass


async def create_run_guarded(
    session: AsyncSession,
    *,
    requested_by_user_id: UUID,
    manifest_version: str,
    manifest_hash: str,
    advisory_judge_enabled: bool,
    max_judged_cases: int,
) -> EvaluationRun:
    # Serialize the check/create transaction across processes. The durable RUNNING
    # row then guards the remainder of execution after this transaction commits.
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": EVALUATION_LOCK_KEY})
    active = (
        await session.execute(
            select(EvaluationRun.id).where(
                EvaluationRun.status.in_((EvaluationRunStatus.PENDING, EvaluationRunStatus.RUNNING))
            )
        )
    ).scalar_one_or_none()
    if active is not None:
        raise EvaluationAlreadyRunningError
    now = datetime.now(UTC)
    run = EvaluationRun(
        requested_by_user_id=requested_by_user_id,
        manifest_version=manifest_version,
        manifest_hash=manifest_hash,
        status=EvaluationRunStatus.RUNNING,
        advisory_judge_enabled=advisory_judge_enabled,
        max_judged_cases=max_judged_cases,
        started_at=now,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def persist_case_result(
    session: AsyncSession,
    *,
    run: EvaluationRun,
    result: SafeCaseResult,
) -> None:
    session.add(
        EvaluationCaseResult(
            run_id=run.id,
            case_id=result.case_id,
            category=result.category,
            manifest_version=run.manifest_version,
            manifest_hash=run.manifest_hash,
            status=result.status,
            safe_reason_code=result.reason_code,
            expected_identifiers=list(result.expected_identifiers),
            actual_identifiers=list(result.actual_identifiers),
            metrics=result.metrics,
            duration_ms=result.duration_ms,
            model_route=result.model_route,
            model_name=result.model_name,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
            retry_count=result.retry_count,
            fallback_used=result.fallback_used,
            fallback_reason_code=result.fallback_reason_code,
            started_at=result.started_at,
            completed_at=result.completed_at,
        )
    )
    await session.commit()


async def finish_run(
    session: AsyncSession,
    *,
    run: EvaluationRun,
    status: EvaluationRunStatus,
    safe_reason_code: str,
    metrics: dict[str, object],
    gates: list[dict[str, object]],
) -> None:
    run.status = status
    run.safe_reason_code = safe_reason_code
    run.metrics = metrics
    run.release_gates = gates
    run.completed_at = datetime.now(UTC)
    await session.commit()


async def mark_run_error(session: AsyncSession, run: EvaluationRun, reason_code: str) -> None:
    run.status = EvaluationRunStatus.ERROR
    run.safe_reason_code = reason_code
    run.completed_at = datetime.now(UTC)
    await session.commit()


def _summary(row: EvaluationRun) -> EvaluationRunSummary:
    metrics = None
    if row.metrics is not None:
        from app.evaluations.contracts import EvaluationMetrics

        metrics = EvaluationMetrics.model_validate(row.metrics)
    return EvaluationRunSummary(
        id=row.id,
        status=EvaluationRunStatus(row.status),
        manifest_version=row.manifest_version,
        manifest_hash=row.manifest_hash,
        advisory_judge_enabled=row.advisory_judge_enabled,
        metrics=metrics,
        release_gates=tuple(ReleaseGate.model_validate(item) for item in row.release_gates),
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
    )


def _case(row: EvaluationCaseResult) -> SafeCaseResult:
    return SafeCaseResult(
        case_id=row.case_id,
        category=EvaluationCategory(row.category),
        status=EvaluationCaseStatus(row.status),
        reason_code=row.safe_reason_code,
        expected_identifiers=tuple(row.expected_identifiers),
        actual_identifiers=tuple(row.actual_identifiers),
        metrics=row.metrics,
        duration_ms=row.duration_ms,
        model_route=row.model_route,
        model_name=row.model_name,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
        retry_count=row.retry_count,
        fallback_used=row.fallback_used,
        fallback_reason_code=row.fallback_reason_code,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


async def list_runs(session: AsyncSession, *, limit: int = 50) -> EvaluationRunList:
    rows = (
        (
            await session.execute(
                select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return EvaluationRunList(runs=tuple(_summary(row) for row in rows))


async def get_run(session: AsyncSession, run_id: UUID) -> EvaluationRunDetail | None:
    row = (
        await session.execute(
            select(EvaluationRun)
            .where(EvaluationRun.id == run_id)
            .options(selectinload(EvaluationRun.results))
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    summary = _summary(row)
    return EvaluationRunDetail(
        **summary.model_dump(), results=tuple(_case(item) for item in row.results)
    )
