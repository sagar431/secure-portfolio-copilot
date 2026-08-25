from app.chat.contracts import (
    GroundedGenerationRequest,
    LLMErrorCode,
    LLMGeneration,
    LLMProvider,
    LLMProviderError,
)
from app.chat.fake import DeterministicFakeLLMProvider
from app.chat.intent import IntentRouter, OpenRouterFuzzyIntentProvider
from app.chat.openrouter_vertex import OpenRouterVertexLLMProvider
from app.chat.router import DeterministicRoutingLLMProvider
from app.core.config import Settings
from app.memory.contracts import ConversationSummarizer, MemoryCandidateExtractor
from app.memory.extractor import (
    DeterministicFirstMemoryCandidateExtractor,
    DeterministicMemoryCandidateExtractor,
    OpenRouterMemoryCandidateExtractor,
)
from app.memory.summarizer import (
    DeterministicConversationSummarizer,
    OpenRouterConversationSummarizer,
)
from app.openrouter_vertex import OpenRouterVertexClient


class DisabledLLMProvider:
    def __init__(self, model_name: str, error_code: LLMErrorCode = LLMErrorCode.DISABLED) -> None:
        self.model_name = model_name
        self.error_code = error_code

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration:
        del request
        raise LLMProviderError(self.error_code)


def _client(settings: Settings, *, simple: bool) -> OpenRouterVertexClient | None:
    if settings.openrouter_api_key is None:
        return None
    return OpenRouterVertexClient(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        provider=settings.openrouter_provider,
        model_name=(
            settings.openrouter_simple_model if simple else settings.openrouter_heavy_model
        ),
        timeout_seconds=(
            settings.openrouter_simple_timeout_seconds
            if simple
            else settings.openrouter_heavy_timeout_seconds
        ),
        max_output_tokens=(
            settings.openrouter_simple_max_output_tokens
            if simple
            else settings.openrouter_heavy_max_output_tokens
        ),
    )


def _provider(settings: Settings, *, simple: bool, max_attempts: int) -> LLMProvider:
    client = _client(settings, simple=simple)
    model_name = settings.openrouter_simple_model if simple else settings.openrouter_heavy_model
    if client is None:
        return DisabledLLMProvider(model_name, LLMErrorCode.UNAVAILABLE)
    return OpenRouterVertexLLMProvider(client=client, max_attempts=max_attempts)


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return DeterministicFakeLLMProvider()
    if settings.llm_provider == "disabled":
        return DisabledLLMProvider(settings.openrouter_heavy_model)
    return DeterministicRoutingLLMProvider(
        simple=_provider(settings, simple=True, max_attempts=1),
        heavy=_provider(settings, simple=False, max_attempts=2),
        heavy_fallback=_provider(settings, simple=False, max_attempts=1),
        low_confidence_threshold=settings.router_low_confidence_threshold,
    )


def create_agent_finalizer(settings: Settings) -> LLMProvider:
    """Agentic finalization always uses the heavy model and never downgrades."""

    if settings.llm_provider in {"fake", "disabled"}:
        return create_llm_provider(settings)
    return _provider(settings, simple=False, max_attempts=2)


def create_memory_extractor(settings: Settings) -> MemoryCandidateExtractor:
    if settings.llm_provider in {"fake", "disabled"}:
        return DeterministicMemoryCandidateExtractor()
    client = _client(settings, simple=False)
    if client is None:
        return DeterministicMemoryCandidateExtractor(fail=True)
    return DeterministicFirstMemoryCandidateExtractor(OpenRouterMemoryCandidateExtractor(client))


def create_intent_router(settings: Settings) -> IntentRouter:
    """Use deterministic high-precision routes and a constrained economical model for fuzzy text."""

    if settings.llm_provider in {"fake", "disabled"}:
        return IntentRouter()
    client = _client(settings, simple=True)
    return (
        IntentRouter(OpenRouterFuzzyIntentProvider(client))
        if client is not None
        else IntentRouter()
    )


def create_conversation_summarizer(settings: Settings) -> ConversationSummarizer:
    if settings.llm_provider in {"fake", "disabled"}:
        return DeterministicConversationSummarizer()
    client = _client(settings, simple=True)
    return (
        OpenRouterConversationSummarizer(client)
        if client is not None
        else DeterministicConversationSummarizer()
    )
