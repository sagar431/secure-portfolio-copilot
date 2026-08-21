from typing import Literal

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
from app.runpod_kimi import KimiErrorCode, KimiProviderError, RunpodKimiClient


class _ClaimSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


class _AnswerSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["supported", "insufficient_evidence"]
    claims: list[_ClaimSchema] = Field(max_length=8)
    limitations: list[str] = Field(max_length=5)


_ANSWER_SCHEMA = _AnswerSchema.model_json_schema(mode="validation")


class RunpodKimiLLMProvider:
    def __init__(self, *, client: RunpodKimiClient) -> None:
        self._client = client

    @property
    def model_name(self) -> str:
        return self._client.model_name

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration:
        answer: _AnswerSchema | None = None

        def validate_content(content: str) -> None:
            nonlocal answer
            try:
                answer = _AnswerSchema.model_validate_json(content, strict=True)
            except (TypeError, ValueError, ValidationError):
                raise KimiProviderError(KimiErrorCode.INVALID_RESPONSE) from None

        try:
            completion = await self._client.complete(
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=build_grounded_prompt(request),
                schema_name="grounded_answer",
                response_schema=_ANSWER_SCHEMA,
                content_validator=validate_content,
            )
        except KimiProviderError as exc:
            if exc.code == KimiErrorCode.TIMEOUT:
                code = LLMErrorCode.TIMEOUT
            elif exc.code == KimiErrorCode.TRANSIENT:
                code = LLMErrorCode.TRANSIENT
            elif exc.code == KimiErrorCode.REJECTED:
                code = LLMErrorCode.REJECTED
            elif exc.code in {
                KimiErrorCode.INVALID_RESPONSE,
                KimiErrorCode.INCOMPLETE_RESPONSE,
            }:
                code = LLMErrorCode.INVALID_RESPONSE
            else:
                code = LLMErrorCode.UNAVAILABLE
            raise LLMProviderError(
                code,
                transient=exc.transient,
                retry_count=exc.retry_count,
            ) from None
        if answer is None:
            raise LLMProviderError(LLMErrorCode.INVALID_RESPONSE)

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
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                latency_ms=completion.latency_ms,
                retry_count=completion.retry_count,
            ),
        )
