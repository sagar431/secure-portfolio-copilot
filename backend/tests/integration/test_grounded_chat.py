import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.models.chat import ChatMessageRequest, ChatRequestTrace, Conversation, Message
from app.models.documents import DocumentChunk
from app.models.memory import Memory, MemorySource
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
async def test_owned_history_orders_legacy_tied_message_pairs_chronologically(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    conversation = await _create_conversation(auth_harness, alice, "Legacy ordering")
    first_time = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    async with auth_harness.session_factory() as session:
        stored = await session.get(Conversation, UUID(conversation["id"]))
        assert stored is not None
        for role, content, request_id, created_at in (
            ("assistant", "First answer", "legacy-1", first_time),
            ("user", "First question", "legacy-1", first_time),
            ("assistant", "Second answer", "legacy-2", first_time + timedelta(seconds=1)),
            ("user", "Second question", "legacy-2", first_time + timedelta(seconds=1)),
        ):
            session.add(
                Message(
                    conversation_id=stored.id,
                    tenant_id=stored.tenant_id,
                    user_id=stored.user_id,
                    role=role,
                    content=content,
                    request_id=request_id,
                    created_at=created_at,
                )
            )
        await session.commit()

    response = await auth_harness.client.get(
        f"/api/conversations/{conversation['id']}/messages",
        headers={"Authorization": f"Bearer {alice}"},
    )

    assert response.status_code == 200
    assert [item["content"] for item in response.json()["data"]["messages"]] == [
        "First question",
        "First answer",
        "Second question",
        "Second answer",
    ]


@pytest.mark.asyncio
async def test_legacy_generic_title_is_displayed_from_first_owned_user_message(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    conversation = await _create_conversation(auth_harness, alice, "Evaluation")
    greeting = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/messages",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "Hello, how are you?"},
    )
    assert greeting.status_code == 200
    first_request = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/messages",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "Show me Atlas Finance results."},
    )
    assert first_request.status_code == 200

    listed = await auth_harness.client.get(
        "/api/conversations", headers={"Authorization": f"Bearer {alice}"}
    )

    assert listed.status_code == 200
    assert listed.json()["data"]["conversations"][0]["title"] == ("Show me Atlas Finance results")
    async with auth_harness.session_factory() as session:
        stored = await session.get(Conversation, UUID(conversation["id"]))
        assert stored is not None
        assert stored.title == "Evaluation"


@pytest.mark.asyncio
async def test_validated_ndjson_stream_orders_events_and_matches_persisted_result(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    conversation = await _create_conversation(auth_harness, alice, "Streaming greeting")
    client_message_id = str(uuid4())
    request_payload = {
        "content": "Hello, how are you?",
        "client_message_id": client_message_id,
    }
    response = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/messages/stream",
        headers={"Authorization": f"Bearer {alice}"},
        json=request_payload,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == [
        "message.started",
        "route.selected",
        "answer.delta",
        "message.completed",
    ]
    assert events[1]["intent"] == "CASUAL"
    completed = events[-1]["result"]
    assert (
        "".join(event["delta"] for event in events if event["type"] == "answer.delta")
        == completed["answer"]
    )
    assert completed["status"] == "casual"
    assert completed["citations"] == []
    assert "raw_provider" not in response.text

    async with auth_harness.session_factory() as session:
        persisted = (
            (
                await session.execute(
                    select(Message)
                    .where(
                        Message.conversation_id == UUID(conversation["id"]),
                        Message.role == "assistant",
                    )
                    .order_by(Message.created_at.desc())
                )
            )
            .scalars()
            .one()
        )
        trace = (
            (
                await session.execute(
                    select(ChatRequestTrace).where(
                        ChatRequestTrace.conversation_id == UUID(conversation["id"])
                    )
                )
            )
            .scalars()
            .one()
        )
    assert persisted.content == completed["answer"]
    assert trace.intent_route == "CASUAL"
    assert trace.retrieved_document_ids == []

    replay = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/messages/stream",
        headers={"Authorization": f"Bearer {alice}"},
        json=request_payload,
    )
    replay_events = [json.loads(line) for line in replay.text.splitlines()]
    replay_completed = replay_events[-1]["result"]
    assert replay_completed["user_message_id"] == completed["user_message_id"]
    assert replay_completed["assistant_message_id"] == completed["assistant_message_id"]
    async with auth_harness.session_factory() as session:
        message_count = await session.scalar(
            select(func.count(Message.id)).where(
                Message.conversation_id == UUID(conversation["id"])
            )
        )
        request_count = await session.scalar(
            select(func.count(ChatMessageRequest.id)).where(
                ChatMessageRequest.conversation_id == UUID(conversation["id"])
            )
        )
    assert message_count == 2
    assert request_count == 1


