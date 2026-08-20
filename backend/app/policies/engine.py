from app.models.identity import Capability, GrantSource
from app.policies.models import (
    AuthorizationScope,
    PolicyDecision,
    PolicyReason,
    PolicyRequest,
)


def _decision(request: PolicyRequest, allowed: bool, reason: PolicyReason) -> PolicyDecision:
    return PolicyDecision(allowed=allowed, reason_code=reason, capability=request.capability)


def authorize(scope: AuthorizationScope, request: PolicyRequest) -> PolicyDecision:
    """Evaluate a request using only immutable, database-derived authorization data."""
    workspace_grants = tuple(
        grant for grant in scope.grants if grant.workspace_id == request.workspace_id
    )
    if not workspace_grants:
        return _decision(request, False, PolicyReason.DENY_WORKSPACE)

    capable_grants = tuple(
        grant for grant in workspace_grants if request.capability in grant.capabilities
    )
    if not capable_grants:
        return _decision(request, False, PolicyReason.DENY_CAPABILITY)

    if request.capability == Capability.ADMINISTER_PLATFORM:
        if any(grant.role == "admin" for grant in capable_grants):
            return _decision(request, True, PolicyReason.ALLOW_PLATFORM_ADMIN)
        return _decision(request, False, PolicyReason.DENY_ROLE)

    if request.company_id is None:
        return _decision(request, False, PolicyReason.DENY_DEFAULT)
    company_grants = tuple(
        grant for grant in capable_grants if request.company_id in grant.company_ids
    )
    if not company_grants:
        return _decision(request, False, PolicyReason.DENY_COMPANY)

    if request.capability == Capability.MANAGE_UPLOADS:
        if any(grant.role == "admin" for grant in company_grants):
            return _decision(request, True, PolicyReason.ALLOW_ADMIN_UPLOAD)
        return _decision(request, False, PolicyReason.DENY_ROLE)

    if request.capability != Capability.QUERY_DOCUMENTS or request.department is None:
        return _decision(request, False, PolicyReason.DENY_DEFAULT)

    for grant in company_grants:
        department_access = next(
            (item for item in grant.departments if item.key == request.department), None
        )
        if department_access is None:
            continue
        if department_access.source == GrantSource.TENANT_SHARED:
            reason = PolicyReason.ALLOW_TENANT_SHARED
        elif department_access.source == GrantSource.EXPLICIT_CROSS_DEPARTMENT:
            reason = PolicyReason.ALLOW_EXPLICIT_CROSS_DEPARTMENT
        else:
            reason = PolicyReason.ALLOW_TENANT_DEPARTMENT
        return _decision(request, True, reason)
    return _decision(request, False, PolicyReason.DENY_DEPARTMENT)
