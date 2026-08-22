import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.auth.repository import get_user_by_email
from app.models.agent_runs import AgentApprovalRequest, AgentPlanVersion, AgentRun, AgentStep
from app.models.identity import MembershipStatus, UserStatus
from tests.conftest import AuthHarness
from tests.integration.test_authorized_search import _login, _metadata, _upload_and_approve
from tests.integration.test_grounded_chat import _create_conversation


async def _setup(auth_harness: AuthHarness) -> tuple[str, str, dict[str, Any]]:
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
        idempotency_key="agent-approval-source-0001",
    )
    conversation = await _create_conversation(auth_harness, alice, "Approval controls")
    return alice, conversation["id"], conversation


async def _guided(
    auth_harness: AuthHarness, token: str, conversation_id: str, question: str
) -> dict[str, Any]:
    response = await auth_harness.client.post(
        f"/api/conversations/{conversation_id}/agent-runs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": question,
            "response_mode": "deep",
            "agent_control_mode": "guided",
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json()["data"])


@pytest.mark.asyncio
async def test_guided_pause_approve_once_same_run_replay_and_safe_projection(
    auth_harness: AuthHarness,
) -> None:
    alice, conversation_id, _ = await _setup(auth_harness)
    pending = await _guided(
        auth_harness, alice, conversation_id, "What drove Margin Compression for Orion?"
    )
    assert pending["outcome"] == "awaiting_approval"
    run_id = pending["agent_session_id"]
    approval = pending["approval"]
    assert approval["status"] == "PENDING"
    assert approval["tool_name"] == "portfolio.search_authorized_documents"
    assert set(approval) == {
        "approval_id",
        "run_id",
        "status",
        "action_label",
        "safe_explanation",
        "tool_name",
        "risk_level",
        "resource_type",
        "estimated_cost_class",
        "safe_scope_summary",
        "remaining_budget",
        "expires_at",
    }
    serialized = str(pending).casefold()
    for forbidden in ("arguments", "query", "prompt", "reasoning", "fingerprint", "token"):
        assert forbidden not in serialized

    async with auth_harness.session_factory() as session:
        run = await session.get(AgentRun, UUID(run_id))
        assert run is not None and run.status == "AWAITING_APPROVAL"
        assert (
            await session.scalar(
                select(func.count()).select_from(AgentStep).where(AgentStep.run_id == run.id)
            )
            == 0
        )

    endpoint = f"/api/agent-runs/{run_id}/approvals/{approval['approval_id']}/resolve"
    tampered = await auth_harness.client.post(
        endpoint,
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "approve_once", "action_argument_hash": "0" * 64},
    )
    assert tampered.status_code == 422

    approved = await auth_harness.client.post(
        endpoint,
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "approve_once"},
    )
    assert approved.status_code == 200, approved.text
    result = approved.json()["data"]
    assert result["agent_session_id"] == run_id
    assert result["terminal_status"] == "completed"
    assert result["step_count"] == 1

    replay = await auth_harness.client.post(
        endpoint,
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "approve_once"},
    )
    assert replay.status_code == 409
    async with auth_harness.session_factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(AgentStep).where(AgentStep.run_id == UUID(run_id))
            )
            == 1
        )


