import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import httpx

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_PROVIDER = "google-vertex"
OPENROUTER_SIMPLE_MODEL = "google/gemini-3.1-flash-lite"
OPENROUTER_HEAVY_MODEL = "google/gemini-3.7-flash"
OPENROUTER_MODELS = frozenset({OPENROUTER_SIMPLE_MODEL, OPENROUTER_HEAVY_MODEL})


def json_contract_instruction(system_instruction: str, response_schema: dict[str, object]) -> str:
    """Put schema guidance in prompt text without unsupported wire parameters."""

    return (
        f"{system_instruction}\nThe following JSON Schema is the exact output contract. "
        "Return one instance and no other text:\n"
        + json.dumps(response_schema, ensure_ascii=True, separators=(",", ":"))
    )


class OpenRouterErrorCode(StrEnum):
    TIMEOUT = "TIMEOUT"
    TRANSIENT = "TRANSIENT"
    REJECTED = "REJECTED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    UNAVAILABLE = "UNAVAILABLE"


class OpenRouterProviderError(RuntimeError):
    """Content-free provider failure safe to map at application boundaries."""

    def __init__(
        self,
        code: OpenRouterErrorCode,
        *,
        transient: bool = False,
        retry_count: int = 0,
    ) -> None:
        super().__init__("OpenRouter Vertex provider failed safely.")
        self.code = code
        self.transient = transient
        self.retry_count = retry_count


@dataclass(frozen=True, slots=True)
class OpenRouterCompletion:
    content: str
    generation_id: str | None
    finish_reason: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    retry_count: int


def _optional_non_negative_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)
    return value


def _extract_completion(payload: object, *, latency_ms: int) -> OpenRouterCompletion:
    if not isinstance(payload, dict):
        raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)
    generation_id = payload.get("id")
    if generation_id is not None and not isinstance(generation_id, str):
        raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)
    choice = choices[0]
    if not isinstance(choice, dict):
        raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)
    finish_reason = choice.get("finish_reason")
    if not isinstance(finish_reason, str):
        raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)
    message = choice.get("message")
    if not isinstance(message, dict):
        raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)

    # Read only visible content. Hidden reasoning/provider fields are deliberately
    # neither copied nor returned from this trust boundary.
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        code = (
            OpenRouterErrorCode.INCOMPLETE_RESPONSE
            if finish_reason == "length"
            else OpenRouterErrorCode.INVALID_RESPONSE
        )
        raise OpenRouterProviderError(code)
    if finish_reason == "length":
        raise OpenRouterProviderError(OpenRouterErrorCode.INCOMPLETE_RESPONSE)

    usage = payload.get("usage")
    if usage is None:
        input_tokens = None
        output_tokens = None
    elif isinstance(usage, dict):
        input_tokens = _optional_non_negative_int(usage.get("prompt_tokens"))
        output_tokens = _optional_non_negative_int(usage.get("completion_tokens"))
    else:
        raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)

    return OpenRouterCompletion(
        content=content,
        generation_id=generation_id,
        finish_reason=finish_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        retry_count=0,
    )


class OpenRouterVertexClient:
    """Pinned OpenRouter client that permits only Google Vertex BYOK routing."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        provider: str,
        model_name: str,
        timeout_seconds: float,
        max_output_tokens: int,
    ) -> None:
        if base_url != OPENROUTER_BASE_URL:
            raise ValueError("OpenRouter base URL is not approved")
        if provider != OPENROUTER_PROVIDER:
            raise ValueError("OpenRouter provider must be google-vertex")
        if model_name not in OPENROUTER_MODELS:
            raise ValueError("OpenRouter model is not approved")
        if not api_key:
            raise ValueError("OpenRouter API key is required")
        self._api_key = api_key
        self.base_url = base_url
        self.provider = provider
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    async def _complete_once(
        self,
        *,
        system_instruction: str,
        prompt: str,
    ) -> OpenRouterCompletion:
        started = time.monotonic()
        request = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
            "stream": False,
            "provider": {
                "only": [OPENROUTER_PROVIDER],
                "allow_fallbacks": False,
                "data_collection": "deny",
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
            raise OpenRouterProviderError(OpenRouterErrorCode.TIMEOUT, transient=True) from None
        except httpx.HTTPError:
            raise OpenRouterProviderError(OpenRouterErrorCode.UNAVAILABLE, transient=True) from None

        if response.status_code >= 400:
            transient = response.status_code in {408, 429} or response.status_code >= 500
            raise OpenRouterProviderError(
                OpenRouterErrorCode.TRANSIENT if transient else OpenRouterErrorCode.REJECTED,
                transient=transient,
            ) from None
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE) from None
        return _extract_completion(
            payload,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    async def complete(
        self,
        *,
        system_instruction: str,
        prompt: str,
        content_validator: Callable[[str], None],
        max_attempts: int = 2,
    ) -> OpenRouterCompletion:
        if max_attempts not in {1, 2}:
            raise ValueError("Provider attempts must be one or two")
        for attempt in range(max_attempts):
            try:
                completion = await self._complete_once(
                    system_instruction=system_instruction,
                    prompt=prompt,
                )
                content_validator(completion.content)
                if attempt == 0:
                    return completion
                return OpenRouterCompletion(
                    content=completion.content,
                    generation_id=completion.generation_id,
                    finish_reason=completion.finish_reason,
                    input_tokens=completion.input_tokens,
                    output_tokens=completion.output_tokens,
                    latency_ms=completion.latency_ms,
                    retry_count=attempt,
                )
            except OpenRouterProviderError as exc:
                retryable = exc.transient or exc.code in {
                    OpenRouterErrorCode.INVALID_RESPONSE,
                    OpenRouterErrorCode.INCOMPLETE_RESPONSE,
                }
                if not retryable or attempt + 1 >= max_attempts:
                    raise OpenRouterProviderError(
                        exc.code,
                        transient=exc.transient,
                        retry_count=attempt,
                    ) from None
        raise OpenRouterProviderError(OpenRouterErrorCode.UNAVAILABLE)
