import asyncio
import json
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agent.history_repository import AgentHistoryIntegrityError, persist_outcome_history
from app.agent.models import (
    ActionType,
    AgentRunOutcome,
    Plan,
    SafeObservationSnapshot,
    SafeStepSnapshot,
    Step,
    StoppingReason,
    TerminalStatus,
    TraceEvent,
    TraceEventType,
    TraceStatus,
)
from app.agent.service import AgentRunService
from app.auth.repository import build_authorization_context, get_user_by_email
from app.model_routing import ResponseMode
from app.models.agent_runs import AgentObservationRecord, AgentPlanVersion, AgentRun, AgentStep
from app.models.chat import Message
from tests.conftest import AuthHarness
from tests.integration.test_authorized_search import _login, _metadata, _upload_and_approve
from tests.integration.test_grounded_chat import _create_conversation


async def _grounded_run(auth_harness: AuthHarness) -> tuple[str, dict[str, Any], dict[str, Any]]:
    nora = await _login(auth_harness.client, "nora@example.com")
    alice = await _login(auth_harness.client, "alice@example.com")
    await _upload_and_approve(
        auth_harness.client,
        nora,
        relative_path="orion/finance/Orion_FY2025_Board_Pack.pdf",
        media_type="application/pdf",
        metadata=_metadata(
            workspace="orion",
            department="finance",
            document_type="FINANCIAL_REPORT",
            reporting_period="FY2025",
        ),
        idempotency_key="agent-history-grounded-0001",
    )
    conversation = await _create_conversation(auth_harness, alice, "Persistent history")
    response = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/agent-runs",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "What drove Margin Compression for Orion?", "response_mode": "deep"},
    )
    assert response.status_code == 200, response.text
    return alice, conversation, cast(dict[str, Any], response.json()["data"])


