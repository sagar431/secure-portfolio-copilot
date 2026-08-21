import asyncio
from uuid import uuid4

from app.chat.contracts import GroundedEvidence, GroundedGenerationRequest
from app.chat.factory import create_llm_provider
from app.core.config import get_settings
from app.model_routing import RoutingSignals, WorkloadKind


def _evidence(index: int) -> GroundedEvidence:
    return GroundedEvidence(
        evidence_id=f"ev_{index}",
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        version_number=1,
        document_title=f"synthetic-{index}.pdf",
        excerpt="Synthetic authorized evidence states that revenue was 100 units.",
        page_number=1,
        sheet_name=None,
        row_start=None,
        row_end=None,
        cell_start=None,
        cell_end=None,
    )


async def main() -> None:
    settings = get_settings()
    if settings.llm_provider != "router":
        raise RuntimeError("Live router smoke requires LLM_PROVIDER=router")
    provider = create_llm_provider(settings)
    simple_evidence = (_evidence(1),)
    strong_evidence = (_evidence(1), _evidence(2))
    requests = (
        GroundedGenerationRequest(
            question="What was revenue?",
            evidence=simple_evidence,
            routing=RoutingSignals(
                WorkloadKind.GROUNDED_ANSWER,
                "What was revenue?",
                1,
                0.95,
            ),
        ),
        GroundedGenerationRequest(
            question="Compare revenue across the authorized reports.",
            evidence=strong_evidence,
            routing=RoutingSignals(
                WorkloadKind.GROUNDED_ANSWER,
                "Compare revenue across the authorized reports.",
                2,
                0.95,
            ),
        ),
    )
    for request in requests:
        generation = await provider.generate(request)
        print(
            {
                "model": generation.usage.model_name,
                "route_reason": generation.usage.route_reason,
                "fallback_used": generation.usage.fallback_used,
                "status": generation.answer.status,
                "claim_count": len(generation.answer.claims),
                "latency_ms": generation.usage.latency_ms,
            }
        )


if __name__ == "__main__":
    asyncio.run(main())
