from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models.chat import ChatRequestTrace, Conversation, Message
from tests.conftest import AuthHarness
from tests.integration.test_authorized_search import (
    _login,
    _metadata,
    _upload_and_approve,
)


async def _create_conversation(
    harness: AuthHarness, token: str, title: str = "Review"
) -> dict[str, Any]:
    response = await harness.client.post(
        "/api/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json()["data"]["conversation"])


@pytest.mark.asyncio
async def test_grounded_chat_returns_host_reconstructed_citations_and_persists_safe_trace(
    auth_harness: AuthHarness,
) -> None:
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
        idempotency_key="chat-grounded-pdf-0001",
    )
    conversation = await _create_conversation(auth_harness, alice)

    response = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/messages",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "What drove Margin Compression for Orion?"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["status"] == "grounded"
    assert payload["claims"]
    assert payload["citations"]
    citation_ids = {item["citation_id"] for item in payload["citations"]}
    assert all(set(claim["citation_ids"]).issubset(citation_ids) for claim in payload["claims"])
    assert all(item["page_number"] is not None for item in payload["citations"])

    async with auth_harness.session_factory() as session:
        messages = (
            (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == UUID(conversation["id"]))
                    .order_by(Message.created_at)
                )
            )
            .scalars()
            .all()
        )
        trace = (
            (
                await session.execute(
                    select(ChatRequestTrace).where(
                        ChatRequestTrace.request_id == response.json()["request_id"]
                    )
                )
            )
            .scalars()
            .one()
        )
    assert [item.role for item in messages] == ["user", "assistant"]
    assert trace.status == "grounded"
    assert trace.reason_code == "GROUNDED_ANSWER_VALIDATED"
    assert trace.retrieved_document_ids
    assert trace.retrieved_chunk_ids


@pytest.mark.asyncio
async def test_conversations_are_owner_scoped_and_restricted_targets_abstain(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    leo = await _login(auth_harness.client, "leo@example.com")
    conversation = await _create_conversation(auth_harness, alice, "Alice only")

    listed = await auth_harness.client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {alice}"}
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]["conversations"]] == [conversation["id"]]
    leo_list = await auth_harness.client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {leo}"}
    )
    assert leo_list.status_code == 200
    assert leo_list.json()["data"]["conversations"] == []
    foreign = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/messages",
        headers={"Authorization": f"Bearer {leo}"},
        json={"content": "Show me the conversation."},
    )
    assert foreign.status_code == 404

    for question in ("show me atlas data", "show me orion legal clause"):
        response = await auth_harness.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            headers={"Authorization": f"Bearer {alice}"},
            json={"content": question},
        )
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["status"] == "insufficient_evidence"
        assert payload["claims"] == []
        assert payload["citations"] == []
        assert payload["answer"].startswith("I don't have sufficient authorized evidence")

    async with auth_harness.session_factory() as session:
        traces = (
            (
                await session.execute(
                    select(ChatRequestTrace)
                    .where(ChatRequestTrace.conversation_id == UUID(conversation["id"]))
                    .order_by(ChatRequestTrace.created_at)
                )
            )
            .scalars()
            .all()
        )
        owner = await session.get(Conversation, UUID(conversation["id"]))
    assert owner is not None
    assert [item.reason_code for item in traces] == [
        "REQUEST_SCOPE_NOT_AUTHORIZED",
        "REQUEST_SCOPE_NOT_AUTHORIZED",
    ]