@pytest.mark.asyncio
async def test_grounded_run_persists_safe_ordered_history_and_serializes_list_detail(
    auth_harness: AuthHarness,
) -> None:
    alice, conversation, created = await _grounded_run(auth_harness)
    run_id = UUID(created["agent_session_id"])

    async with auth_harness.session_factory() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        plans = (
            (
                await session.execute(
                    select(AgentPlanVersion)
                    .where(AgentPlanVersion.run_id == run_id)
                    .order_by(AgentPlanVersion.version)
                )
            )
            .scalars()
            .all()
        )
        steps = (
            (
                await session.execute(
                    select(AgentStep)
                    .where(AgentStep.run_id == run_id)
                    .order_by(AgentStep.step_number)
                )
            )
            .scalars()
            .all()
        )
        observations = (
            (
                await session.execute(
                    select(AgentObservationRecord)
                    .where(AgentObservationRecord.run_id == run_id)
                    .order_by(AgentObservationRecord.step_number)
                )
            )
            .scalars()
            .all()
        )

    assert run.conversation_id == UUID(conversation["id"])
    assert run.status == "COMPLETED"
    assert run.response_mode == "deep"
    assert run.selected_model_tier == "deep"
    assert run.started_at is not None and run.completed_at is not None
    assert [item.version for item in plans] == list(range(1, len(plans) + 1))
    assert [item.step_number for item in steps] == list(range(1, len(steps) + 1))
    assert [item.step_number for item in observations] == list(range(1, len(observations) + 1))
    assert all(item.tool_name.startswith("portfolio.") for item in steps)
    assert all(item.evidence_count == len(item.authorized_chunk_ids) for item in observations)

    list_response = await auth_harness.client.get(
        "/api/agent-runs?limit=1",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert list_response.status_code == 200
    assert list_response.json()["data"]["runs"][0]["id"] == str(run_id)
    detail_response = await auth_harness.client.get(
        f"/api/agent-runs/{run_id}",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()["data"]
    assert [item["stage"] for item in detail["timeline"]] == [
        "perception",
        "policy",
        "decision",
        "tool",
        "observation",
        "final",
    ]
    assert set(detail) == {
        "id",
        "conversation_id",
        "response_mode",
        "selected_model_tier",
        "selected_model_name",
        "status",
        "safe_reason_code",
        "step_count",
        "retry_count",
        "duration_ms",
        "created_at",
        "started_at",
        "completed_at",
        "final_assistant_message_id",
        "input_tokens",
        "output_tokens",
        "perception_status",
        "perception_reason_code",
        "policy_decision",
        "policy_reason_code",
        "plan_versions",
        "steps",
        "timeline",
    }
    persisted_json = json.dumps(
        {
            "run": {
                column.name: getattr(run, column.name) for column in AgentRun.__table__.columns
            },
            "plans": [
                {
                    column.name: getattr(item, column.name)
                    for column in AgentPlanVersion.__table__.columns
                }
                for item in plans
            ],
            "steps": [
                {column.name: getattr(item, column.name) for column in AgentStep.__table__.columns}
                for item in steps
            ],
            "observations": [
                {
                    column.name: getattr(item, column.name)
                    for column in AgentObservationRecord.__table__.columns
                }
                for item in observations
            ],
        },
        default=str,
    ).casefold()
    for forbidden in (
        "margin compression",
        "what drove",
        "raw_prompt",
        "chain-of-thought",
        "authorization_scope",
        "password",
        "document text",
        "memory content",
        "tool arguments",
    ):
        assert forbidden not in persisted_json

    async with auth_harness.session_factory() as session:
        immutable = (
            (
                await session.execute(
                    select(AgentPlanVersion).where(AgentPlanVersion.run_id == run_id)
                )
            )
            .scalars()
            .first()
        )
        assert immutable is not None
        immutable.change_reason_code = "FORGED_REWRITE"
        with pytest.raises(ValueError, match="immutable"):
            await session.flush()
        await session.rollback()

    async with auth_harness.session_factory() as session:
        original_step = (
            (await session.execute(select(AgentStep).where(AgentStep.run_id == run_id)))
            .scalars()
            .first()
        )
        assert original_step is not None
        session.add(
            AgentStep(
                run_id=original_step.run_id,
                plan_version_id=original_step.plan_version_id,
                step_number=original_step.step_number,
                plan_version=original_step.plan_version,
                plan_step_index=original_step.plan_step_index,
                action_name=original_step.action_name,
                tool_name=original_step.tool_name,
                status=original_step.status,
                policy_decision=original_step.policy_decision,
                safe_reason_code=original_step.safe_reason_code,
                duration_ms=original_step.duration_ms,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async with auth_harness.session_factory() as session:
        user = await get_user_by_email(session, "alice@example.com")
        replayed_run = await session.get(AgentRun, run_id)
        assert user is not None and replayed_run is not None
        context = build_authorization_context(user)
        assert context is not None
        replay = AgentRunOutcome(
            agent_session_id=run_id,
            terminal_status=TerminalStatus.COMPLETED,
            stopping_reason=StoppingReason.COMPLETED,
            answer="Safe response.",
            step_count=0,
            replan_count=0,
            retry_count=0,
            trace=(),
        )
        with pytest.raises(AgentHistoryIntegrityError, match="replay"):
            await persist_outcome_history(
                session,
                run=replayed_run,
                scope=context.scope,
                outcome=replay,
            )


@pytest.mark.asyncio
async def test_history_is_owner_tenant_scoped_paginated_and_foreign_is_generic_404(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    leo = await _login(auth_harness.client, "leo@example.com")
    nora = await _login(auth_harness.client, "nora@example.com")
    conversation = await _create_conversation(auth_harness, alice, "History isolation")
    run_ids: list[str] = []
    for _ in range(2):
        response = await auth_harness.client.post(
            f"/api/conversations/{conversation['id']}/agent-runs",
            headers={"Authorization": f"Bearer {alice}"},
            json={"content": "Show me Orion legal contracts.", "response_mode": "deep"},
        )
        assert response.status_code == 200
        run_ids.append(response.json()["data"]["agent_session_id"])

    first_page = await auth_harness.client.get(
        "/api/agent-runs?limit=1&tenant_id=forged&user_id=forged&conversation_id=forged",
        headers={
            "Authorization": f"Bearer {alice}",
            "X-User-ID": str(uuid4()),
            "X-Tenant": str(uuid4()),
            "X-Conversation-ID": str(uuid4()),
            "X-Run-ID": run_ids[0],
        },
    )
    assert first_page.status_code == 200
    first_data = first_page.json()["data"]
    assert len(first_data["runs"]) == 1
    assert first_data["next_cursor"]
    second_page = await auth_harness.client.get(
        "/api/agent-runs",
        params={"limit": 1, "cursor": first_data["next_cursor"]},
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["data"]["runs"]) == 1
    assert {first_data["runs"][0]["id"], second_page.json()["data"]["runs"][0]["id"]} == set(
        run_ids
    )

    foreign = await auth_harness.client.get(
        f"/api/agent-runs/{run_ids[0]}", headers={"Authorization": f"Bearer {leo}"}
    )
    unknown = await auth_harness.client.get(
        f"/api/agent-runs/{uuid4()}", headers={"Authorization": f"Bearer {leo}"}
    )
    assert foreign.status_code == unknown.status_code == 404
    assert (
        foreign.json()["error"]
        == unknown.json()["error"]
        == {
            "code": "not_found",
            "message": "Agent run was not found.",
        }
    )
    leo_list = await auth_harness.client.get(
        "/api/agent-runs", headers={"Authorization": f"Bearer {leo}"}
    )
    assert leo_list.status_code == 200
    assert leo_list.json()["data"]["runs"] == []
    invalid_cursor = await auth_harness.client.get(
        "/api/agent-runs?cursor=not-a-valid-cursor",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["error"]["code"] == "invalid_cursor"
    no_capability = await auth_harness.client.get(
        "/api/agent-runs", headers={"Authorization": f"Bearer {nora}"}
    )
    assert no_capability.status_code == 403
    unauthenticated = await auth_harness.client.get("/api/agent-runs")
    assert unauthenticated.status_code == 401


class _TerminalLoop:
    def __init__(self, status: TerminalStatus, reason: StoppingReason) -> None:
        self.status = status
        self.reason = reason

    async def run(self, **kwargs: object) -> AgentRunOutcome:
        run_id = cast(UUID, kwargs["agent_run_id"])
        return AgentRunOutcome(
            agent_session_id=run_id,
            terminal_status=self.status,
            stopping_reason=self.reason,
            answer="Safe terminal response.",
            step_count=0,
            replan_count=0,
            retry_count=0,
            trace=(
                TraceEvent(
                    event_type=TraceEventType.TERMINAL,
                    status=TraceStatus.TERMINATED,
                    duration_ms=0,
                    reason_code=self.reason.value.upper(),
                ),
            ),
        )


class _EmptyGateway:
    def permitted_catalog(self, *_: object) -> tuple[object, ...]:
        return ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal", "reason", "persisted"),
    [
        (
            TerminalStatus.INSUFFICIENT_EVIDENCE,
            StoppingReason.INSUFFICIENT_AUTHORIZED_EVIDENCE,
            "INSUFFICIENT_EVIDENCE",
        ),
        (TerminalStatus.REFUSED, StoppingReason.REQUEST_REFUSED, "REFUSED"),
        (TerminalStatus.FAILED, StoppingReason.MODEL_ERROR, "FAILED"),
        (TerminalStatus.FAILED, StoppingReason.TOOL_ERROR, "FAILED"),
        (TerminalStatus.LIMIT_REACHED, StoppingReason.MAX_STEPS, "LIMIT_REACHED"),
    ],
)
async def test_terminal_outcomes_are_reliably_persisted(
    auth_harness: AuthHarness,
    terminal: TerminalStatus,
    reason: StoppingReason,
    persisted: str,
) -> None:
    alice_token = await _login(auth_harness.client, "alice@example.com")
    conversation = await _create_conversation(auth_harness, alice_token, f"Terminal {persisted}")
    async with auth_harness.session_factory() as session:
        user = await get_user_by_email(session, "alice@example.com")
        assert user is not None
        context = build_authorization_context(user)
        assert context is not None
        service = AgentRunService(
            session,
            cast(Any, _TerminalLoop(terminal, reason)),
            cast(Any, _EmptyGateway()),
            model_name="fake-agent",
            route_reason_code="AGENTIC_REQUEST",
        )
        result = await service.run(
            context,
            conversation_id=UUID(conversation["id"]),
            question="Summarize Orion revenue.",
            response_mode=ResponseMode.DEEP,
            request_id=f"terminal-{persisted.casefold()}",
        )
        run = await session.get(AgentRun, result.agent_session_id)
        assert run is not None
        assert run.status == persisted
        assert run.completed_at is not None


class _UnauthorizedObservationLoop:
    async def run(self, **kwargs: object) -> AgentRunOutcome:
        run_id = cast(UUID, kwargs["agent_run_id"])
        tool_name = "portfolio.search_authorized_documents"
        return AgentRunOutcome(
            agent_session_id=run_id,
            terminal_status=TerminalStatus.COMPLETED,
            stopping_reason=StoppingReason.COMPLETED,
            answer="Safe terminal response.",
            step_count=1,
            replan_count=0,
            retry_count=0,
            trace=(),
            plan_versions=(
                Plan(
                    version=1,
                    plan_text=("Excluded model plan text.",),
                    steps=(
                        Step(
                            step_index=0,
                            action_type=ActionType.TOOL_CALL,
                            action_name=tool_name,
                            reason_code="SEARCH_AUTHORIZED_EVIDENCE",
                        ),
                    ),
                    change_reason_code="PLAN_CREATED",
                ),
            ),
            safe_steps=(
                SafeStepSnapshot(
                    plan_version=1,
                    plan_step_index=0,
                    tool_name=tool_name,
                    status="COMPLETED",
                    policy_decision="ALLOWED",
                    reason_code="TOOL_COMPLETED",
                    duration_ms=1,
                ),
            ),
            safe_observations=(
                SafeObservationSnapshot(
                    status="SUCCESS",
                    reason_code="TOOL_COMPLETED",
                    document_ids=(uuid4(),),
                    chunk_ids=(uuid4(),),
                    citation_ids=("ev_1",),
                    duration_ms=1,
                ),
            ),
        )


class _CancelledLoop:
    async def run(self, **_: object) -> AgentRunOutcome:
        raise asyncio.CancelledError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("loop", "expected_status", "error_type"),
    [
        (_UnauthorizedObservationLoop(), "FAILED", Exception),
        (_CancelledLoop(), "CANCELLED", asyncio.CancelledError),
    ],
)
async def test_unsafe_partial_history_rolls_back_and_cancellation_is_terminal(
    auth_harness: AuthHarness,
    loop: object,
    expected_status: str,
    error_type: type[BaseException],
) -> None:
    alice_token = await _login(auth_harness.client, "alice@example.com")
    conversation = await _create_conversation(
        auth_harness, alice_token, f"Safe failure {expected_status}"
    )
    conversation_id = UUID(conversation["id"])
    async with auth_harness.session_factory() as session:
        user = await get_user_by_email(session, "alice@example.com")
        assert user is not None
        context = build_authorization_context(user)
        assert context is not None
        service = AgentRunService(
            session,
            cast(Any, loop),
            cast(Any, _EmptyGateway()),
            model_name="fake-agent",
            route_reason_code="AGENTIC_REQUEST",
        )
        with pytest.raises(error_type):
            await service.run(
                context,
                conversation_id=conversation_id,
                question="A question that must not enter safe history.",
                response_mode=ResponseMode.DEEP,
                request_id=f"safe-failure-{expected_status.casefold()}",
            )

    async with auth_harness.session_factory() as session:
        runs = (
            (
                await session.execute(
                    select(AgentRun).where(AgentRun.conversation_id == conversation_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(runs) == 1
        run = runs[0]
        assert run.status == expected_status
        assert run.completed_at is not None
        assert (
            not (
                await session.execute(
                    select(AgentPlanVersion).where(AgentPlanVersion.run_id == run.id)
                )
            )
            .scalars()
            .all()
        )
        assert (
            not (await session.execute(select(AgentStep).where(AgentStep.run_id == run.id)))
            .scalars()
            .all()
        )
        assert (
            not (
                await session.execute(
                    select(AgentObservationRecord).where(AgentObservationRecord.run_id == run.id)
                )
            )
            .scalars()
            .all()
        )
        assert (
            not (
                await session.execute(
                    select(Message).where(Message.conversation_id == conversation_id)
                )
            )
            .scalars()
            .all()
        )
