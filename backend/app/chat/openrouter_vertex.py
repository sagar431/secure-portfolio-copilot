from pydantic import ValidationError

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
from app.chat.structured_answer import AnswerSchema
from app.openrouter_vertex import (
    OpenRouterErrorCode,
    OpenRouterProviderError,
    OpenRouterVertexClient,
    json_contract_instruction,
)


class OpenRouterVertexLLMProvider:
    def __init__(self, *, client: OpenRouterVertexClient, max_attempts: int) -> None:
        if max_attempts not in {1, 2}:
            raise ValueError("Provider attempts must be one or two")
        self._client = client
        self._max_attempts = max_attempts

    @property
    def model_name(self) -> str:
        return self._client.model_name

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration:
        answer: AnswerSchema | None = None

        def validate_content(content: str) -> None:
            nonlocal answer
            try:
                answer = AnswerSchema.model_validate_json(content, strict=True)
            except (TypeError, ValueError, ValidationError):
                raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE) from None
            valid_ids = {item.evidence_id for item in request.evidence}
            supported = answer.status == "supported"
            if supported != bool(answer.claims):
                raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)
            if not supported and answer.claims:
                raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)
            if any(
                not claim.evidence_ids
                or len(set(claim.evidence_ids)) != len(claim.evidence_ids)
                or not set(claim.evidence_ids).issubset(valid_ids)
                for claim in answer.claims
            ):
                raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)

        try:
            completion = await self._client.complete(
                system_instruction=json_contract_instruction(
                    SYSTEM_INSTRUCTION, AnswerSchema.model_json_schema(mode="validation")
                ),
                prompt=build_grounded_prompt(request),
                content_validator=validate_content,
                max_attempts=self._max_attempts,
            )
        except OpenRouterProviderError as exc:
            if exc.code == OpenRouterErrorCode.TIMEOUT:
                code = LLMErrorCode.TIMEOUT
            elif exc.code == OpenRouterErrorCode.TRANSIENT:
                code = LLMErrorCode.TRANSIENT
            elif exc.code == OpenRouterErrorCode.REJECTED:
                code = LLMErrorCode.REJECTED
            elif exc.code in {
                OpenRouterErrorCode.INVALID_RESPONSE,
                OpenRouterErrorCode.INCOMPLETE_RESPONSE,
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
