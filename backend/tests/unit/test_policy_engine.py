from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.models.identity import Capability, GrantSource
from app.policies.engine import authorize
from app.policies.models import (
    AuthorizationGrant,
    AuthorizationScope,
    DepartmentAccess,
    PolicyReason,
    PolicyRequest,
    TrustedIdentity,
)

ORION = UUID("11111111-1111-4111-8111-111111111111")
ATLAS = UUID("22222222-2222-4222-8222-222222222222")
ORION_COMPANY = UUID("33333333-3333-4333-8333-333333333333")
ATLAS_COMPANY = UUID("44444444-4444-4444-8444-444444444444")


def scope_for(
    *,
    workspace: UUID,
    company: UUID | None,
    role: str,
    primary_department: str,
    departments: tuple[tuple[str, GrantSource], ...],
    capabilities: tuple[Capability, ...] = (Capability.QUERY_DOCUMENTS,),
) -> AuthorizationScope:
    identity = TrustedIdentity(
        user_id=uuid4(), email="synthetic@example.com", display_name="Synthetic User"
    )
    return AuthorizationScope(
        identity=identity,
        grants=(
            AuthorizationGrant(
                membership_id=uuid4(),
                home_tenant_id=workspace,
                home_tenant_slug="workspace",
                home_tenant_name="Workspace",
                workspace_id=workspace,
                workspace_slug="workspace",
                workspace_name="Workspace",
                role=role,
                primary_department=primary_department,
                company_ids=(company,) if company else (),
                company_slugs=("company",) if company else (),
                departments=tuple(
                    DepartmentAccess(key=key, source=source) for key, source in departments
                ),
                capabilities=capabilities,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("user_scope", "department", "expected_reason"),
    [
        (
            scope_for(
                workspace=ORION,
                company=ORION_COMPANY,
                role="analyst",
                primary_department="finance",
                departments=(
                    ("finance", GrantSource.PRIMARY_DEPARTMENT),
                    ("shared", GrantSource.TENANT_SHARED),
                ),
            ),
            "finance",
            PolicyReason.ALLOW_TENANT_DEPARTMENT,
        ),
        (
            scope_for(
                workspace=ORION,
                company=ORION_COMPANY,
                role="counsel",
                primary_department="legal",
                departments=(
                    ("legal", GrantSource.PRIMARY_DEPARTMENT),
                    ("shared", GrantSource.TENANT_SHARED),
                ),
            ),
            "legal",
            PolicyReason.ALLOW_TENANT_DEPARTMENT,
        ),
        (
            scope_for(
                workspace=ORION,
                company=ORION_COMPANY,
                role="reviewer",
                primary_department="investment-committee",
                departments=(
                    ("finance", GrantSource.EXPLICIT_CROSS_DEPARTMENT),
                    ("legal", GrantSource.EXPLICIT_CROSS_DEPARTMENT),
                    ("shared", GrantSource.TENANT_SHARED),
                ),
            ),
            "legal",
            PolicyReason.ALLOW_EXPLICIT_CROSS_DEPARTMENT,
        ),
        (
            scope_for(
                workspace=ATLAS,
                company=ATLAS_COMPANY,
                role="analyst",
                primary_department="finance",
                departments=(
                    ("finance", GrantSource.PRIMARY_DEPARTMENT),
                    ("shared", GrantSource.TENANT_SHARED),
                ),
            ),
            "shared",
            PolicyReason.ALLOW_TENANT_SHARED,
        ),
        (
            scope_for(
                workspace=ATLAS,
                company=ATLAS_COMPANY,
                role="counsel",
                primary_department="legal",
                departments=(
                    ("legal", GrantSource.PRIMARY_DEPARTMENT),
                    ("shared", GrantSource.TENANT_SHARED),
                ),
            ),
            "legal",
            PolicyReason.ALLOW_TENANT_DEPARTMENT,
        ),
    ],
)
def test_expected_query_scopes_allow(
    user_scope: AuthorizationScope, department: str, expected_reason: PolicyReason
) -> None:
    grant = user_scope.grants[0]
    decision = authorize(
        user_scope,
        PolicyRequest(
            capability=Capability.QUERY_DOCUMENTS,
            workspace_id=grant.workspace_id,
            company_id=grant.company_ids[0],
            department=department,
        ),
    )

    assert decision.allowed
    assert decision.reason_code == expected_reason


def test_alice_cannot_gain_legal_atlas_or_forged_company_access() -> None:
    alice = scope_for(
        workspace=ORION,
        company=ORION_COMPANY,
        role="analyst",
        primary_department="finance",
        departments=(
            ("finance", GrantSource.PRIMARY_DEPARTMENT),
            ("shared", GrantSource.TENANT_SHARED),
        ),
    )

    requests = (
        (
            PolicyRequest(
                capability=Capability.QUERY_DOCUMENTS,
                workspace_id=ORION,
                company_id=ORION_COMPANY,
                department="legal",
            ),
            PolicyReason.DENY_DEPARTMENT,
        ),
        (
            PolicyRequest(
                capability=Capability.QUERY_DOCUMENTS,
                workspace_id=ATLAS,
                company_id=ATLAS_COMPANY,
                department="finance",
            ),
            PolicyReason.DENY_WORKSPACE,
        ),
        (
            PolicyRequest(
                capability=Capability.QUERY_DOCUMENTS,
                workspace_id=ORION,
                company_id=ATLAS_COMPANY,
                department="finance",
            ),
            PolicyReason.DENY_COMPANY,
        ),
    )
    for request, reason in requests:
        decision = authorize(alice, request)
        assert not decision.allowed
        assert decision.reason_code == reason


def test_amir_cannot_gain_orion_access() -> None:
    amir = scope_for(
        workspace=ATLAS,
        company=ATLAS_COMPANY,
        role="analyst",
        primary_department="finance",
        departments=(
            ("finance", GrantSource.PRIMARY_DEPARTMENT),
            ("shared", GrantSource.TENANT_SHARED),
        ),
    )

    decision = authorize(
        amir,
        PolicyRequest(
            capability=Capability.QUERY_DOCUMENTS,
            workspace_id=ORION,
            company_id=ORION_COMPANY,
            department="finance",
        ),
    )

    assert not decision.allowed
    assert decision.reason_code == PolicyReason.DENY_WORKSPACE


def test_nora_can_administer_and_manage_uploads_but_cannot_query() -> None:
    nora = scope_for(
        workspace=ORION,
        company=ORION_COMPANY,
        role="admin",
        primary_department="administration",
        departments=(),
        capabilities=(Capability.MANAGE_UPLOADS, Capability.ADMINISTER_PLATFORM),
    )

    upload = authorize(
        nora,
        PolicyRequest(
            capability=Capability.MANAGE_UPLOADS,
            workspace_id=ORION,
            company_id=ORION_COMPANY,
        ),
    )
    query = authorize(
        nora,
        PolicyRequest(
            capability=Capability.QUERY_DOCUMENTS,
            workspace_id=ORION,
            company_id=ORION_COMPANY,
            department="finance",
        ),
    )

    assert upload.allowed and upload.reason_code == PolicyReason.ALLOW_ADMIN_UPLOAD
    assert not query.allowed and query.reason_code == PolicyReason.DENY_CAPABILITY


def test_scope_is_immutable_and_policy_request_rejects_identity_fields() -> None:
    alice = scope_for(
        workspace=ORION,
        company=ORION_COMPANY,
        role="analyst",
        primary_department="finance",
        departments=(("finance", GrantSource.PRIMARY_DEPARTMENT),),
    )

    with pytest.raises(ValidationError):
        alice.identity.display_name = "Forged"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        PolicyRequest.model_validate(
            {
                "capability": "QUERY_DOCUMENTS",
                "workspace_id": str(ORION),
                "company_id": str(ORION_COMPANY),
                "department": "finance",
                "user_id": str(uuid4()),
                "role": "admin",
            }
        )
