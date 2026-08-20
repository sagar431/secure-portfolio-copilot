import math
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.embeddings.contracts import EmbeddingModel, EmbeddingProviderError


class OllamaEmbeddingProvider:
    """Strict Ollama adapter for the configured model; never substitutes a model."""

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        model_version: str,
        dimensions: int,
        timeout_seconds: float,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_ref = f"{model_name}:{model_version}"
        self._model = EmbeddingModel(model_name, model_version, dimensions)
        self._timeout = timeout_seconds

    @property
    def model(self) -> EmbeddingModel:
        return self._model

    async def _request(self, operation: Callable[[], Awaitable[httpx.Response]]) -> httpx.Response:
        for attempt in range(2):
            try:
                response = await operation()
                if response.status_code >= 500:
                    raise EmbeddingProviderError("PROVIDER_TRANSIENT", transient=True)
                if response.status_code >= 400:
                    raise EmbeddingProviderError("PROVIDER_REJECTED")
                return response
            except (TimeoutError, httpx.TransportError):
                error = EmbeddingProviderError("PROVIDER_TRANSIENT", transient=True)
            except EmbeddingProviderError as exc:
                error = exc
            if not error.transient or attempt == 1:
                raise error from None
        raise EmbeddingProviderError("PROVIDER_UNAVAILABLE")

    async def ensure_ready(self) -> None:
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            response = await self._request(lambda: client.get(f"{self._base_url}/api/tags"))
            try:
                payload: Any = response.json()
                available = {
                    str(item.get("name"))
                    for item in payload.get("models", [])
                    if isinstance(item, dict)
                }
            except (TypeError, ValueError, AttributeError):
                raise EmbeddingProviderError("INVALID_PROVIDER_RESPONSE") from None
            if self._model_ref not in available:
                pulled = await self._request(
                    lambda: client.post(
                        f"{self._base_url}/api/pull",
                        json={"model": self._model_ref, "stream": False},
                    )
                )
                try:
                    pull_payload: Any = pulled.json()
                    if pull_payload.get("status") != "success":
                        raise EmbeddingProviderError("MODEL_UNAVAILABLE")
                except (TypeError, ValueError, AttributeError):
                    raise EmbeddingProviderError("INVALID_PROVIDER_RESPONSE") from None
                refreshed = await self._request(lambda: client.get(f"{self._base_url}/api/tags"))
                try:
                    refreshed_payload: Any = refreshed.json()
                    refreshed_names = {
                        str(item.get("name"))
                        for item in refreshed_payload.get("models", [])
                        if isinstance(item, dict)
                    }
                except (TypeError, ValueError, AttributeError):
                    raise EmbeddingProviderError("INVALID_PROVIDER_RESPONSE") from None
                if self._model_ref not in refreshed_names:
                    raise EmbeddingProviderError("MODEL_UNAVAILABLE")

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            response = await self._request(
                lambda: client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model_ref, "input": list(texts)},
                )
            )
        try:
            payload: Any = response.json()
            raw_vectors = payload["embeddings"]
            vectors = tuple(tuple(float(value) for value in vector) for vector in raw_vectors)
        except (KeyError, TypeError, ValueError):
            raise EmbeddingProviderError("INVALID_PROVIDER_RESPONSE") from None
        if len(vectors) != len(texts) or any(
            len(vector) != self._model.dimensions for vector in vectors
        ):
            raise EmbeddingProviderError("DIMENSION_MISMATCH")
        if any(
            not all(math.isfinite(value) for value in vector)
            or math.sqrt(sum(value * value for value in vector)) == 0
            for vector in vectors
        ):
            raise EmbeddingProviderError("INVALID_VECTOR")
        return vectors
