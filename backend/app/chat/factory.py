from app.chat.contracts import (
    GroundedGenerationRequest,
    LLMErrorCode,
    LLMGeneration,
    LLMProvider,
    LLMProviderError,
)
from app.chat.fake import DeterministicFakeLLMProvider
from app.chat.gemini import GeminiLLMProvider
from app.chat.ollama import OllamaQwenLLMProvider
from app.chat.router import DeterministicRoutingLLMProvider
from app.chat.runpod import RunpodKimiLLMProvider
from app.core.config import Settings
from app.ollama_qwen import OllamaQwenClient
from app.runpod_kimi import RunpodKimiClient


class DisabledLLMProvider:
    def __init__(self, model_name: str, error_code: LLMErrorCode = LLMErrorCode.DISABLED) -> None:
        self.model_name = model_name
        self.error_code = error_code

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration:
        del request
        raise LLMProviderError(self.error_code)


def create_kimi_llm_provider(settings: Settings) -> LLMProvider:
    if settings.runpod_api_key is None:
        return DisabledLLMProvider(settings.runpod_model_name, LLMErrorCode.UNAVAILABLE)
    return RunpodKimiLLMProvider(
        client=RunpodKimiClient(
            api_key=settings.runpod_api_key.get_secret_value(),
            base_url=settings.runpod_base_url,
            model_name=settings.runpod_model_name,
            timeout_seconds=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
        )
    )


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return DeterministicFakeLLMProvider()
    if settings.llm_provider == "disabled":
        return DisabledLLMProvider(settings.llm_model_name)
    if settings.llm_provider == "router":
        return DeterministicRoutingLLMProvider(
            qwen=OllamaQwenLLMProvider(
                client=OllamaQwenClient(
                    base_url=settings.qwen_base_url,
                    model_name=settings.qwen_model_name,
                    timeout_seconds=settings.qwen_timeout_seconds,
                    max_output_tokens=settings.qwen_max_output_tokens,
                )
            ),
            kimi=create_kimi_llm_provider(settings),
            low_confidence_threshold=settings.router_low_confidence_threshold,
        )
    if settings.llm_provider == "runpod":
        return create_kimi_llm_provider(settings)
    if settings.gemini_api_key is None:
        return DisabledLLMProvider(settings.llm_model_name, LLMErrorCode.UNAVAILABLE)
    return GeminiLLMProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model_name=settings.llm_model_name,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )


def create_agent_finalizer(settings: Settings) -> LLMProvider:
    """Agentic work is always strong-routed; it never downgrades to Qwen."""

    if settings.llm_provider == "router":
        return create_kimi_llm_provider(settings)
    return create_llm_provider(settings)
