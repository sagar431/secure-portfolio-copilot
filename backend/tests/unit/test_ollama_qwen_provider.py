import logging
from typing import Any
from uuid import uuid4

import pytest

from app.chat.contracts import (
    GroundedEvidence,
    GroundedGenerationRequest,
    LLMErrorCode,
    LLMProviderError,
)
from app.chat.ollama import OllamaQwenLLMProvider
from app.ollama_qwen import QWEN_BASE_URL, QWEN_MODEL, OllamaQwenClient


class _Response:
    status_code = 200

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def json(self) -> object:
        return self.payload


class _AsyncClient:
    calls: list[dict[str, object]] = []
    payload: object

    def __init__(self, **kwargs: object) -> None:
        assert kwargs["trust_env"] is False

    async def __aenter__(self) -> "_AsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return _Response(self.payload)


def _request() -> GroundedGenerationRequest:
    return GroundedGenerationRequest(
        question="What was revenue?",
        evidence=(
            GroundedEvidence(
                evidence_id="ev_1",
                chunk_id=uuid4(),
                document_id=uuid4(),
                document_version_id=uuid4(),
                version_number=1,
                document_title="synthetic.pdf",
                excerpt="Authorized synthetic revenue evidence.",
                page_number=1,
                sheet_name=None,
                row_start=None,
                row_end=None,
                cell_start=None,
                cell_end=None,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_qwen_request_is_pinned_bounded_and_has_no_tools_or_reasoning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    hidden = "private hidden reasoning"
    payload: dict[str, Any] = {
        "message": {
            "role": "assistant",
            "content": (
                '{"status":"supported","claims":[{"text":"Revenue is supported.",'
                '"evidence_ids":["ev_1"]}],"limitations":[]}'
            ),
            "thinking": hidden,
        },
        "done": True,
        "prompt_eval_count": 10,
        "eval_count": 5,
    }
    _AsyncClient.calls.clear()
    _AsyncClient.payload = payload
    monkeypatch.setattr("app.ollama_qwen.httpx.AsyncClient", _AsyncClient)
    provider = OllamaQwenLLMProvider(
        client=OllamaQwenClient(
            base_url=QWEN_BASE_URL,
            model_name=QWEN_MODEL,
            timeout_seconds=2,
            max_output_tokens=512,
        )
    )

    with caplog.at_level(logging.DEBUG):
        generation = await provider.generate(_request())

    assert generation.answer.claims[0].evidence_ids == ("ev_1",)
    assert hidden not in caplog.text
    assert "thinking" not in payload["message"]
    call = _AsyncClient.calls[0]
    assert call["url"] == f"{QWEN_BASE_URL}/api/chat"
    body = call["json"]
    assert isinstance(body, dict)
    assert body["model"] == "qwen3:8b"
    assert body["stream"] is False
    assert body["think"] is False
    assert "tools" not in body
    assert body["options"] == {"temperature": 0, "num_predict": 512}


@pytest.mark.asyncio
async def test_visible_think_markup_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _AsyncClient.calls.clear()
    _AsyncClient.payload = {
        "message": {"content": "<think>secret</think>{}"},
        "done": True,
    }
    monkeypatch.setattr("app.ollama_qwen.httpx.AsyncClient", _AsyncClient)
    provider = OllamaQwenLLMProvider(
        client=OllamaQwenClient(
            base_url=QWEN_BASE_URL,
            model_name=QWEN_MODEL,
            timeout_seconds=2,
            max_output_tokens=512,
        )
    )

    with pytest.raises(LLMProviderError) as raised:
        await provider.generate(_request())

    assert getattr(raised.value, "code", None) == LLMErrorCode.INVALID_RESPONSE
