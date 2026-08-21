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
from app.chat.structured_answer import ANSWER_SCHEMA, AnswerSchema
from app.ollama_qwen import OllamaQwenClient, QwenErrorCode, QwenProviderError


class OllamaQwenLLMProvider:
    def __init__(self, *, client: OllamaQwenClient) -> None:
        self._client = client

    @property
    def model_name(self) -> str:
        return self._client.model_name

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration:
        try:
            completion = await self._client.complete(
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=build_grounded_prompt(request),
                response_schema=ANSWER_SCHEMA,
            )
            answer = AnswerSchema.model_validate_json(completion.content, strict=True)
        except QwenProviderError as exc:
            mapping = {
                QwenErrorCode.TIMEOUT: LLMErrorCode.TIMEOUT,
                QwenErrorCode.TRANSIENT: LLMErrorCode.TRANSIENT,
                QwenErrorCode.REJECTED: LLMErrorCode.REJECTED,
                QwenErrorCode.INVALID_RESPONSE: LLMErrorCode.INVALID_RESPONSE,
                QwenErrorCode.UNAVAILABLE: LLMErrorCode.UNAVAILABLE,
            }
            raise LLMProviderError(mapping[exc.code], transient=exc.transient) from None
        except (TypeError, ValueError, ValidationError):
            raise LLMProviderError(LLMErrorCode.INVALID_RESPONSE) from None
        return LLMGeneration(
            answer=GroundedAnswerDraft(
                status=answer.status,
                claims=tuple(
                    GroundedClaimDraft(text=item.text, evidence_ids=tuple(item.evidence_ids))
                    for item in answer.claims
                ),
                limitations=tuple(answer.limitations),
            ),
            usage=LLMUsage(
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                latency_ms=completion.latency_ms,
            ),
        )
