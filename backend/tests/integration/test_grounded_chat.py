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
    assert all(item.model_name == "NO_MODEL_CALL" for item in traces)
    assert all(item.route_reason_code == "NO_MODEL_CALL" for item in traces)


@pytest.mark.asyncio
async def test_response_mode_api_routes_safely_and_fast_upgrade_does_not_persist(
    auth_harness: AuthHarness,
) -> None:
    auth_harness.settings.router_low_confidence_threshold = 0.0
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
        idempotency_key="chat-response-modes-0001",
    )
    conversation = await _create_conversation(auth_harness, alice, "Response modes")
    path = f"/api/conversations/{conversation['id']}/messages"
    headers = {"Authorization": f"Bearer {alice}"}
    simple_question = "What was Orion revenue in FY2025?"

    automatic = await auth_harness.client.post(
        path, headers=headers, json={"content": simple_question}
    )
    assert automatic.status_code == 200, automatic.text
    automatic_data = automatic.json()["data"]
    assert automatic_data["requested_response_mode"] == "auto"
    assert automatic_data["resolved_response_mode"] == "fast"
    assert automatic_data["route_reason"] == "SIMPLE_LOW_RISK"

    deep = await auth_harness.client.post(
        path,
        headers=headers,
        json={"content": simple_question, "response_mode": "deep"},
    )
    assert deep.status_code == 200, deep.text
    deep_data = deep.json()["data"]
    assert deep_data["requested_response_mode"] == "deep"
    assert deep_data["resolved_response_mode"] == "deep"
    assert deep_data["route_reason"] == "USER_REQUESTED_DEEP"
    assert [item["chunk_id"] for item in automatic_data["citations"]] == [
        item["chunk_id"] for item in deep_data["citations"]
    ]

    async with auth_harness.session_factory() as session:
        before_rejection = len(
            (
                await session.execute(
                    select(Message).where(Message.conversation_id == UUID(conversation["id"]))
                )
            )
            .scalars()
            .all()
        )

    rejected = await auth_harness.client.post(
        path,
        headers=headers,
        json={
            "content": "Compare Orion revenue across reporting periods.",
            "response_mode": "fast",
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"] == {
        "code": "deep_mode_required",
        "message": "This request requires broader analysis.",
    }
    assert "Orion revenue" not in rejected.text

    async with auth_harness.session_factory() as session:
        after_rejection = len(
            (
                await session.execute(
                    select(Message).where(Message.conversation_id == UUID(conversation["id"]))
                )
            )
            .scalars()
            .all()
        )
    assert after_rejection == before_rejection


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forged",
    [
        {"response_mode": "turbo"},
        {"model": "google/gemini-3.7-flash"},
        {"provider": "google-vertex"},
        {"route_reason": "USER_REQUESTED_DEEP"},
        {"tenant_id": "forged"},
    ],
)
async def test_response_mode_api_rejects_unknown_and_forged_controls(
    auth_harness: AuthHarness, forged: dict[str, str]
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    conversation = await _create_conversation(auth_harness, alice, "Strict modes")

    response = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/messages",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "What was revenue?", **forged},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