@pytest.mark.asyncio
async def test_reject_stop_foreign_ids_and_concurrent_approval_fail_closed(
    auth_harness: AuthHarness,
) -> None:
    alice, conversation_id, _ = await _setup(auth_harness)
    leo = await _login(auth_harness.client, "leo@example.com")

    rejected = await _guided(auth_harness, alice, conversation_id, "Summarize Orion finance.")
    reject_url = (
        f"/api/agent-runs/{rejected['agent_session_id']}/approvals/"
        f"{rejected['approval']['approval_id']}/resolve"
    )
    foreign = await auth_harness.client.post(
        reject_url,
        headers={"Authorization": f"Bearer {leo}"},
        json={"action": "reject"},
    )
    assert foreign.status_code == 404
    response = await auth_harness.client.post(
        reject_url,
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "reject"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "REJECTED"
    async with auth_harness.session_factory() as session:
        rejected_steps = await session.scalar(
            select(func.count())
            .select_from(AgentStep)
            .where(AgentStep.run_id == UUID(rejected["agent_session_id"]))
        )
        assert rejected_steps == 0

    stopped = await _guided(auth_harness, alice, conversation_id, "Summarize Orion results.")
    response = await auth_harness.client.post(
        f"/api/agent-runs/{stopped['agent_session_id']}/stop",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"
    async with auth_harness.session_factory() as session:
        stopped_run = await session.get(AgentRun, UUID(stopped["agent_session_id"]))
        assert stopped_run is not None and stopped_run.status == "CANCELLED"

    changed = await _guided(auth_harness, alice, conversation_id, "Summarize Orion finance.")
    async with auth_harness.session_factory() as session:
        original_plans = tuple(
            (
                await session.scalars(
                    select(AgentPlanVersion)
                    .where(AgentPlanVersion.run_id == UUID(changed["agent_session_id"]))
                    .order_by(AgentPlanVersion.version)
                )
            ).all()
        )
        original_plan_snapshot = tuple(
            (item.id, item.version, item.change_reason_code, item.planned_step_count)
            for item in original_plans
        )
    change_response = await auth_harness.client.post(
        f"/api/agent-runs/{changed['agent_session_id']}/approvals/"
        f"{changed['approval']['approval_id']}/change-request",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "Summarize Orion approved results."},
    )
    assert change_response.status_code == 200, change_response.text
    changed_data = change_response.json()["data"]
    assert changed_data["agent_session_id"] != changed["agent_session_id"]
    async with auth_harness.session_factory() as session:
        old_run = await session.get(AgentRun, UUID(changed["agent_session_id"]))
        assert old_run is not None and old_run.status == "CANCELLED"
        unchanged_plans = tuple(
            (
                await session.scalars(
                    select(AgentPlanVersion)
                    .where(AgentPlanVersion.run_id == old_run.id)
                    .order_by(AgentPlanVersion.version)
                )
            ).all()
        )
        assert (
            tuple(
                (item.id, item.version, item.change_reason_code, item.planned_step_count)
                for item in unchanged_plans
            )
            == original_plan_snapshot
        )

    expired = await _guided(auth_harness, alice, conversation_id, "Summarize Orion results.")
    async with auth_harness.session_factory() as session:
        row = await session.get(AgentApprovalRequest, UUID(expired["approval"]["approval_id"]))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    expired_response = await auth_harness.client.post(
        f"/api/agent-runs/{expired['agent_session_id']}/approvals/"
        f"{expired['approval']['approval_id']}/resolve",
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "approve_once"},
    )
    assert expired_response.status_code == 409
    assert expired_response.json()["error"]["code"] == "approval_expired"

    concurrent = await _guided(auth_harness, alice, conversation_id, "Summarize Orion board pack.")
    concurrent_url = (
        f"/api/agent-runs/{concurrent['agent_session_id']}/approvals/"
        f"{concurrent['approval']['approval_id']}/resolve"
    )
    first, second = await asyncio.gather(
        auth_harness.client.post(
            concurrent_url,
            headers={"Authorization": f"Bearer {alice}"},
            json={"action": "approve_once"},
        ),
        auth_harness.client.post(
            concurrent_url,
            headers={"Authorization": f"Bearer {alice}"},
            json={"action": "approve_once"},
        ),
    )
    assert sorted((first.status_code, second.status_code)) == [200, 409]
    async with auth_harness.session_factory() as session:
        approvals = (
            await session.scalars(
                select(AgentApprovalRequest).where(
                    AgentApprovalRequest.run_id == UUID(concurrent["agent_session_id"])
                )
            )
        ).all()
        assert len(approvals) == 1
        assert approvals[0].status == "CONSUMED"


