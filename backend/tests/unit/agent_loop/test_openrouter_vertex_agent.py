from typing import Any

import pytest

from app.agent.contracts import AgentModelError, AgentModelErrorCode
from app.agent.models import (
    EvidenceStatus,
    GoalStatus,
    PerceptionEntities,
    PerceptionIntent,
    PerceptionMode,
    PerceptionSnapshot,
    RequiredEvidence,
    ResultRequirement,
)
from app.agent.openrouter_vertex import (
    OpenRouterVertexDecisionProvider,
    OpenRouterVertexPerceptionProvider,
)
from app.mcp_gateway.contracts import APPROVED_TOOL_NAMES
from app.mcp_gateway.gateway import ApprovedToolGateway
from app.openrouter_vertex import (
    OPENROUTER_BASE_URL,
    OPENROUTER_HEAVY_MODEL,
    OPENROUTER_PROVIDER,
    OpenRouterCompletion,
    OpenRouterVertexClient,
)
from tests.unit.mcp_gateway.test_gateway import _authorization_scope


def _client() -> OpenRouterVertexClient:
    return OpenRouterVertexClient(
        api_key="synthetic",
        base_url=OPENROUTER_BASE_URL,
        provider=OPENROUTER_PROVIDER,
        model_name=OPENROUTER_HEAVY_MODEL,
        timeout_seconds=3,
        max_output_tokens=1536,
    )


def _perception_json(*, confidence: object = 0.9) -> str:
    import json

    return json.dumps(
        {
            "mode": "user_query",
            "intent": "financial_lookup",
            "domain": "portfolio_documents",
            "entities": {},
            "mentioned_scope_hints": {},
            "result_requirement": "grounded_answer",
            "required_evidence": ["financial_document"],
            "required_capabilities": ["QUERY_DOCUMENTS"],
            "ambiguities": [],
            "risk_flags": [],
            "evidence_status": "none",
            "local_goal_status": "pending",
            "global_goal_status": "pending",
            "confidence": confidence,
            "reason_code": "QUERY_CLASSIFIED",
            "clarification_question": None,
            "rationale_summary": "Authorized evidence is required.",
        }
    )


def _decision_json(*, arguments: dict[str, object] | None = None) -> str:
    import json

    return json.dumps(
        {
            "plan": {
                "version": 1,
                "plan_text": ["Search authorized evidence."],
                "steps": [
                    {
                        "step_index": 0,
                        "action_type": "TOOL_CALL",
                        "action_name": "portfolio.search_authorized_documents",
                        "status": "pending",
                        "reason_code": "SEARCH",
                    }
                ],
                "change_reason_code": "PLAN_CREATED",
            },
            "next_action": {
                "type": "TOOL_CALL",
                "action_name": "portfolio.search_authorized_documents",
                "arguments": arguments or {"query": "synthetic", "top_k": 2},
                "reason_code": "SEARCH",
            },
            "replan": False,
        }
    )


def _snapshot() -> PerceptionSnapshot:
    return PerceptionSnapshot(
        mode=PerceptionMode.USER_QUERY,
        intent=PerceptionIntent.FINANCIAL_LOOKUP,
        domain="portfolio_documents",
        entities=PerceptionEntities(financial_metrics=("revenue",)),
        result_requirement=ResultRequirement.GROUNDED_ANSWER,
        required_evidence=(RequiredEvidence.FINANCIAL_DOCUMENT,),
        required_capabilities=("QUERY_DOCUMENTS",),
        evidence_status=EvidenceStatus.NONE,
        local_goal_status=GoalStatus.PENDING,
        global_goal_status=GoalStatus.PENDING,
        confidence=0.9,
        reason_code="QUERY_CLASSIFIED",
    )


def _completion(content: str) -> OpenRouterCompletion:
    return OpenRouterCompletion(content, "gen-synthetic", "stop", 10, 5, 2, 0)


@pytest.mark.asyncio
async def test_vertex_uses_separate_strict_perception_and_decision_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    calls: list[dict[str, Any]] = []

    async def complete(**kwargs: Any) -> OpenRouterCompletion:
        calls.append(kwargs)
        content = _perception_json() if len(calls) == 1 else _decision_json()
        kwargs["content_validator"](content)
        return _completion(content)

    monkeypatch.setattr(client, "complete", complete)
    perception = OpenRouterVertexPerceptionProvider(client=client)
    decision = OpenRouterVertexDecisionProvider(client=client)

    snapshot = await perception.perceive_user_query(query="Synthetic question")
    result = await decision.decide_initial(
        query="Synthetic question",
        perception=snapshot,
        permitted_tool_catalog=ApprovedToolGateway.permitted_catalog(
            _authorization_scope(), APPROVED_TOOL_NAMES
        ),
    )

    assert snapshot.mode == PerceptionMode.USER_QUERY
    assert result.next_action.action_name == "portfolio.search_authorized_documents"
    assert len(calls) == 2
    assert calls[0]["system_instruction"] != calls[1]["system_instruction"]
    assert all(call["max_attempts"] == 2 for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        _perception_json(confidence="0.9"),
        _decision_json(arguments={"tenant_id": "forged"}),
    ],
)
async def test_vertex_agent_contracts_reject_coercion_and_scope_smuggling(
    content: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client()

    async def complete(**kwargs: Any) -> OpenRouterCompletion:
        kwargs["content_validator"](content)
        return _completion(content)

    monkeypatch.setattr(client, "complete", complete)
    if "confidence" in content:
        operation = OpenRouterVertexPerceptionProvider(client=client).perceive_user_query(
            query="Synthetic"
        )
    else:
        operation = OpenRouterVertexDecisionProvider(client=client).decide_initial(
            query="Synthetic", perception=_snapshot(), permitted_tool_catalog=()
        )

    with pytest.raises(AgentModelError) as raised:
        await operation
    assert raised.value.code == AgentModelErrorCode.INVALID_RESPONSE
