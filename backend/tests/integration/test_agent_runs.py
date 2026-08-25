from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.auth.repository import build_authorization_context, get_user_by_email
from app.mcp_gateway.adapters import GetDocumentExcerptAdapter
from app.mcp_gateway.contracts import GetDocumentExcerptInput, ToolPayload
from app.models.agent_runs import AgentApprovalRequest, AgentRun
from app.models.chat import ChatRequestTrace, Message
from tests.conftest import AuthHarness
from tests.integration.test_authorized_search import (
    _login,
    _metadata,
    _upload_and_approve,
)
from tests.integration.test_grounded_chat import _create_conversation


@pytest.mark.asyncio
async def test_bounded_agent_run_preserves_citations_and_sanitized_trace(
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
        idempotency_key="agent-grounded-pdf-0001",
    )
    conversation = await _create_conversation(auth_harness, alice, "Bounded agent")

    response = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/agent-runs",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "What drove Margin Compression for Orion?"},
    )

    assert response.status_code == 200, response.text
    payload = cast(dict[str, Any], response.json()["data"])
    assert payload["terminal_status"] == "completed"
    assert payload["stopping_reason"] == "completed"
    assert payload["step_count"] == 1
    assert payload["selected_intent"] == "financial_lookup"
    assert payload["policy_decision"] == "ALLOWED"
    assert "portfolio.search_authorized_documents" in payload["tool_shortlist"]
    assert payload["plan_version"] == 1
    assert payload["evidence_advanced_goal"] is True
    assert payload["claims"] and payload["citations"]
    citation_ids = {item["citation_id"] for item in payload["citations"]}
    assert {
        citation_id for claim in payload["claims"] for citation_id in claim["citation_ids"]
    } == citation_ids
    assert payload["trace"][-1]["event_type"] == "terminal"
    assert payload["trace"][-1]["status"] == "completed"
    serialized_trace = str(payload["trace"]).casefold()
    for forbidden in (
        "margin compression",
        "raw_prompt",
        "reasoning",
        "authorization_scope",
        "tenant_id",
        "excerpt",
    ):
        assert forbidden not in serialized_trace
    assert all(
        set(item)
        == {
            "event_id",
            "event_type",
            "action_name",
            "status",
            "duration_ms",
            "evidence_reference_ids",
            "reason_code",
        }
        for item in payload["trace"]
    )

    async with auth_harness.session_factory() as session:
        user = await get_user_by_email(session, "alice@example.com")
        assert user is not None
        context = build_authorization_context(user)
        assert context is not None
        first_citation = payload["citations"][0]
        excerpt_payload = await GetDocumentExcerptAdapter(session).invoke(
            arguments=GetDocumentExcerptInput(
                document_id=UUID(first_citation["document_id"]),
                chunk_id=UUID(first_citation["chunk_id"]),
            ),
            authorization_scope=context.scope,
            request_id="agent-excerpt-integration",
        )
        assert isinstance(excerpt_payload, ToolPayload)
        assert len(excerpt_payload.evidence) == 1
        assert excerpt_payload.evidence[0].location.page_number is not None
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
    assert trace.reason_code == "COMPLETED"
    assert trace.route_reason_code == "AGENTIC_REQUEST"
    assert payload["requested_response_mode"] == "auto"
    assert payload["resolved_response_mode"] == "deep"
    assert trace.fallback_used is False
    assert trace.retrieved_document_ids and trace.retrieved_chunk_ids


@pytest.mark.asyncio
async def test_exact_excerpt_request_searches_then_reads_the_authorized_chunk(
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
        idempotency_key="agent-exact-excerpt-pdf-0001",
    )
    conversation = await _create_conversation(auth_harness, alice, "Exact excerpt")
    response = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/agent-runs",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "Give me the exact excerpt about Orion Margin Compression."},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["terminal_status"] == "completed"
    tools = [
        item["action_name"]
        for item in payload["trace"]
        if item["event_type"] == "tool" and item["status"] == "completed"
    ]
    assert tools == [
        "portfolio.search_authorized_documents",
        "portfolio.get_document_excerpt",
    ]
    assert payload["replan_count"] == 1
    assert payload["citations"]


