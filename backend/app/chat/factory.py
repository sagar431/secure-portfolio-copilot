from app.chat.contracts import (
    GroundedGenerationRequest,
    LLMErrorCode,
    LLMGeneration,
    LLMProvider,
    LLMProviderError,
)
from app.chat.fake import DeterministicFakeLLMProvider
from app.chat.gemini import GeminiLLMProvider
from app.chat.runpod import RunpodKimiLLMProvider
from app.core.config import Settings
from app.runpod_kimi import RunpodKimiClient


class DisabledLLMProvider:
    def __init__(self, model_name: str, error_code: LLMErrorCode = LLMErrorCode.DISABLED) -> None:
        self.model_name = model_name
        self.error_code = error_code

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration:
        del request
        raise LLMProviderError(self.error_code)


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        return DeterministicFakeLLMProvider()
    if settings.llm_provider == "disabled":
        return DisabledLLMProvider(settings.llm_model_name)
    if settings.llm_provider == "runpod":
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
    if settings.gemini_api_key is None:
        return DisabledLLMProvider(settings.llm_model_name, LLMErrorCode.UNAVAILABLE)
    return GeminiLLMProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        model_name=settings.llm_model_name,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
    )
