import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.agent.factory import create_agent_stage_providers
from app.agent.runpod import RunpodKimiDecisionProvider, RunpodKimiPerceptionProvider
from app.chat.contracts import (
    GroundedEvidence,
    GroundedGenerationRequest,
    LLMErrorCode,
    LLMProviderError,
)
from app.chat.factory import create_llm_provider
from app.chat.runpod import RunpodKimiLLMProvider
from app.core.config import Settings
from app.runpod_kimi import (
    RUNPOD_KIMI_BASE_URL,
    RUNPOD_KIMI_MODEL,
    KimiCompletion,
    KimiErrorCode,
    KimiProviderError,
    RunpodKimiClient,
)


def _client(*, max_output_tokens: int = 1024) -> RunpodKimiClient:
    return RunpodKimiClient(
        api_key="synthetic-runpod-key-never-log",
        base_url=RUNPOD_KIMI_BASE_URL,
        model_name=RUNPOD_KIMI_MODEL,
        timeout_seconds=3,
        max_output_tokens=max_output_tokens,
    )


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload


class _AsyncClient:
    instances: list["_AsyncClient"] = []
    responses: list[_Response] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.calls: list[dict[str, object]] = []
        self.instances.append(self)

    async def __aenter__(self) -> "_AsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_transport_enforces_kimi_request_and_discards_reasoning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    hidden = "synthetic hidden reasoning must disappear"
    payload: dict[str, Any] = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": '{"ok":true}',
                    "reasoning_content": hidden,
                },
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 17},
    }
    _AsyncClient.instances.clear()
    _AsyncClient.responses = [_Response(payload)]
    monkeypatch.setattr("app.runpod_kimi.httpx.AsyncClient", _AsyncClient)

    with caplog.at_level(logging.DEBUG):
        result = await _client().complete(
            system_instruction="Return JSON.",
            prompt="Synthetic input.",
            schema_name="synthetic",
            response_schema={"type": "object"},
        )

    assert result.content == '{"ok":true}'
    assert result.input_tokens == 9
    assert result.output_tokens == 17
    message = payload["choices"][0]["message"]
    assert "reasoning_content" not in message
    assert hidden not in caplog.text
    assert "synthetic-runpod-key-never-log" not in caplog.text

    call = _AsyncClient.instances[0].calls[0]
    assert call["url"] == f"{RUNPOD_KIMI_BASE_URL}/chat/completions"
    request = call["json"]
    assert isinstance(request, dict)
    assert request["model"] == "kimi-k3"
    assert request["temperature"] == 1
    assert request["max_tokens"] == 1024
    assert request["stream"] is False


@pytest.mark.asyncio
async def test_empty_length_response_is_incomplete_and_retried_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _AsyncClient.instances.clear()
    _AsyncClient.responses = [
        _Response(
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": ""},
                    }
                ]
            }
        ),
        _Response(
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": ""},
                    }
                ]
            }
        ),
    ]
    monkeypatch.setattr("app.runpod_kimi.httpx.AsyncClient", _AsyncClient)

    with pytest.raises(KimiProviderError) as raised:
        await _client().complete(
            system_instruction="Return JSON.",
            prompt="Synthetic input.",
            schema_name="synthetic",
            response_schema={"type": "object"},
        )

    assert raised.value.code == KimiErrorCode.INCOMPLETE_RESPONSE
    assert raised.value.retry_count == 1
    assert len(_AsyncClient.instances) == 2


@pytest.mark.asyncio
async def test_transport_retries_one_transient_failure_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    attempts = 0

    async def fail(**kwargs: object) -> KimiCompletion:
        nonlocal attempts
        del kwargs
        attempts += 1
        raise KimiProviderError(KimiErrorCode.TRANSIENT, transient=True)

    monkeypatch.setattr(client, "_complete_once", fail)
    with pytest.raises(KimiProviderError) as raised:
        await client.complete(
            system_instruction="Return JSON.",
            prompt="Synthetic input.",
            schema_name="synthetic",
            response_schema={"type": "object"},
        )

    assert attempts == 2
    assert raised.value.code == KimiErrorCode.TRANSIENT
    assert raised.value.retry_count == 1


@pytest.mark.asyncio
async def test_strict_content_validation_shares_the_same_two_call_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    attempts = 0
    validations = 0

    async def succeed(**kwargs: object) -> KimiCompletion:
        nonlocal attempts
        del kwargs
        attempts += 1
        return KimiCompletion(
            content='{ "ok": true }',
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            retry_count=0,
        )

    def validate(_: str) -> None:
        nonlocal validations
        validations += 1
        if validations == 1:
            raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE)

    monkeypatch.setattr(client, "_complete_once", succeed)
    completion = await client.complete(
        system_instruction="Return JSON.",
        prompt="Synthetic input.",
        schema_name="synthetic",
        response_schema={"type": "object"},
        content_validator=validate,
    )

    assert attempts == 2
    assert validations == 2
    assert completion.retry_count == 1


def _completion(content: dict[str, object]) -> KimiCompletion:
    return KimiCompletion(
        content=json.dumps(content),
        input_tokens=10,
        output_tokens=20,
        latency_ms=5,
        retry_count=0,
    )