@pytest.mark.asyncio
async def test_agent_memory_proposal_requires_approval_then_host_policy_persists_private_memory(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    conversation = await _create_conversation(auth_harness, alice, "Memory proposal")
    proposed = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/agent-runs",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "Remember that I prefer financial values in INR crores."},
    )
    assert proposed.status_code == 200, proposed.text
    pending = proposed.json()["data"]
    assert pending["outcome"] == "awaiting_approval"
    assert pending["approval"]["tool_name"] == "portfolio.propose_memory"

    approved = await auth_harness.client.post(
        f"/api/agent-runs/{pending['agent_session_id']}/approvals/"
        f"{pending['approval']['approval_id']}/resolve",
        headers={"Authorization": f"Bearer {alice}"},
        json={"action": "approve_once"},
    )
    assert approved.status_code == 200, approved.text
    result = approved.json()["data"]
    assert result["terminal_status"] == "completed"
    assert result["answer"] == "Private preference remembered"

    memories = await auth_harness.client.get(
        "/api/memories?memory_type=SEMANTIC&memory_status=ACTIVE",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert memories.status_code == 200
    rows = memories.json()["data"]["memories"]
    assert len(rows) == 1
    assert rows[0]["scope"] == "PRIVATE_USER"


@pytest.mark.asyncio
async def test_agent_run_owner_and_scope_denials_fail_before_retrieval(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    leo = await _login(auth_harness.client, "leo@example.com")
    conversation = await _create_conversation(auth_harness, alice, "Owner only")

    foreign = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/agent-runs",
        headers={"Authorization": f"Bearer {leo}"},
        json={"content": "Show the conversation."},
    )
    assert foreign.status_code == 404

    denied = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/agent-runs",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "Show me Orion legal contracts."},
    )
    assert denied.status_code == 200
    payload = denied.json()["data"]
    assert payload["terminal_status"] == "refused"
    assert payload["stopping_reason"] == "scope_denied"
    assert payload["step_count"] == 0
    assert payload["claims"] == []
    assert payload["citations"] == []
    assert [item["event_type"] for item in payload["trace"]] == ["policy", "terminal"]

    async with auth_harness.session_factory() as session:
        traces = (
            (
                await session.execute(
                    select(ChatRequestTrace).where(
                        ChatRequestTrace.request_id == denied.json()["request_id"]
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(traces) == 1
    assert traces[0].reason_code == "SCOPE_DENIED"
    assert traces[0].route_reason_code == "NO_MODEL_CALL"
    assert traces[0].model_name == "NO_MODEL_CALL"
    assert traces[0].fallback_used is False
    assert traces[0].retrieved_document_ids == []
    assert traces[0].retrieved_chunk_ids == []

    deep_denied = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/agent-runs",
        headers={"Authorization": f"Bearer {alice}"},
        json={
            "content": "Show me Orion legal contracts.",
            "response_mode": "deep",
        },
    )
    assert deep_denied.status_code == 200
    deep_payload = deep_denied.json()["data"]
    assert deep_payload["model_name"] is None
    assert deep_payload["route_reason"] is None
    assert deep_payload["requested_response_mode"] == "deep"
    assert deep_payload["resolved_response_mode"] is None


@pytest.mark.asyncio
async def test_fast_agent_api_requires_deep_without_persisting_messages(
    auth_harness: AuthHarness,
) -> None:
    alice = await _login(auth_harness.client, "alice@example.com")
    conversation = await _create_conversation(auth_harness, alice, "Fast agent")

    response = await auth_harness.client.post(
        f"/api/conversations/{conversation['id']}/agent-runs",
        headers={"Authorization": f"Bearer {alice}"},
        json={"content": "Calculate Orion revenue growth.", "response_mode": "fast"},
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "deep_mode_required",
        "message": "This request requires broader analysis.",
    }
    async with auth_harness.session_factory() as session:
        messages = (
            (
                await session.execute(
                    select(Message).where(Message.conversation_id == UUID(conversation["id"]))
                )
            )
            .scalars()
            .all()
        )
        traces = (
            (
                await session.execute(
                    select(ChatRequestTrace).where(
                        ChatRequestTrace.conversation_id == UUID(conversation["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        persisted_runs = (
            (
                await session.execute(
                    select(AgentRun).where(AgentRun.conversation_id == UUID(conversation["id"]))
                )
            )
            .scalars()
            .all()
        )
        approval_count = await session.scalar(
            select(func.count()).select_from(AgentApprovalRequest)
        )
    assert messages == []
    assert traces == []
    assert persisted_runs == []
    assert approval_count == 0