@pytest.mark.asyncio
async def test_approval_binding_scope_identity_and_unknown_ids_fail_closed(
    auth_harness: AuthHarness,
) -> None:
    alice, conversation_id, _ = await _setup(auth_harness)
    leo = await _login(auth_harness.client, "leo@example.com")

    for field, value in (
        ("plan_version", 2),
        ("proposed_step_number", 2),
        ("action_name", "portfolio.get_document_excerpt"),
        ("action_argument_hash", "0" * 64),
    ):
        pending = await _guided(auth_harness, alice, conversation_id, f"Check binding {field}.")
        async with auth_harness.session_factory() as session:
            row = await session.get(AgentApprovalRequest, UUID(pending["approval"]["approval_id"]))
            assert row is not None
            setattr(row, field, value)
            await session.commit()
        response = await auth_harness.client.post(
            f"/api/agent-runs/{pending['agent_session_id']}/approvals/"
            f"{pending['approval']['approval_id']}/resolve",
            headers={"Authorization": f"Bearer {alice}"},
            json={"action": "approve_once"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "approval_mismatch"
        async with auth_harness.session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AgentStep)
                    .where(AgentStep.run_id == UUID(pending["agent_session_id"]))
                )
                == 0
            )

    scope_changed = await _guided(auth_harness, alice, conversation_id, "Check scope binding.")
    async with auth_harness.session_factory() as session:
        row = await session.get(
            AgentApprovalRequest, UUID(scope_changed["approval"]["approval_id"])
        )
        assert row is not None
        row.authorization_scope_fingerprint = "0" * 64
        await session.commit()
    scope_response = await auth_harness.client.post(
        f"/api/agent-runs/{scope_changed['agent_session_id']}/approvals/"
        f"{scope_changed['approval']['approval_id']}/resolve",
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "approve_once"},
    )
    assert scope_response.status_code == 409
    assert scope_response.json()["error"]["code"] == "authorization_changed"

    known = await _guided(auth_harness, alice, conversation_id, "Check resource ownership.")
    known_url = (
        f"/api/agent-runs/{known['agent_session_id']}/approvals/"
        f"{known['approval']['approval_id']}/resolve"
    )
    foreign = await auth_harness.client.post(
        known_url,
        headers={"Authorization": f"Bearer {leo}"},
        json={"action": "approve_once"},
    )
    unknown_run = await auth_harness.client.post(
        f"/api/agent-runs/{uuid4()}/approvals/{known['approval']['approval_id']}/resolve",
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "approve_once"},
    )
    unknown_approval = await auth_harness.client.post(
        f"/api/agent-runs/{known['agent_session_id']}/approvals/{uuid4()}/resolve",
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "approve_once"},
    )
    assert {foreign.status_code, unknown_run.status_code, unknown_approval.status_code} == {404}
    assert {
        (item.json()["error"]["code"], item.json()["error"]["message"])
        for item in (foreign, unknown_run, unknown_approval)
    } == {("not_found", "Agent run was not found.")}


@pytest.mark.asyncio
async def test_disabled_user_and_revoked_membership_cannot_resume(
    auth_harness: AuthHarness,
) -> None:
    alice, conversation_id, _ = await _setup(auth_harness)
    pending = await _guided(auth_harness, alice, conversation_id, "Check disabled identity.")
    async with auth_harness.session_factory() as session:
        user = await get_user_by_email(session, "alice@example.com")
        assert user is not None
        user.status = UserStatus.DISABLED.value
        await session.commit()
    disabled = await auth_harness.client.post(
        f"/api/agent-runs/{pending['agent_session_id']}/approvals/"
        f"{pending['approval']['approval_id']}/resolve",
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "approve_once"},
    )
    assert disabled.status_code == 401

    async with auth_harness.session_factory() as session:
        user = await get_user_by_email(session, "alice@example.com")
        assert user is not None
        user.status = UserStatus.ACTIVE.value
        await session.commit()
    await auth_harness.client.post(
        f"/api/agent-runs/{pending['agent_session_id']}/stop",
        headers={"Authorization": f"Bearer {alice}"},
    )

    pending = await _guided(auth_harness, alice, conversation_id, "Check revoked membership.")
    async with auth_harness.session_factory() as session:
        user = await get_user_by_email(session, "alice@example.com")
        assert user is not None
        for membership in user.memberships:
            membership.status = MembershipStatus.REVOKED.value
        await session.commit()
    revoked = await auth_harness.client.post(
        f"/api/agent-runs/{pending['agent_session_id']}/approvals/"
        f"{pending['approval']['approval_id']}/resolve",
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "approve_once"},
    )
    assert revoked.status_code == 401
    async with auth_harness.session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AgentStep)
                .where(AgentStep.run_id == UUID(pending["agent_session_id"]))
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("control_mode", ["balanced", "autonomous"])
async def test_balanced_and_autonomous_run_authorized_read_only_tools_without_prompt(
    auth_harness: AuthHarness, control_mode: str
) -> None:
    alice, conversation_id, _ = await _setup(auth_harness)
    response = await auth_harness.client.post(
        f"/api/conversations/{conversation_id}/agent-runs",
        headers={"Authorization": f"Bearer {alice}"},
        json={
            "content": "What drove Margin Compression for Orion?",
            "response_mode": "deep",
            "agent_control_mode": control_mode,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["terminal_status"] == "completed"
    async with auth_harness.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(AgentApprovalRequest))
        assert count == 0
