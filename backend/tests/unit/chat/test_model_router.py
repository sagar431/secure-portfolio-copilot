from uuid import uuid4

import pytest

from app.chat.contracts import (
    GroundedAnswerDraft,
    GroundedEvidence,
    GroundedGenerationRequest,
    LLMErrorCode,
    LLMGeneration,
    LLMProviderError,
    LLMUsage,
)
from app.chat.router import DeterministicRoutingLLMProvider
from app.model_routing import RoutingSignals, WorkloadKind


def _request(*, documents: int = 1, score: float = 0.9) -> GroundedGenerationRequest:
    document_ids = [uuid4() for _ in range(documents)]
    return GroundedGenerationRequest(
        question="What was revenue?",
        evidence=tuple(
            GroundedEvidence(
                evidence_id=f"ev_{index}",
                chunk_id=uuid4(),
                document_id=document_id,
                document_version_id=uuid4(),
                version_number=1,
                document_title="synthetic.pdf",
                excerpt="Authorized synthetic evidence.",
                page_number=1,
                sheet_name=None,
                row_start=None,
                row_end=None,
                cell_start=None,
                cell_end=None,
            )
            for index, document_id in enumerate(document_ids, 1)
        ),
        routing=RoutingSignals(
            workload=WorkloadKind.GROUNDED_ANSWER,
            question="What was revenue?",
            authorized_document_count=documents,
            top_retrieval_score=score,
        ),
    )


class _Provider:
    def __init__(self, name: str, error: LLMProviderError | None = None) -> None:
        self.model_name = name
        self.error = error
        self.requests: list[GroundedGenerationRequest] = []

    async def generate(self, request: GroundedGenerationRequest) -> LLMGeneration:
        self.requests.append(request)
        if self.error:
            raise self.error
        return LLMGeneration(
            GroundedAnswerDraft("insufficient_evidence", ()),
            LLMUsage(latency_ms=3),
        )


@pytest.mark.asyncio
async def test_simple_request_uses_flash_lite_only() -> None:
    simple = _Provider("google/gemini-3.1-flash-lite")
    heavy = _Provider("google/gemini-3.7-flash")
    router = DeterministicRoutingLLMProvider(
        simple=simple, heavy=heavy, heavy_fallback=heavy, low_confidence_threshold=0.55
    )

    generation = await router.generate(_request())

    assert len(simple.requests) == 1
    assert not heavy.requests
    assert generation.usage.model_name == "google/gemini-3.1-flash-lite"
    assert generation.usage.route_reason == "SIMPLE_LOW_RISK"
    assert not generation.usage.fallback_used


@pytest.mark.asyncio
async def test_multi_document_request_uses_heavy_and_never_downgrades() -> None:
    simple = _Provider("google/gemini-3.1-flash-lite")
    heavy = _Provider("google/gemini-3.7-flash")
    router = DeterministicRoutingLLMProvider(
        simple=simple, heavy=heavy, heavy_fallback=heavy, low_confidence_threshold=0.55
    )

    generation = await router.generate(_request(documents=2))

    assert not simple.requests
    assert len(heavy.requests) == 1
    assert generation.usage.model_name == "google/gemini-3.7-flash"
    assert generation.usage.route_reason == "MULTI_DOCUMENT"


@pytest.mark.asyncio
async def test_router_derives_question_and_document_count_from_the_actual_request() -> None:
    simple = _Provider("google/gemini-3.1-flash-lite")
    heavy = _Provider("google/gemini-3.7-flash")
    router = DeterministicRoutingLLMProvider(
        simple=simple, heavy=heavy, heavy_fallback=heavy, low_confidence_threshold=0.55
    )
    request = _request(documents=2)
    assert request.routing is not None
    mismatched = GroundedGenerationRequest(
        question="Compare revenue across the authorized documents.",
        evidence=request.evidence,
        routing=RoutingSignals(
            workload=WorkloadKind.GROUNDED_ANSWER,
            question="simple",
            authorized_document_count=1,
            top_retrieval_score=0.99,
        ),
    )

    generation = await router.generate(mismatched)

    assert not simple.requests
    assert heavy.requests == [mismatched]
    assert generation.usage.route_reason == "MULTI_DOCUMENT"


@pytest.mark.asyncio
async def test_simple_timeout_falls_forward_once_with_same_authorized_request() -> None:
    simple = _Provider(
        "google/gemini-3.1-flash-lite",
        LLMProviderError(LLMErrorCode.TIMEOUT, transient=True),
    )
    heavy = _Provider("google/gemini-3.7-flash")
    router = DeterministicRoutingLLMProvider(
        simple=simple, heavy=heavy, heavy_fallback=heavy, low_confidence_threshold=0.55
    )
    request = _request()

    generation = await router.generate(request)

    assert simple.requests == [request]
    assert heavy.requests == [request]
    assert generation.usage.model_name == "google/gemini-3.7-flash"
    assert generation.usage.route_reason == "SIMPLE_LOW_RISK"
    assert generation.usage.fallback_used
    assert generation.usage.fallback_reason == "SIMPLE_MODEL_TIMEOUT"
    assert generation.usage.retry_count == 1


@pytest.mark.asyncio
async def test_simple_rejection_does_not_fallback() -> None:
    simple = _Provider("google/gemini-3.1-flash-lite", LLMProviderError(LLMErrorCode.REJECTED))
    heavy = _Provider("google/gemini-3.7-flash")
    router = DeterministicRoutingLLMProvider(
        simple=simple, heavy=heavy, heavy_fallback=heavy, low_confidence_threshold=0.55
    )

    with pytest.raises(LLMProviderError) as raised:
        await router.generate(_request())

    assert raised.value.model_name == "google/gemini-3.1-flash-lite"
    assert raised.value.route_reason == "SIMPLE_LOW_RISK"
    assert not heavy.requests
