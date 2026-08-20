from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EmbeddingModel:
    name: str
    version: str
    dimensions: int


class EmbeddingErrorCode(StrEnum):
    INVALID_DIMENSIONS = "INVALID_DIMENSIONS"
    PROVIDER_TRANSIENT = "PROVIDER_TRANSIENT"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INVALID_PROVIDER_RESPONSE = "INVALID_PROVIDER_RESPONSE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    DIMENSION_MISMATCH = "DIMENSION_MISMATCH"
    INVALID_VECTOR = "INVALID_VECTOR"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    CHUNK_LIMIT_EXCEEDED = "CHUNK_LIMIT_EXCEEDED"
    OPERATION_TIMEOUT = "OPERATION_TIMEOUT"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


class EmbeddingProviderError(RuntimeError):
    """A content-free provider failure safe for deterministic handling."""

    def __init__(self, code: EmbeddingErrorCode | str, *, transient: bool = False) -> None:
        super().__init__("Embedding provider is unavailable.")
        try:
            self.code = EmbeddingErrorCode(code)
        except ValueError:
            self.code = EmbeddingErrorCode.UNKNOWN_PROVIDER_ERROR
        self.transient = transient


class EmbeddingProvider(Protocol):
    @property
    def model(self) -> EmbeddingModel: ...

    async def ensure_ready(self) -> None: ...

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...
