import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum

import httpx

QWEN_BASE_URL = "http://192.168.31.213:11434"
QWEN_MODEL = "qwen3:8b"


class QwenErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    TRANSIENT = "TRANSIENT"
    REJECTED = "REJECTED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNAVAILABLE = "UNAVAILABLE"


class QwenProviderError(RuntimeError):
    def __init__(self, code: QwenErrorCode, *, transient: bool = False) -> None:
        super().__init__("Mac Qwen provider failed safely.")
        self.code = code
        self.transient = transient


@dataclass(frozen=True, slots=True)
class QwenCompletion:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


def _optional_count(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QwenProviderError(QwenErrorCode.INVALID_RESPONSE)
    return value


class OllamaQwenClient:
    """Pinned development-only Qwen client. It has no tool capability or retry layer."""

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        max_output_tokens: int,
    ) -> None:
        if base_url != QWEN_BASE_URL:
            raise ValueError("Qwen base URL is not approved")
        if model_name != QWEN_MODEL:
            raise ValueError("Qwen model is not approved")
        self.base_url = base_url
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    async def complete(
        self,
        *,
        system_instruction: str,
        prompt: str,
        response_schema: dict[str, object],
    ) -> QwenCompletion:
        started = time.monotonic()
        request = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "format": response_schema,
            "options": {"temperature": 0, "num_predict": self.max_output_tokens},
        }
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout_seconds), trust_env=False
                ) as client:
                    response = await client.post(f"{self.base_url}/api/chat", json=request)
        except (TimeoutError, httpx.TimeoutException):
            raise QwenProviderError(QwenErrorCode.TIMEOUT, transient=True) from None
        except httpx.HTTPError:
            raise QwenProviderError(QwenErrorCode.UNAVAILABLE) from None
        if response.status_code >= 400:
            transient = response.status_code in {408, 429} or response.status_code >= 500
            raise QwenProviderError(
                QwenErrorCode.TRANSIENT if transient else QwenErrorCode.REJECTED,
                transient=transient,
            ) from None
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise QwenProviderError(QwenErrorCode.INVALID_RESPONSE) from None
        if not isinstance(payload, dict) or payload.get("done") is not True:
            raise QwenProviderError(QwenErrorCode.INVALID_RESPONSE)
        message = payload.get("message")
        if not isinstance(message, dict):
            raise QwenProviderError(QwenErrorCode.INVALID_RESPONSE)
        # Never propagate model reasoning, even if a server ignores think=false.
        message.pop("thinking", None)
        message.pop("reasoning_content", None)
        content = message.get("content")
        if (
            not isinstance(content, str)
            or not content.strip()
            or "<think" in content.lower()
            or "</think>" in content.lower()
        ):
            raise QwenProviderError(QwenErrorCode.INVALID_RESPONSE)
        return QwenCompletion(
            content=content,
            input_tokens=_optional_count(payload.get("prompt_eval_count")),
            output_tokens=_optional_count(payload.get("eval_count")),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
