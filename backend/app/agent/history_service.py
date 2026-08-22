from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.history_repository import get_owned_run, list_owned_runs
from app.chat.scope_guard import resolve_home_tenant_id
from app.core.errors import APIError
from app.models.agent_runs import AgentRun, AgentStep
from app.models.identity import Capability
from app.policies.models import AuthorizationContext
from app.schemas.agent_runs import (
    AgentObservationData,
    AgentPlanVersionData,
    AgentRunHistoryDetailData,
    AgentRunHistoryListData,
    AgentRunHistorySummaryData,
    AgentStepData,
    AgentTimelineEventData,
)


def _require_query_documents(context: AuthorizationContext) -> None:
    if not any(Capability.QUERY_DOCUMENTS in grant.capabilities for grant in context.scope.grants):
        raise APIError(403, "forbidden", "Agent history access is not permitted.")


def _encode_cursor(created_at: datetime, run_id: UUID) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "run_id": str(run_id)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime | None, UUID | None]:
    if value is None:
        return None, None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if set(payload) != {"created_at", "run_id"}:
            raise ValueError
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, UUID(payload["run_id"])
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise APIError(400, "invalid_cursor", "Agent history cursor is invalid.") from None


def _summary(run: AgentRun) -> AgentRunHistorySummaryData:
    return AgentRunHistorySummaryData.model_validate(run)


def _step_data(step: AgentStep) -> AgentStepData:
    observation = step.observation
    observation_data = (
        AgentObservationData.model_validate(
            {
                "status": observation.status,
                "safe_reason_code": observation.safe_reason_code,
                "authorized_document_ids": tuple(
                    UUID(item) for item in observation.authorized_document_ids
                ),
                "authorized_chunk_ids": tuple(
                    UUID(item) for item in observation.authorized_chunk_ids
                ),
                "citation_ids": tuple(observation.citation_ids),
                "evidence_count": observation.evidence_count,
                "retry_count": observation.retry_count,
                "duration_ms": observation.duration_ms,
            }
        )
        if observation is not None
        else None
    )
    return AgentStepData.model_validate(
        {
            "step_number": step.step_number,
            "plan_version": step.plan_version,
            "plan_step_index": step.plan_step_index,
            "action_name": step.action_name,
            "tool_name": step.tool_name,
            "status": step.status,
            "policy_decision": step.policy_decision,
            "safe_reason_code": step.safe_reason_code,
            "duration_ms": step.duration_ms,
            "observation": observation_data,
        }
    )


def _timeline(
    run: AgentRun, steps: tuple[AgentStepData, ...]
) -> tuple[AgentTimelineEventData, ...]:
    events: list[AgentTimelineEventData] = []

    def append(
        stage: Literal["perception", "policy", "decision", "tool", "observation", "final"],
        status: str,
        reason: str,
        summary: str,
        *,
        tool_name: str | None = None,
        step_number: int | None = None,
        duration_ms: int = 0,
    ) -> None:
        events.append(
            AgentTimelineEventData(
                sequence=len(events) + 1,
                stage=stage,
                status=status,
                safe_reason_code=reason,
                summary=summary,
                tool_name=tool_name,
                step_number=step_number,
                duration_ms=duration_ms,
            )
        )

    append(
        "perception",
        run.perception_status,
        run.perception_reason_code,
        "The request was classified without retaining query or reasoning content.",
    )
    append(
        "policy",
        run.policy_decision,
        run.policy_reason_code,
        "Server-owned authorization policy was evaluated.",
    )
    if run.plan_versions:
        for plan in run.plan_versions:
            append(
                "decision",
                "RECORDED",
                plan.change_reason_code,
                (
                    f"Immutable plan version {plan.version} recorded "
                    f"{plan.planned_step_count} bounded steps."
                ),
            )
    else:
        append(
            "decision",
            "NOT_RECORDED",
            "NO_PLAN_RECORDED",
            "No safe plan metadata was recorded.",
        )
    if steps:
        for step in steps:
            append(
                "tool",
                step.status,
                step.safe_reason_code,
                "An allow-listed tool action reached a terminal step state.",
                tool_name=step.tool_name,
                step_number=step.step_number,
                duration_ms=step.duration_ms,
            )
            if step.observation is not None:
                append(
                    "observation",
                    step.observation.status,
                    step.observation.safe_reason_code,
                    (
                        "Authorized observation metadata recorded "
                        f"{step.observation.evidence_count} evidence references."
                    ),
                    tool_name=step.tool_name,
                    step_number=step.step_number,
                    duration_ms=step.observation.duration_ms,
                )
            else:
                append(
                    "observation",
                    "NOT_RECORDED",
                    "NO_SAFE_OBSERVATION",
                    "No validated observation metadata was persisted for this step.",
                    tool_name=step.tool_name,
                    step_number=step.step_number,
                )
    else:
        append("tool", "NOT_EXECUTED", "NO_TOOL_STEP", "No tool step was executed.")
        append(
            "observation",
            "NOT_RECORDED",
            "NO_SAFE_OBSERVATION",
            "No validated observation metadata was persisted.",
        )
    append(
        "final",
        run.status,
        run.safe_reason_code,
        "The run reached its recorded lifecycle state.",
        duration_ms=run.duration_ms,
    )
    return tuple(events)


class AgentHistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        context: AuthorizationContext,
        *,
        cursor: str | None,
        limit: int,
    ) -> AgentRunHistoryListData:
        _require_query_documents(context)
        tenant_id = resolve_home_tenant_id(context)
        created_at, run_id = _decode_cursor(cursor)
        records = await list_owned_runs(
            self._session,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
            limit=limit,
            cursor_created_at=created_at,
            cursor_id=run_id,
        )
        visible = records[:limit]
        next_cursor = (
            _encode_cursor(visible[-1].created_at, visible[-1].id)
            if len(records) > limit and visible
            else None
        )
        return AgentRunHistoryListData(
            runs=tuple(_summary(item) for item in visible), next_cursor=next_cursor
        )

    async def get(
        self, context: AuthorizationContext, *, run_id: UUID
    ) -> AgentRunHistoryDetailData:
        _require_query_documents(context)
        tenant_id = resolve_home_tenant_id(context)
        run = await get_owned_run(
            self._session,
            run_id=run_id,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
        )
        if run is None:
            raise APIError(404, "not_found", "Agent run was not found.")
        steps = tuple(_step_data(item) for item in run.steps)
        return AgentRunHistoryDetailData(
            **_summary(run).model_dump(),
            final_assistant_message_id=run.final_assistant_message_id,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            perception_status=cast(
                Literal["NOT_STARTED", "COMPLETED", "FAILED"], run.perception_status
            ),
            perception_reason_code=run.perception_reason_code,
            policy_decision=cast(
                Literal["NOT_EVALUATED", "ALLOWED", "DENIED"], run.policy_decision
            ),
            policy_reason_code=run.policy_reason_code,
            plan_versions=tuple(
                AgentPlanVersionData.model_validate(item) for item in run.plan_versions
            ),
            steps=steps,
            timeline=_timeline(run, steps),
        )
