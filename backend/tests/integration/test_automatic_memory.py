from uuid import UUID

import pytest
from sqlalchemy import select

from app.models.memory import Memory, MemoryAuditEvent, MemoryStatus, MemoryType
from tests.conftest import AuthHarness
from tests.integration.test_authorized_search import _login, _metadata, _upload_and_approve


async def _conversation(harness: AuthHarness, token: str) -> str:
    response = await harness.client.post(
        "/api/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Automatic memory demo"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["conversation"]["id"]


async def _message(harness: AuthHarness, token: str, conversation_id: str, content: str):
    return await harness.client.post(
        f"/api/conversations/{conversation_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": content, "response_mode": "auto"},
    )


@pytest.mark.asyncio
async def test_explicit_preference_is_automatic_private_audited_and_superseded(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    leo = await _login(auth_harness.client, "leo@example.com")
    conversation_id = await _conversation(auth_harness, alice)

    remembered = await _message(
        auth_harness,
        alice,
        conversation_id,
        "Remember that I prefer financial values in INR crores.",
    )
    assert remembered.status_code == 200, remembered.text
    assert remembered.json()["data"]["memory_notifications"] == ["Private preference remembered"]

    alice_active = await auth_harness.client.get(
        "/api/memories?memory_type=SEMANTIC&memory_status=ACTIVE",
        headers={"Authorization": f"Bearer {alice}"},
    )
    active = alice_active.json()["data"]["memories"]
    assert len(active) == 1
    assert active[0]["content"] == "Present financial values in INR crores."
    assert active[0]["scope"] == "PRIVATE_USER"
    assert active[0]["origin"] == "EXPLICIT_USER"
    assert active[0]["owner_display"].startswith("Alice")
    assert active[0]["source_conversation"] == "Automatic memory demo"

    nora = await _login(auth_harness.client, "nora@example.com")
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
        idempotency_key="automatic-memory-format-demo",
    )
    # A fresh login and request-scoped service instance must still load the PostgreSQL memory.
    alice_reauthenticated = await _login(auth_harness.client, "alice@example.com")
    fresh_conversation = await _conversation(auth_harness, alice_reauthenticated)
    formatted = await _message(
        auth_harness,
        alice_reauthenticated,
        fresh_conversation,
        "What was Orion revenue in FY2025?",
    )
    assert formatted.status_code == 200
    assert "Present financial values in INR crores." in formatted.json()["data"]["answer"]
    assert formatted.json()["data"]["citations"]

    leo_list = await auth_harness.client.get(
        "/api/memories", headers={"Authorization": f"Bearer {leo}"}
    )
    assert leo_list.status_code == 200
    assert leo_list.json()["data"]["memories"] == []
    foreign_delete = await auth_harness.client.delete(
        f"/api/memories/{active[0]['id']}", headers={"Authorization": f"Bearer {leo}"}
    )
    assert foreign_delete.status_code == 404

    changed = await _message(
        auth_harness,
        alice,
        conversation_id,
        "From now on use USD millions.",
    )
    assert changed.status_code == 200, changed.text
    refreshed = await auth_harness.client.get(
        "/api/memories?memory_type=SEMANTIC",
        headers={"Authorization": f"Bearer {alice}"},
    )
    by_status = {item["status"]: item for item in refreshed.json()["data"]["memories"]}
    assert by_status["ACTIVE"]["content"] == "Present financial values in USD millions."
    assert by_status["SUPERSEDED"]["content"] == "Present financial values in INR crores."

    async with auth_harness.session_factory() as session:
        memory_id = UUID(by_status["ACTIVE"]["id"])
        row = await session.get(Memory, memory_id)
        assert row is not None
        assert row.memory_type == MemoryType.SEMANTIC.value
        events = (
            (
                await session.execute(
                    select(MemoryAuditEvent).where(MemoryAuditEvent.memory_id == memory_id)
                )
            )
            .scalars()
            .all()
        )
        assert {event.action for event in events} == {"CREATE"}

    deleted = await auth_harness.client.delete(
        f"/api/memories/{by_status['ACTIVE']['id']}",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert deleted.status_code == 200
    after_delete = await auth_harness.client.get(
        "/api/memories?memory_type=SEMANTIC&memory_status=ACTIVE",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert after_delete.json()["data"]["memories"] == []


@pytest.mark.asyncio
async def test_long_conversation_is_bounded_and_gets_private_summary(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    leo = await _login(auth_harness.client, "leo@example.com")
    conversation_id = await _conversation(auth_harness, alice)
    for index in range(auth_harness.settings.memory_recent_message_limit // 2 + 1):
        response = await _message(
            auth_harness,
            alice,
            conversation_id,
            f"Question {index} with no matching authorized evidence.",
        )
        assert response.status_code == 200

    summaries = await auth_harness.client.get(
        "/api/memories?memory_type=CONVERSATION_SUMMARY&memory_status=ACTIVE",
        headers={"Authorization": f"Bearer {alice}"},
    )
    rows = summaries.json()["data"]["memories"]
    assert len(rows) == 1
    assert rows[0]["scope"] == "PRIVATE_USER"
    assert len(rows[0]["content"]) <= 1000
    leo_summaries = await auth_harness.client.get(
        "/api/memories?memory_type=CONVERSATION_SUMMARY",
        headers={"Authorization": f"Bearer {leo}"},
    )
    assert leo_summaries.json()["data"]["memories"] == []
    async with auth_harness.session_factory() as session:
        summary = await session.get(Memory, UUID(rows[0]["id"]))
        assert summary is not None
        assert summary.status == MemoryStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_inferred_preference_requires_owner_confirmation_and_can_be_dismissed(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    leo = await _login(auth_harness.client, "leo@example.com")
    conversation_id = await _conversation(auth_harness, alice)
    proposed = await _message(
        auth_harness,
        alice,
        conversation_id,
        "I tend to like concise tables.",
    )
    assert proposed.status_code == 200
    assert proposed.json()["data"]["memory_notifications"] == ["Preference awaiting confirmation"]
    pending = await auth_harness.client.get(
        "/api/memories?memory_status=PENDING_CONFIRMATION",
        headers={"Authorization": f"Bearer {alice}"},
    )
    row = pending.json()["data"]["memories"][0]
    assert row["content"] == "Use concise tables."
    assert row["can_confirm"] is True
    foreign_confirm = await auth_harness.client.post(
        f"/api/memories/{row['id']}/confirm",
        headers={"Authorization": f"Bearer {leo}"},
    )
    assert foreign_confirm.status_code == 404
    confirmed = await auth_harness.client.post(
        f"/api/memories/{row['id']}/confirm",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "ACTIVE"
    deleted = await auth_harness.client.post(
        f"/api/memories/{row['id']}/dismiss",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert deleted.status_code == 404
