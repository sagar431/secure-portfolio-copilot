from types import SimpleNamespace
from uuid import UUID, uuid4

from app.auth.repository import build_authorization_context
from app.models.identity import (
    Capability,
    CompanyStatus,
    GrantSource,
    MembershipStatus,
    TenantStatus,
    UserStatus,
)


def test_company_ids_and_slugs_preserve_the_same_ordered_company_pairs() -> None:
    workspace_id = uuid4()
    company_by_id_first = SimpleNamespace(
        id=UUID("10000000-0000-0000-0000-000000000001"),
        tenant_id=workspace_id,
        slug="zeta-company",
        status=CompanyStatus.ACTIVE,
    )
    company_by_slug_first = SimpleNamespace(
        id=UUID("20000000-0000-0000-0000-000000000002"),
        tenant_id=workspace_id,
        slug="alpha-company",
        status=CompanyStatus.ACTIVE,
    )
    tenant = SimpleNamespace(
        id=workspace_id,
        slug="workspace",
        name="Workspace",
        status=TenantStatus.ACTIVE,
    )
    membership_id = uuid4()
    membership = SimpleNamespace(
        id=membership_id,
        status=MembershipStatus.ACTIVE,
        tenant=tenant,
        tenant_id=workspace_id,
        role=SimpleNamespace(key="analyst"),
        primary_department=SimpleNamespace(key="finance"),
        workspace_grants=(
            SimpleNamespace(
                workspace_tenant=tenant,
                workspace_tenant_id=workspace_id,
                capability=Capability.QUERY_DOCUMENTS,
            ),
        ),
        company_grants=(
            SimpleNamespace(
                company=company_by_slug_first,
                capability=Capability.QUERY_DOCUMENTS,
            ),
            SimpleNamespace(
                company=company_by_id_first,
                capability=Capability.QUERY_DOCUMENTS,
            ),
        ),
        department_grants=(
            SimpleNamespace(
                workspace_tenant_id=workspace_id,
                capability=Capability.QUERY_DOCUMENTS,
                department=SimpleNamespace(key="finance"),
                source=GrantSource.PRIMARY_DEPARTMENT,
            ),
        ),
    )
    user = SimpleNamespace(
        id=uuid4(),
        email="pairing@example.com",
        display_name="Pairing Test",
        status=UserStatus.ACTIVE,
        memberships=(membership,),
    )

    context = build_authorization_context(user)

    assert context is not None
    grant = context.scope.grants[0]
    assert tuple(zip(grant.company_ids, grant.company_slugs, strict=True)) == (
        (company_by_id_first.id, company_by_id_first.slug),
        (company_by_slug_first.id, company_by_slug_first.slug),
    )