@pytest.mark.asyncio
async def test_grounded_stream_emits_safe_progress_before_validated_answer_and_citations(
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
        idempotency_key="chat-stream-progress-pdf-0001",
    )
    conversation = await _create_conversation(auth_harness, alice, "Streaming evidence")
    response = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/messages/stream",
        headers={"Authorization": f"Bearer {alice}"},
        json={
            "content": "What drove Margin Compression for Orion?",
            "client_message_id": str(uuid4()),
        },
    )
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines()]
    types = [item["type"] for item in events]
    assert types[:5] == [
        "message.started",
        "route.selected",
        "retrieval.started",
        "retrieval.completed",
        "memory.loaded",
    ]
    first_answer = types.index("answer.delta")
    first_citation = types.index("citation")
    assert first_answer > types.index("memory.loaded")
    assert first_citation > first_answer
    assert types[-1] == "message.completed"
    completed = events[-1]["result"]
    assert completed["status"] == "grounded"
    assert "raw_provider" not in response.text
    assert "system_instruction" not in response.text


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

    memories = await auth_harness.client.get(
        "/api/memories?memory_type=EPISODIC&memory_status=ACTIVE",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert memories.status_code == 200
    episodes = memories.json()["data"]["memories"]
    assert len(episodes) == 1
    assert episodes[0]["sources"]
    leo = await _login(auth_harness.client, "leo@example.com")
    leo_memories = await auth_harness.client.get(
        "/api/memories?memory_type=EPISODIC",
        headers={"Authorization": f"Bearer {leo}"},
    )
    assert leo_memories.json()["data"]["memories"] == []

    recall_conversation = await _create_conversation(
        auth_harness, alice, "Recall prior investigation"
    )
    recalled = await auth_harness.client.post(
        f"/api/conversations/{recall_conversation['id']}/messages",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "What did I investigate last time?"},
    )
    assert recalled.status_code == 200
    recalled_data = recalled.json()["data"]
    assert recalled_data["status"] == "memory_recall"
    assert recalled_data["intent_route"] == "MEMORY_RECALL"
    assert recalled_data["answer"].startswith("From your private memory/history:")
    assert "not current financial facts" in recalled_data["answer"]
    assert recalled_data["citations"] == []

    continued = await auth_harness.client.post(
        f"/api/conversations/{recall_conversation['id']}/messages",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "Continue that investigation."},
    )
    assert continued.status_code == 200
    continued_data = continued.json()["data"]
    assert continued_data["status"] == "grounded"
    assert continued_data["intent_route"] == "MEMORY_RECALL"
    assert continued_data["citations"]

    leo_conversation = await _create_conversation(auth_harness, leo, "Leo recall")
    leo_recall = await auth_harness.client.post(
        f"/api/conversations/{leo_conversation['id']}/messages",
        headers={"Authorization": f"Bearer {leo}"},
        json={"content": "What did I investigate last time?"},
    )
    assert leo_recall.status_code == 200
    leo_answer = leo_recall.json()["data"]["answer"]
    assert leo_answer.startswith("I don’t have a recent authorized investigation")
    assert "Margin Compression" not in leo_answer

    async with auth_harness.session_factory() as session:
        episode = await session.get(Memory, UUID(episodes[0]["id"]))
        assert episode is not None
        source_link = (
            (
                await session.execute(
                    select(MemorySource).where(MemorySource.memory_id == episode.id)
                )
            )
            .scalars()
            .first()
        )
        assert source_link is not None
        source = await session.get(DocumentChunk, source_link.chunk_id)
        assert source is not None
        source.active = False
        await session.commit()
    revoked = await auth_harness.client.get(
        "/api/memories?memory_type=EPISODIC",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert episodes[0]["id"] not in {item["id"] for item in revoked.json()["data"]["memories"]}


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
    foreign_history = await auth_harness.client.get(
        f"/api/conversations/{conversation['id']}/messages",
        headers={"Authorization": f"Bearer {leo}"},
    )
    assert foreign_history.status_code == 404
    foreign = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/messages",
        headers={"Authorization": f"Bearer {leo}"},
        json={"content": "Show me the conversation."},
    )
    assert foreign.status_code == 404
    foreign_stream = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/messages/stream",
        headers={"Authorization": f"Bearer {leo}"},
        json={"content": "Show me Alice's conversation."},
    )
    assert foreign_stream.status_code == 200
    stream_events = [json.loads(line) for line in foreign_stream.text.splitlines()]
    assert [item["type"] for item in stream_events] == ["message.started", "error"]
    assert conversation["title"] not in foreign_stream.text
    assert "Alice only" not in foreign_stream.text

    for question in ("show me atlas data", "show me orion legal clause"):
        response = await auth_harness.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            headers={"Authorization": f"Bearer {alice}"},
            json={"content": question},
        )
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["status"] == "refused"
        assert payload["intent_route"] == "REFUSE"
        assert payload["claims"] == []
        assert payload["citations"] == []
        assert payload["answer"].startswith("I can’t perform that request")

    owner_history = await auth_harness.client.get(
        f"/api/conversations/{conversation['id']}/messages",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert owner_history.status_code == 200
    assert owner_history.json()["data"]["has_more"] is False
    assert [item["role"] for item in owner_history.json()["data"]["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]

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
