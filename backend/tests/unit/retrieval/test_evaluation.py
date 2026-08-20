from uuid import uuid4

from app.models.identity import Capability, GrantSource
from app.policies.models import (
    AuthorizationGrant,
    AuthorizationScope,
    DepartmentAccess,
    TrustedIdentity,
)
from app.retrieval.contracts import SearchCandidate
from app.retrieval.evaluation import evaluate_curated_query


def _scope() -> AuthorizationScope:
    identity = TrustedIdentity(user_id=uuid4(), email="alice@example.com", display_name="Alice")
    return AuthorizationScope(
        identity=identity,
        grants=(
            AuthorizationGrant(
                membership_id=uuid4(),
                home_tenant_id=uuid4(),
                home_tenant_slug="orion",
                home_tenant_name="Orion Capital",
                workspace_id=uuid4(),
                workspace_slug="orion",
                workspace_name="Orion Capital",
                role="analyst",
                primary_department="finance",
                company_ids=(uuid4(),),
                company_slugs=("orion-main",),
                departments=(
                    DepartmentAccess(key="finance", source=GrantSource.PRIMARY_DEPARTMENT),
                ),
                capabilities=(Capability.QUERY_DOCUMENTS,),
            ),
        ),
    )


def _candidate(*, tenant: str = "orion") -> SearchCandidate:
    return SearchCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        version_number=1,
        excerpt="Drivers of Margin Compression synthetic evidence",
        keyword_score=0.5,
        vector_score=0.8,
        final_score=0.695,
        page_number=3,
        sheet_name=None,
        row_start=None,
        row_end=None,
        cell_start=None,
        cell_end=None,
        filename="Orion_FY2025_Board_Pack.pdf",
        source_type="pdf",
        document_type="FINANCIAL_REPORT",
        reporting_period="FY2025",
        tenant_slug=tenant,
        company_slug="orion-main",
        department="finance",
        visibility="DEPARTMENT_PRIVATE",
        classification="FINANCE_ONLY",
    )


def test_curated_evaluation_reports_recall_at_five_and_no_authorization_leak() -> None:
    result = evaluate_curated_query("Drivers of Margin Compression", (_candidate(),), _scope())

    assert result is not None
    assert result.recall_at_5 == 1.0
    assert result.expected_top_5_hits == 1
    assert result.authorization_leak_count == 0


def test_curated_evaluation_counts_scope_mismatch_and_ad_hoc_is_not_run() -> None:
    scope = _scope()
    result = evaluate_curated_query(
        "drivers of margin compression", (_candidate(tenant="atlas"),), scope
    )

    assert result is not None
    assert result.authorization_leak_count == 1
    assert evaluate_curated_query("unlisted query", (), scope) is None