def _install_completions(
    monkeypatch: pytest.MonkeyPatch,
    client: RunpodKimiClient,
    factory: Callable[[str], KimiCompletion],
) -> None:
    async def complete(**kwargs: object) -> KimiCompletion:
        schema_name = kwargs["schema_name"]
        assert isinstance(schema_name, str)
        completion = factory(schema_name)
        validator = kwargs.get("content_validator")
        if validator is not None:
            assert callable(validator)
            validator(completion.content)
        return completion

    monkeypatch.setattr(client, "complete", complete)


@pytest.mark.asyncio
async def test_perception_and_decision_apply_strict_pydantic_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()

    def result(schema_name: str) -> KimiCompletion:
        if schema_name == "perception_snapshot":
            return _completion(
                {
                    "mode": "user_query",
                    "intent": "financial_lookup",
                    "domain": "portfolio_documents",
                    "entities": {"financial_metrics": ["revenue"]},
                    "mentioned_scope_hints": {},
                    "result_requirement": "grounded_answer",
                    "required_evidence": ["financial_document"],
                    "required_capabilities": ["QUERY_DOCUMENTS"],
                    "ambiguities": [],
                    "risk_flags": [],
                    "evidence_status": "none",
                    "local_goal_status": "pending",
                    "global_goal_status": "pending",
                    "confidence": 0.9,
                    "reason_code": "QUERY_CLASSIFIED",
                    "clarification_question": None,
                    "rationale_summary": "Authorized evidence is required.",
                }
            )
        return _completion(
            {
                "plan": {
                    "version": 1,
                    "plan_text": ["Finalize from authorized evidence."],
                    "steps": [
                        {
                            "step_index": 0,
                            "action_type": "FINALIZE",
                            "action_name": None,
                            "status": "pending",
                            "reason_code": "EVIDENCE_READY",
                        }
                    ],
                    "change_reason_code": "PLAN_CREATED",
                },
                "next_action": {
                    "type": "FINALIZE",
                    "action_name": None,
                    "arguments": {},
                    "reason_code": "EVIDENCE_READY",
                },
                "replan": False,
            }
        )

    _install_completions(monkeypatch, client, result)
    perception = RunpodKimiPerceptionProvider(client=client)
    snapshot = await perception.perceive_user_query(query="What was revenue?")
    decision = await RunpodKimiDecisionProvider(client=client).decide_initial(
        query="What was revenue?",
        perception=snapshot,
        permitted_tool_catalog=(),
    )

    assert snapshot.reason_code == "QUERY_CLASSIFIED"
    assert decision.next_action.type == "FINALIZE"


@pytest.mark.asyncio
async def test_grounded_finalizer_rejects_extra_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    _install_completions(
        monkeypatch,
        client,
        lambda _: _completion(
            {
                "status": "supported",
                "claims": [{"text": "Supported.", "evidence_ids": ["ev_1"]}],
                "limitations": [],
                "reasoning_content": "must not be accepted",
            }
        ),
    )
    provider = RunpodKimiLLMProvider(client=client)
    request = GroundedGenerationRequest(
        question="What does the evidence say?",
        evidence=(
            GroundedEvidence(
                evidence_id="ev_1",
                chunk_id=uuid4(),
                document_id=uuid4(),
                document_version_id=uuid4(),
                version_number=1,
                document_title="synthetic.pdf",
                excerpt="Synthetic authorized evidence.",
                page_number=1,
                sheet_name=None,
                row_start=None,
                row_end=None,
                cell_start=None,
                cell_end=None,
            ),
        ),
    )

    with pytest.raises(LLMProviderError) as raised:
        await provider.generate(request)

    assert raised.value.code == LLMErrorCode.INVALID_RESPONSE


def test_runpod_settings_are_fixed_and_require_sufficient_output_budget() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        llm_provider="runpod",
        runpod_api_key=SecretStr("synthetic"),
        llm_max_output_tokens=1024,
    )
    assert settings.runpod_base_url == RUNPOD_KIMI_BASE_URL
    assert settings.runpod_model_name == "kimi-k3"

    with pytest.raises(ValidationError, match="at least 1024"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            llm_provider="runpod",
            runpod_api_key=SecretStr("synthetic"),
            llm_max_output_tokens=512,
        )
    with pytest.raises(ValidationError, match="approved Kimi endpoint"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            llm_provider="runpod",
            runpod_api_key=SecretStr("synthetic"),
            runpod_base_url="https://attacker.invalid/v1",
        )


def test_factories_select_runpod_for_all_three_model_stages() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        llm_provider="runpod",
        runpod_api_key=SecretStr("synthetic"),
        llm_max_output_tokens=1024,
    )

    perception, decision = create_agent_stage_providers(settings)
    finalizer = create_llm_provider(settings)

    assert isinstance(perception, RunpodKimiPerceptionProvider)
    assert isinstance(decision, RunpodKimiDecisionProvider)
    assert isinstance(finalizer, RunpodKimiLLMProvider)
