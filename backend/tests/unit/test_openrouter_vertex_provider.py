import json
import logging
from typing import Any

import pytest
from pydantic import ValidationError

from app.chat.structured_answer import AnswerSchema
from app.openrouter_vertex import (
    OPENROUTER_BASE_URL,
    OPENROUTER_HEAVY_MODEL,
    OPENROUTER_PROVIDER,
    OPENROUTER_SIMPLE_MODEL,
    OpenRouterErrorCode,
    OpenRouterProviderError,
    OpenRouterVertexClient,
)


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload


class _AsyncClient:
    queued: list[_Response | Exception] = []
    requests: list[dict[str, Any]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> "_AsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _Response:
        self.requests.append({"url": url, **kwargs, "client": self.kwargs})
        item = self.queued.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _payload(content: str, *, finish_reason: str = "stop") -> dict[str, object]:
    return {
        "id": "gen-safe-synthetic",
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {
                    "content": content,
                    "reasoning_details": [{"sensitive": "must-not-propagate"}],
                },
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        "provider": {"raw_body": "must-not-propagate"},
    }


def _client(*, model: str = OPENROUTER_SIMPLE_MODEL) -> OpenRouterVertexClient:
    return OpenRouterVertexClient(
        api_key="synthetic-openrouter-key-never-log",
        base_url=OPENROUTER_BASE_URL,
        provider=OPENROUTER_PROVIDER,
        model_name=model,
        timeout_seconds=30,
        max_output_tokens=1024,
    )


def _answer_validator(content: str) -> None:
    try:
        AnswerSchema.model_validate_json(content, strict=True)
    except (TypeError, ValueError, ValidationError):
        raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE) from None


@pytest.fixture(autouse=True)
def _reset_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    _AsyncClient.queued = []
    _AsyncClient.requests = []
    monkeypatch.setattr("app.openrouter_vertex.httpx.AsyncClient", _AsyncClient)


@pytest.mark.asyncio
async def test_request_forces_vertex_byok_without_tools_schema_or_reasoning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _AsyncClient.queued = [
        _Response(_payload('{"status":"insufficient_evidence","claims":[],"limitations":[]}'))
    ]

    completion = await _client().complete(
        system_instruction="Return JSON only.",
        prompt="synthetic",
        content_validator=_answer_validator,
    )

    assert completion.content.startswith("{")
    assert not hasattr(completion, "reasoning_details")
    assert "synthetic-openrouter-key-never-log" not in caplog.text
    assert len(_AsyncClient.requests) == 1
    captured = _AsyncClient.requests[0]
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    body = captured["json"]
    assert body["model"] == "google/gemini-3.1-flash-lite"
    assert body["provider"] == {
        "only": ["google-vertex"],
        "allow_fallbacks": False,
        "data_collection": "deny",
    }
    unsupported = {"tools", "tool_choice", "response_format", "reasoning", "reasoning_effort"}
    assert not (unsupported & body.keys())
    assert captured["client"]["trust_env"] is False


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"status":"insufficient_evidence","claims":[],"limitations":[]}\n```',
        '{"status":"insufficient_evidence","claims":[],"limitations":[],"extra":true}',
        '{"status":"supported","claims":[{"text":1,"evidence_ids":["ev_1"]}],"limitations":[]}',
        "{malformed",
    ],
)
@pytest.mark.asyncio
async def test_visible_json_validation_fails_closed(content: str) -> None:
    _AsyncClient.queued = [_Response(_payload(content))]

    with pytest.raises(OpenRouterProviderError) as raised:
        await _client().complete(
            system_instruction="Return JSON only.",
            prompt="synthetic",
            content_validator=_answer_validator,
            max_attempts=1,
        )

    assert raised.value.code == OpenRouterErrorCode.INVALID_RESPONSE
    assert len(_AsyncClient.requests) == 1


@pytest.mark.asyncio
async def test_retry_budget_is_at_most_two_total_calls() -> None:
    valid = '{"status":"insufficient_evidence","claims":[],"limitations":[]}'
    _AsyncClient.queued = [
        _Response(_payload("{malformed")),
        _Response(_payload(valid)),
        _Response(_payload(valid)),
    ]

    completion = await _client(model=OPENROUTER_HEAVY_MODEL).complete(
        system_instruction="Return JSON only.",
        prompt="synthetic",
        content_validator=_answer_validator,
        max_attempts=2,
    )

    assert completion.retry_count == 1
    assert len(_AsyncClient.requests) == 2
    assert len(_AsyncClient.queued) == 1


@pytest.mark.asyncio
async def test_two_invalid_responses_return_content_free_safe_error() -> None:
    _AsyncClient.queued = [
        _Response(_payload("{malformed")),
        _Response(_payload("{still-malformed")),
    ]

    with pytest.raises(OpenRouterProviderError) as raised:
        await _client(model=OPENROUTER_HEAVY_MODEL).complete(
            system_instruction="Return JSON only.",
            prompt="synthetic-sensitive-prompt",
            content_validator=_answer_validator,
            max_attempts=2,
        )

    assert raised.value.code == OpenRouterErrorCode.INVALID_RESPONSE
    assert raised.value.retry_count == 1
    assert "synthetic-sensitive-prompt" not in str(raised.value)
    assert len(_AsyncClient.requests) == 2


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"base_url": "https://attacker.invalid/v1"}, "base URL"),
        ({"provider": "google"}, "google-vertex"),
        ({"model_name": "arbitrary/model"}, "model"),
        ({"api_key": ""}, "API key"),
    ],
)
def test_client_rejects_unapproved_configuration(override: dict[str, str], message: str) -> None:
    values = {
        "api_key": "synthetic",
        "base_url": OPENROUTER_BASE_URL,
        "provider": OPENROUTER_PROVIDER,
        "model_name": OPENROUTER_SIMPLE_MODEL,
        "timeout_seconds": 30,
        "max_output_tokens": 1024,
    }
    values.update(override)
    with pytest.raises(ValueError, match=message):
        OpenRouterVertexClient(**values)  # type: ignore[arg-type]


def test_json_contract_itself_is_strict() -> None:
    valid = json.dumps(
        {
            "status": "supported",
            "claims": [{"text": "fact", "evidence_ids": ["ev_1"]}],
            "limitations": [],
        }
    )
    parsed = AnswerSchema.model_validate_json(valid, strict=True)
    assert parsed.claims[0].text == "fact"
