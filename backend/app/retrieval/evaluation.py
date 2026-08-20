from dataclasses import dataclass

from app.models.identity import Capability
from app.policies.models import AuthorizationScope
from app.retrieval.contracts import SearchCandidate

DATASET_NAME = "step5-synthetic-ground-truth-v1"


@dataclass(frozen=True, slots=True)
class CuratedCase:
    query: str
    document_title: str
    excerpt_phrase: str


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    dataset_name: str
    curated_query_count: int
    recall_at_5: float
    expected_top_5_hits: int
    authorization_leak_count: int


CURATED_CASES = (
    CuratedCase(
        query="drivers of margin compression",
        document_title="Orion_FY2025_Board_Pack.pdf",
        excerpt_phrase="Drivers of Margin Compression",
    ),
    CuratedCase(
        query="ebitda margin",
        document_title="Orion_FY2024_FY2025_Financials.xlsx",
        excerpt_phrase="EBITDA Margin",
    ),
    CuratedCase(
        query="investment agreement",
        document_title="Orion_Series_C_Investment_Agreement.pdf",
        excerpt_phrase="Investment Agreement",
    ),
)


def evaluate_curated_query(
    query: str,
    candidates: tuple[SearchCandidate, ...],
    scope: AuthorizationScope,
) -> EvaluationResult | None:
    normalized = " ".join(query.casefold().split())
    case = next((item for item in CURATED_CASES if item.query == normalized), None)
    if case is None:
        return None
    top_five = candidates[:5]
    hit = any(
        item.filename == case.document_title and case.excerpt_phrase in item.excerpt
        for item in top_five
    )
    leaks = 0
    for item in top_five:
        allowed = any(
            Capability.QUERY_DOCUMENTS in grant.capabilities
            and grant.workspace_slug == item.tenant_slug
            and item.company_slug in grant.company_slugs
            and item.department in {department.key for department in grant.departments}
            for grant in scope.grants
        )
        if not allowed:
            leaks += 1
    return EvaluationResult(
        dataset_name=DATASET_NAME,
        curated_query_count=1,
        recall_at_5=1.0 if hit else 0.0,
        expected_top_5_hits=1,
        authorization_leak_count=leaks,
    )
