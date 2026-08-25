from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.memory.contracts import ConversationSummarizer, ConversationSummaryRequest
from app.memory.prompts import (
    CONVERSATION_SUMMARY_SYSTEM_INSTRUCTION,
    conversation_summary_prompt,
)
from app.openrouter_vertex import (
    OpenRouterErrorCode,
    OpenRouterProviderError,
    OpenRouterVertexClient,
    json_contract_instruction,
)


class ConversationSummarySchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    summary: str = Field(min_length=1, max_length=1000)


class DeterministicConversationSummarizer:
    """Bounded test summarizer that preserves recent goals without transcript growth."""

    async def summarize(self, request: ConversationSummaryRequest) -> str:
        items: list[str] = []
        if request.previous_summary:
            items.append(f"Earlier context: {' '.join(request.previous_summary.split())[:300]}")
        for role, content in request.messages[-6:]:
            label = "User goal" if role == "user" else "Safe outcome"
            items.append(f"{label}: {' '.join(content.split())[:180]}")
        return " ".join(items)[:1000]


class OpenRouterConversationSummarizer:
    def __init__(self, client: OpenRouterVertexClient) -> None:
        self._client = client

    async def summarize(self, request: ConversationSummaryRequest) -> str:
        parsed: ConversationSummarySchema | None = None

        def validate(content: str) -> None:
            nonlocal parsed
            try:
                parsed = ConversationSummarySchema.model_validate_json(content, strict=True)
            except (TypeError, ValueError, ValidationError):
                raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE) from None

        await self._client.complete(
            system_instruction=json_contract_instruction(
                CONVERSATION_SUMMARY_SYSTEM_INSTRUCTION,
                ConversationSummarySchema.model_json_schema(mode="validation"),
            ),
            prompt=conversation_summary_prompt(
                request.messages,
                previous_summary=request.previous_summary,
            ),
            content_validator=validate,
            max_attempts=1,
        )
        if parsed is None:
            raise OpenRouterProviderError(OpenRouterErrorCode.INVALID_RESPONSE)
        return " ".join(parsed.summary.split())[:1000]


__all__ = [
    "ConversationSummarizer",
    "DeterministicConversationSummarizer",
    "OpenRouterConversationSummarizer",
]
