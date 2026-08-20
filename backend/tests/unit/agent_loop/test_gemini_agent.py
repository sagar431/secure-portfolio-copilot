from types import SimpleNamespace

import pytest
from google.genai import types

from app.agent.contracts import AgentModelError, AgentModelErrorCode
from app.agent.gemini import GeminiDecisionProvider, GeminiPerceptionProvider
from app.agent.models import (
    EvidenceStatus,
    GoalStatus,
    PerceptionMode,
    PerceptionSnapshot,
)


class _Models:
    def __init__(self, owner: "_Client") -> None:
        self.owner = owner

    async def generate_content(self, **kwargs: object) -> object:
        self.owner.calls.append(kwargs)
        config = kwargs["config"]
        assert isinstance(config, types.GenerateContentConfig)
        if "Perception" in str(config.system_instruction):
            parsed = {
                "mode": "user_query",
                "intent": "document_lookup",
                "domain": "portfolio_documents",
                "entities": [],
                "result_requirement": "grounded_answer",
                "required_capabilities": ["QUERY_DOCUMENTS"],
                "ambiguities": [],
                "risk_flags": [],
                "evidence_status": "none",
                "local_goal_status": "pending",
                "global_goal_status": "pending",
                "confidence": 0.9,
                "reason_code": "QUERY_CLASSIFIED",
            }
        else:
            parsed = {
                "plan": {
                    "version": 1,
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
                    "arguments": {"query": "synthetic", "top_k": 2},
                    "reason_code": "SEARCH",
                },
                "replan": False,
            }
        return SimpleNamespace(parsed=parsed)


class _AsyncClient:
    def __init__(self, owner: "_Client") -> None:
        self.models = _Models(owner)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _Client:
    instances: list["_Client"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.calls: list[dict[str, object]] = []
        self.aio = _AsyncClient(self)
        self.instances.append(self)


def _perception() -> PerceptionSnapshot:
    return PerceptionSnapshot(
        mode=PerceptionMode.USER_QUERY,
        intent="document_lookup",
        domain="portfolio_documents",
        result_requirement="grounded_answer",
        required_capabilities=("QUERY_DOCUMENTS",),
        evidence_status=EvidenceStatus.NONE,
        local_goal_status=GoalStatus.PENDING,
        global_goal_status=GoalStatus.PENDING,
        confidence=0.9,
        reason_code="QUERY_CLASSIFIED",
    )


@pytest.mark.asyncio
async def test_gemini_uses_separate_structured_stages_without_tools_or_thoughts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Client.instances.clear()
    monkeypatch.setattr("app.agent.gemini.genai.Client", _Client)
    kwargs = {
        "api_key": "synthetic",
        "model_name": "gemini-3.7-flash",
        "timeout_seconds": 3,
        "max_output_tokens": 512,
    }
    perception = GeminiPerceptionProvider(**kwargs)
    decision = GeminiDecisionProvider(**kwargs)

    snapshot = await perception.perceive_user_query(query="Synthetic question")
    result = await decision.decide_initial(
        query="Synthetic question",
        perception=snapshot,
        permitted_tools=frozenset({"portfolio.search_authorized_documents"}),
    )

    assert snapshot.mode == PerceptionMode.USER_QUERY
    assert result.next_action.action_name == "portfolio.search_authorized_documents"
    assert len(_Client.instances) == 2
    for instance in _Client.instances:
        call = instance.calls[0]
        config = call["config"]
        assert isinstance(config, types.GenerateContentConfig)
        assert config.tools is None
        assert config.thinking_config is not None
        assert config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
        assert config.thinking_config.include_thoughts is False
        assert instance.aio.closed


@pytest.mark.asyncio
async def test_gemini_malformed_scope_argument_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GeminiDecisionProvider(
        api_key="synthetic", model_name="gemini-3.7-flash", timeout_seconds=3, max_output_tokens=512
    )

    async def malformed(*args: object, **kwargs: object) -> object:
        from app.agent.models import DecisionResult

        return DecisionResult.model_validate(
            {
                "plan": {
                    "version": 1,
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
                    "arguments": {"tenant_id": "forged"},
                    "reason_code": "SEARCH",
                },
                "replan": False,
            },
            strict=False,
        )

    monkeypatch.setattr(provider._stage, "_once", malformed)
    with pytest.raises(AgentModelError) as raised:
        await provider.decide_initial(
            query="Synthetic", perception=_perception(), permitted_tools=frozenset()
        )
    assert raised.value.code == AgentModelErrorCode.INVALID_RESPONSE
