from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.models.identity import (
    Capability,
    Company,
    CompanyGrant,
    CompanyStatus,
    DepartmentGrant,
    GrantSource,
    Membership,
    MembershipStatus,
    TenantStatus,
    User,
    UserStatus,
    WorkspaceGrant,
)
from app.policies.models import (
    AuthorizationContext,
    AuthorizationGrant,
    AuthorizationScope,
    DepartmentAccess,
    TrustedIdentity,
)


def _identity_load_options() -> tuple[ExecutableOption, ...]:
    membership = selectinload(User.memberships)
    return (
        membership.selectinload(Membership.tenant),
        membership.selectinload(Membership.role),
        membership.selectinload(Membership.primary_department),
        membership.selectinload(Membership.workspace_grants).selectinload(
            WorkspaceGrant.workspace_tenant
        ),
        membership.selectinload(Membership.company_grants).selectinload(CompanyGrant.company),
        membership.selectinload(Membership.department_grants).selectinload(
            DepartmentGrant.department
        ),
    )


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    statement = (
        select(User).where(User.email == email.strip().lower()).options(*_identity_load_options())
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    statement = select(User).where(User.id == user_id).options(*_identity_load_options())
    result = await session.execute(statement)
    return result.scalar_one_or_none()


def build_authorization_context(user: User) -> AuthorizationContext | None:
    if user.status != UserStatus.ACTIVE:
        return None

    identity = TrustedIdentity(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
    )
    authorization_grants: list[AuthorizationGrant] = []
    for membership in user.memberships:
        if (
            membership.status != MembershipStatus.ACTIVE
            or membership.tenant.status != TenantStatus.ACTIVE
        ):
            continue

        workspace_capabilities: dict[UUID, set[Capability]] = defaultdict(set)
        workspace_by_id = {}
        for grant in membership.workspace_grants:
            if grant.workspace_tenant.status != TenantStatus.ACTIVE:
                continue
            workspace_by_id[grant.workspace_tenant_id] = grant.workspace_tenant
            workspace_capabilities[grant.workspace_tenant_id].add(Capability(grant.capability))

        for workspace_id, capabilities in workspace_capabilities.items():
            companies: list[Company] = []
            for company_grant in membership.company_grants:
                if (
                    company_grant.capability in capabilities
                    and company_grant.company.tenant_id == workspace_id
                    and company_grant.company.status == CompanyStatus.ACTIVE
                ):
                    companies.append(company_grant.company)

            departments = [
                DepartmentAccess(
                    key=department_grant.department.key,
                    source=GrantSource(department_grant.source),
                )
                for department_grant in membership.department_grants
                if department_grant.workspace_tenant_id == workspace_id
                and department_grant.capability == Capability.QUERY_DOCUMENTS
                and Capability.QUERY_DOCUMENTS in capabilities
            ]
            workspace = workspace_by_id[workspace_id]
            ordered_companies = tuple(
                sorted(
                    {company.id: company for company in companies}.values(),
                    key=lambda company: str(company.id),
                )
            )
            authorization_grants.append(
                AuthorizationGrant(
                    membership_id=membership.id,
                    home_tenant_id=membership.tenant_id,
                    home_tenant_slug=membership.tenant.slug,
                    home_tenant_name=membership.tenant.name,
                    workspace_id=workspace.id,
                    workspace_slug=workspace.slug,
                    workspace_name=workspace.name,
                    role=membership.role.key,
                    primary_department=membership.primary_department.key,
                    company_ids=tuple(company.id for company in ordered_companies),
                    company_slugs=tuple(company.slug for company in ordered_companies),
                    departments=tuple(sorted(departments, key=lambda item: item.key)),
                    capabilities=tuple(sorted(capabilities, key=lambda item: item.value)),
                )
            )

    if not authorization_grants:
        return None
    scope = AuthorizationScope(
        identity=identity,
        grants=tuple(
            sorted(authorization_grants, key=lambda grant: (grant.workspace_slug, grant.role))
        ),
    )
    return AuthorizationContext(identity=identity, scope=scope)
