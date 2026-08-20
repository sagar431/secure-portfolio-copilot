"""Bounded embedding provider adapters."""

from app.embeddings.contracts import EmbeddingProvider, EmbeddingProviderError
from app.embeddings.fake import DeterministicFakeEmbeddingProvider

__all__ = [
    "DeterministicFakeEmbeddingProvider",
    "EmbeddingProvider",
    "EmbeddingProviderError",
]
