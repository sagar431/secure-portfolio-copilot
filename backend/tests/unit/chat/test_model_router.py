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
async def test_simple_request_uses_qwen_only() -> None:
    qwen = _Provider("qwen3:8b")
    kimi = _Provider("kimi-k3")
    router = DeterministicRoutingLLMProvider(qwen=qwen, kimi=kimi, low_confidence_threshold=0.55)

    generation = await router.generate(_request())

    assert len(qwen.requests) == 1
    assert not kimi.requests
    assert generation.usage.model_name == "qwen3:8b"
    assert generation.usage.route_reason == "SIMPLE_LOW_RISK"
    assert not generation.usage.fallback_used


@pytest.mark.asyncio
async def test_multi_document_request_uses_kimi_and_never_downgrades() -> None:
    qwen = _Provider("qwen3:8b")
    kimi = _Provider("kimi-k3")
    router = DeterministicRoutingLLMProvider(qwen=qwen, kimi=kimi, low_confidence_threshold=0.55)

    generation = await router.generate(_request(documents=2))

    assert not qwen.requests
    assert len(kimi.requests) == 1
    assert generation.usage.model_name == "kimi-k3"
    assert generation.usage.route_reason == "MULTI_DOCUMENT"


@pytest.mark.asyncio
async def test_router_derives_question_and_document_count_from_the_actual_request() -> None:
    qwen = _Provider("qwen3:8b")
    kimi = _Provider("kimi-k3")
    router = DeterministicRoutingLLMProvider(qwen=qwen, kimi=kimi, low_confidence_threshold=0.55)
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

    assert not qwen.requests
    assert kimi.requests == [mismatched]
    assert generation.usage.route_reason == "MULTI_DOCUMENT"


@pytest.mark.asyncio
async def test_qwen_timeout_falls_back_to_kimi_with_same_authorized_request() -> None:
    qwen = _Provider("qwen3:8b", LLMProviderError(LLMErrorCode.TIMEOUT, transient=True))
    kimi = _Provider("kimi-k3")
    router = DeterministicRoutingLLMProvider(qwen=qwen, kimi=kimi, low_confidence_threshold=0.55)
    request = _request()

    generation = await router.generate(request)

    assert qwen.requests == [request]
    assert kimi.requests == [request]
    assert generation.usage.model_name == "kimi-k3"
    assert generation.usage.route_reason == "SIMPLE_LOW_RISK"
    assert generation.usage.fallback_used
    assert generation.usage.fallback_reason == "QWEN_TIMEOUT"


@pytest.mark.asyncio
async def test_qwen_rejection_does_not_fallback() -> None:
    qwen = _Provider("qwen3:8b", LLMProviderError(LLMErrorCode.REJECTED))
    kimi = _Provider("kimi-k3")
    router = DeterministicRoutingLLMProvider(qwen=qwen, kimi=kimi, low_confidence_threshold=0.55)

    with pytest.raises(LLMProviderError) as raised:
        await router.generate(_request())

    assert raised.value.model_name == "qwen3:8b"
    assert raised.value.route_reason == "SIMPLE_LOW_RISK"
    assert not kimi.requests
