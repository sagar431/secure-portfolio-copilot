import asyncio
import math
from uuid import uuid4

import httpx
import pytest

from app.chunking import GeneratedChunk
from app.embeddings import DeterministicFakeEmbeddingProvider, EmbeddingProviderError
from app.embeddings.contracts import EmbeddingModel
from app.embeddings.ollama import OllamaEmbeddingProvider
from app.ingestion.contracts import FileKind
from app.retrieval.indexing import embed_generated_chunks


def _chunk(ordinal: int) -> GeneratedChunk:
    return GeneratedChunk(
        ordinal=ordinal,
        tenant_id=uuid4(),
        company_id=uuid4(),
        department="finance",
        visibility="DEPARTMENT_PRIVATE",
        classification="FINANCE_ONLY",
        document_id=uuid4(),
        document_version_id=uuid4(),
        document_version=1,
        version_status="APPROVED",
        active=True,
        source_type=FileKind.PDF,
        content=f"synthetic revenue ebitda evidence {ordinal}",
        content_hash=f"{ordinal:064x}",
        page_number=ordinal + 1,
    )


class RecordingProvider:
    def __init__(self, *, dimensions: int = 768, invalid: str | None = None) -> None:
        self._model = EmbeddingModel("nomic-embed-text", "v1.5", dimensions)
        self.invalid = invalid
        self.batch_sizes: list[int] = []

    @property
    def model(self) -> EmbeddingModel:
        return self._model

    async def ensure_ready(self) -> None:
        return None

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.batch_sizes.append(len(texts))
        value = 1.0
        if self.invalid == "nonfinite":
            value = math.inf
        if self.invalid == "zero":
            value = 0.0
        return tuple((value,) + (0.0,) * (self.model.dimensions - 1) for _ in texts)


class SlowProvider(RecordingProvider):
    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        await asyncio.sleep(0.05)
        return await super().embed(texts)


@pytest.mark.asyncio
async def test_fake_provider_is_deterministic_finite_and_nonzero() -> None:
    provider = DeterministicFakeEmbeddingProvider()
    first = await provider.embed(("Revenue growth", "!!!"))
    second = await provider.embed(("Revenue growth", "!!!"))

    assert first == second
    assert all(len(vector) == 768 for vector in first)
    assert all(all(math.isfinite(value) for value in vector) for vector in first)
    assert all(any(value != 0 for value in vector) for vector in first)


@pytest.mark.asyncio
async def test_embedding_batches_are_bounded_and_preserve_order() -> None:
    provider = RecordingProvider()
    chunks = tuple(_chunk(index) for index in range(5))

    embedded = await embed_generated_chunks(
        provider, chunks, batch_size=2, max_chunks=5, timeout_seconds=1
    )

    assert provider.batch_sizes == [2, 2, 1]
    assert [item.chunk.ordinal for item in embedded] == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "expected_code"),
    [
        (RecordingProvider(dimensions=767), "DIMENSION_MISMATCH"),
        (RecordingProvider(invalid="nonfinite"), "INVALID_VECTOR"),
        (RecordingProvider(invalid="zero"), "INVALID_VECTOR"),
    ],
)
async def test_invalid_provider_vectors_fail_closed(
    provider: RecordingProvider, expected_code: str
) -> None:
    with pytest.raises(EmbeddingProviderError) as captured:
        await embed_generated_chunks(
            provider, (_chunk(0),), batch_size=1, max_chunks=1, timeout_seconds=1
        )

    assert captured.value.code == expected_code
    assert str(captured.value) == "Embedding provider is unavailable."


@pytest.mark.asyncio
async def test_embedding_total_chunk_limit_fails_before_provider_call() -> None:
    provider = RecordingProvider()

    with pytest.raises(EmbeddingProviderError) as captured:
        await embed_generated_chunks(
            provider,
            (_chunk(0), _chunk(1)),
            batch_size=1,
            max_chunks=1,
            timeout_seconds=1,
        )

    assert captured.value.code == "CHUNK_LIMIT_EXCEEDED"
    assert provider.batch_sizes == []


@pytest.mark.asyncio
async def test_embedding_operation_timeout_is_safe_and_bounded() -> None:
    with pytest.raises(EmbeddingProviderError) as captured:
        await embed_generated_chunks(
            SlowProvider(),
            (_chunk(0),),
            batch_size=1,
            max_chunks=1,
            timeout_seconds=0.001,
        )

    assert captured.value.code == "OPERATION_TIMEOUT"
    assert captured.value.transient is True


def _ollama() -> OllamaEmbeddingProvider:
    return OllamaEmbeddingProvider(
        base_url="http://127.0.0.1:11434",
        model_name="nomic-embed-text",
        model_version="v1.5",
        dimensions=768,
        timeout_seconds=1,
    )


@pytest.mark.asyncio
async def test_ollama_transport_failure_retries_at_most_once() -> None:
    attempts = 0

    async def operation() -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.RemoteProtocolError("synthetic protocol failure")

    with pytest.raises(EmbeddingProviderError) as captured:
        await _ollama()._request(operation)

    assert attempts == 2
    assert captured.value.code == "PROVIDER_TRANSIENT"


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "attempts_expected"), [(503, 2), (400, 1)])
async def test_ollama_http_retry_policy(status: int, attempts_expected: int) -> None:
    attempts = 0

    async def operation() -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status)

    with pytest.raises(EmbeddingProviderError):
        await _ollama()._request(operation)

    assert attempts == attempts_expected
