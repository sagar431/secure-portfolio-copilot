from app.core.config import Settings
from app.embeddings.contracts import EmbeddingModel, EmbeddingProvider, EmbeddingProviderError
from app.embeddings.fake import DeterministicFakeEmbeddingProvider
from app.embeddings.ollama import OllamaEmbeddingProvider


class DisabledEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        self._model = EmbeddingModel(
            settings.embedding_model_name,
            settings.embedding_model_version,
            settings.embedding_dimensions,
        )

    @property
    def model(self) -> EmbeddingModel:
        return self._model

    async def ensure_ready(self) -> None:
        raise EmbeddingProviderError("PROVIDER_DISABLED")

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        raise EmbeddingProviderError("PROVIDER_DISABLED")


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "disabled":
        return DisabledEmbeddingProvider(settings)
    if settings.embedding_provider == "fake":
        return DeterministicFakeEmbeddingProvider(
            dimensions=settings.embedding_dimensions,
            model_name=settings.embedding_model_name,
            model_version=settings.embedding_model_version,
        )
    return OllamaEmbeddingProvider(
        base_url=settings.ollama_base_url,
        model_name=settings.embedding_model_name,
        model_version=settings.embedding_model_version,
        dimensions=settings.embedding_dimensions,
        timeout_seconds=settings.embedding_timeout_seconds,
    )
