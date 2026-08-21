import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import httpx

RUNPOD_KIMI_BASE_URL = "https://api.runpod.ai/v2/moonshot-kimi/openai/v1"
RUNPOD_KIMI_MODEL = "kimi-k3"
RUNPOD_KIMI_TEMPERATURE = 1
RUNPOD_KIMI_MIN_OUTPUT_TOKENS = 1024


class KimiErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    TRANSIENT = "TRANSIENT"
    REJECTED = "REJECTED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    UNAVAILABLE = "UNAVAILABLE"


class KimiProviderError(RuntimeError):
    """Content-free Kimi failure that is safe to map at a caller boundary."""

    def __init__(
        self,
        code: KimiErrorCode,
        *,
        transient: bool = False,
        retry_count: int = 0,
    ) -> None:
        super().__init__("Runpod Kimi provider failed safely.")
        self.code = code
        self.transient = transient
        self.retry_count = retry_count


@dataclass(frozen=True, slots=True)
class KimiCompletion:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    retry_count: int


def _optional_non_negative_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE)
    return value


def _extract_completion(payload: object, *, latency_ms: int) -> KimiCompletion:
    if not isinstance(payload, dict):
        raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE)
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE)
    choice = choices[0]
    if not isinstance(choice, dict):
        raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE)
    finish_reason = choice.get("finish_reason")
    if not isinstance(finish_reason, str):
        raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE)
    message = choice.get("message")
    if not isinstance(message, dict):
        raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE)

    # Kimi may return hidden reasoning beside the visible answer. Delete it at the
    # provider boundary before validation and never propagate, persist, or log it.
    if "reasoning_content" in message:
        del message["reasoning_content"]

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        code = (
            KimiErrorCode.INCOMPLETE_RESPONSE
            if finish_reason == "length"
            else KimiErrorCode.INVALID_RESPONSE
        )
        raise KimiProviderError(code)

    usage = payload.get("usage")
    if usage is None:
        input_tokens = None
        output_tokens = None
    elif isinstance(usage, dict):
        input_tokens = _optional_non_negative_int(usage.get("prompt_tokens"))
        output_tokens = _optional_non_negative_int(usage.get("completion_tokens"))
    else:
        raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE)

    return KimiCompletion(
        content=content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        retry_count=0,
    )


class RunpodKimiClient:
    """Minimal OpenAI-compatible client with one bounded application retry."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        max_output_tokens: int,
    ) -> None:
        if base_url != RUNPOD_KIMI_BASE_URL:
            raise ValueError("Runpod Kimi base URL is not approved")
        if model_name != RUNPOD_KIMI_MODEL:
            raise ValueError("Runpod Kimi model is not approved")
        if max_output_tokens < RUNPOD_KIMI_MIN_OUTPUT_TOKENS:
            raise ValueError("Runpod Kimi requires at least 1024 output tokens")
        self._api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    async def _complete_once(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema_name: str,
        response_schema: dict[str, object],
    ) -> KimiCompletion:
        started = time.monotonic()
        request = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": RUNPOD_KIMI_TEMPERATURE,
            "max_tokens": self.max_output_tokens,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": False,
                    "schema": response_schema,
                },
            },
        }
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout_seconds),
                    trust_env=False,
                ) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=request,
                    )
        except (TimeoutError, httpx.TimeoutException):
            raise KimiProviderError(KimiErrorCode.TIMEOUT, transient=True) from None
        except httpx.HTTPError:
            raise KimiProviderError(KimiErrorCode.UNAVAILABLE) from None

        if response.status_code >= 400:
            transient = response.status_code in {408, 429} or response.status_code >= 500
            raise KimiProviderError(
                KimiErrorCode.TRANSIENT if transient else KimiErrorCode.REJECTED,
                transient=transient,
            ) from None
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE) from None
        return _extract_completion(
            payload,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    async def complete(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema_name: str,
        response_schema: dict[str, object],
        content_validator: Callable[[str], None] | None = None,
    ) -> KimiCompletion:
        for attempt in range(2):
            try:
                completion = await self._complete_once(
                    system_instruction=system_instruction,
                    prompt=prompt,
                    schema_name=schema_name,
                    response_schema=response_schema,
                )
                if content_validator is not None:
                    content_validator(completion.content)
                if attempt == 0:
                    return completion
                return KimiCompletion(
                    content=completion.content,
                    input_tokens=completion.input_tokens,
                    output_tokens=completion.output_tokens,
                    latency_ms=completion.latency_ms,
                    retry_count=attempt,
                )
            except KimiProviderError as exc:
                retryable = exc.transient or exc.code in {
                    KimiErrorCode.INVALID_RESPONSE,
                    KimiErrorCode.INCOMPLETE_RESPONSE,
                }
                if not retryable or attempt == 1:
                    raise KimiProviderError(
                        exc.code,
                        transient=exc.transient,
                        retry_count=attempt,
                    ) from None
        raise KimiProviderError(KimiErrorCode.UNAVAILABLE)
