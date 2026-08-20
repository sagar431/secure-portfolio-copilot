import asyncio
import time
from typing import Literal

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.chat.contracts import (
    GroundedAnswerDraft,
    GroundedClaimDraft,
    GroundedGenerationRequest,
    LLMErrorCode,
    LLMGeneration,
    LLMProviderError,
    LLMUsage,
)
from app.chat.prompt import SYSTEM_INSTRUCTION, build_grounded_prompt


class _ClaimSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


class _AnswerSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["supported", "insufficient_evidence"]
    claims: list[_ClaimSchema] = Field(max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=5)


# Gemini's accepted JSON-schema subset does not support every keyword emitted by Pydantic.
# Keep the wire schema intentionally small, then apply the stricter Pydantic model locally.
_PROVIDER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["supported", "insufficient_evidence"],
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["text", "evidence_ids"],
            },
        },
        "limitations": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["status", "claims", "limitations"],
}


class GeminiLLMProvider:
    """Official Google GenAI adapter with no tool-capable features configured."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: float,
        max_output_tokens: int,
    ) -> None:
        self._api_key = api_key
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens

    @property
    def model_name(self) -> str:
        return self._model_name

    async def _generate_once(self, request: GroundedGenerationRequest) -> LLMGeneration:
        started = time.monotonic()
        client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(
                timeout=int(self._timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await client.aio.models.generate_content(
                    model=self._model_name,
                    contents=build_grounded_prompt(request),
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0,
                        candidate_count=1,
                        max_output_tokens=self._max_output_tokens,
                        response_mime_type="application/json",
                        response_schema=_PROVIDER_RESPONSE_SCHEMA,
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.MEDIUM,
                            include_thoughts=False,
                        ),
                    ),
                )
        finally:
            await client.aio.aclose()
        parsed = response.parsed
        if isinstance(parsed, _AnswerSchema):
            answer = parsed
        else:
            answer = _AnswerSchema.model_validate(parsed)
        usage = response.usage_metadata
        return LLMGeneration(
            answer=GroundedAnswerDraft(
                status=answer.status,
                claims=tuple(
                    GroundedClaimDraft(
                        text=item.text,
                        evidence_ids=tuple(item.evidence_ids),
                    )
                    for item in answer.claims
                ),
                limitations=tuple(answer.limitations),
            ),
            usage=LLMUsage(
                input_tokens=usage.prompt_token_count if usage is not None else None,
                output_tokens=usage.candidates_token_count if usage is not None else None,
                latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            ),
        )

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration:
        for attempt in range(2):
            try:
                generation = await self._generate_once(request)
                if attempt:
                    return LLMGeneration(
                        answer=generation.answer,
                        usage=LLMUsage(
                            input_tokens=generation.usage.input_tokens,
                            output_tokens=generation.usage.output_tokens,
                            latency_ms=generation.usage.latency_ms,
                            retry_count=attempt,
                        ),
                    )
                return generation
            except TimeoutError:
                error = LLMProviderError(LLMErrorCode.TIMEOUT, transient=True)
            except LLMProviderError as exc:
                error = exc
            except errors.APIError as exc:
                transient = exc.code in {408, 429} or exc.code >= 500
                error = LLMProviderError(
                    LLMErrorCode.TRANSIENT if transient else LLMErrorCode.REJECTED,
                    transient=transient,
                )
            except (TypeError, ValueError, ValidationError):
                error = LLMProviderError(LLMErrorCode.INVALID_RESPONSE)
            except Exception:
                error = LLMProviderError(LLMErrorCode.UNAVAILABLE)
            if not error.transient or attempt == 1:
                raise LLMProviderError(
                    error.code,
                    transient=error.transient,
                    retry_count=attempt,
                ) from None
        raise LLMProviderError(LLMErrorCode.UNAVAILABLE)
