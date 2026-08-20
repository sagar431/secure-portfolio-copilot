import hashlib
import math
import re

from app.embeddings.contracts import EmbeddingModel, EmbeddingProviderError

_TOKEN = re.compile(r"[a-z0-9]+")


class DeterministicFakeEmbeddingProvider:
    """Local token-hash embeddings for deterministic automated tests only."""

    def __init__(
        self,
        *,
        dimensions: int = 768,
        model_name: str = "nomic-embed-text",
        model_version: str = "v1.5",
    ) -> None:
        self._model = EmbeddingModel(model_name, model_version, dimensions)

    @property
    def model(self) -> EmbeddingModel:
        return self._model

    async def ensure_ready(self) -> None:
        if self._model.dimensions <= 0:
            raise EmbeddingProviderError("INVALID_DIMENSIONS")

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            values = [0.0] * self._model.dimensions
            for token in _TOKEN.findall(text.casefold()):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self._model.dimensions
                values[index] += -1.0 if digest[4] & 1 else 1.0
            norm = math.sqrt(sum(value * value for value in values))
            if not norm:
                digest = hashlib.sha256(text.encode("utf-8")).digest()
                values[int.from_bytes(digest[:4], "big") % self._model.dimensions] = 1.0
                norm = 1.0
            values = [value / norm for value in values]
            vectors.append(tuple(values))
        return tuple(vectors)
