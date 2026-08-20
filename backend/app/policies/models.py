from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.identity import Capability, GrantSource


class FrozenStrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class TrustedIdentity(FrozenStrictModel):
    user_id: UUID
    email: EmailStr
    display_name: str


class DepartmentAccess(FrozenStrictModel):
    key: str
    source: GrantSource


class AuthorizationGrant(FrozenStrictModel):
    membership_id: UUID
    home_tenant_id: UUID
    home_tenant_slug: str
    home_tenant_name: str
    workspace_id: UUID
    workspace_slug: str
    workspace_name: str
    role: str
    primary_department: str
    company_ids: tuple[UUID, ...]
    company_slugs: tuple[str, ...]
    departments: tuple[DepartmentAccess, ...]
    capabilities: tuple[Capability, ...]


class AuthorizationScope(FrozenStrictModel):
    identity: TrustedIdentity
    grants: tuple[AuthorizationGrant, ...]


class AuthorizationContext(FrozenStrictModel):
    identity: TrustedIdentity
    scope: AuthorizationScope


class PolicyReason(StrEnum):
    ALLOW_TENANT_DEPARTMENT = "ALLOW_TENANT_DEPARTMENT"
    ALLOW_TENANT_SHARED = "ALLOW_TENANT_SHARED"
    ALLOW_EXPLICIT_CROSS_DEPARTMENT = "ALLOW_EXPLICIT_CROSS_DEPARTMENT"
    ALLOW_ADMIN_UPLOAD = "ALLOW_ADMIN_UPLOAD"
    ALLOW_PLATFORM_ADMIN = "ALLOW_PLATFORM_ADMIN"
    DENY_WORKSPACE = "DENY_WORKSPACE"
    DENY_COMPANY = "DENY_COMPANY"
    DENY_DEPARTMENT = "DENY_DEPARTMENT"
    DENY_CAPABILITY = "DENY_CAPABILITY"
    DENY_ROLE = "DENY_ROLE"
    DENY_DEFAULT = "DENY_DEFAULT"


class PolicyRequest(FrozenStrictModel):
    capability: Capability
    workspace_id: UUID
    company_id: UUID | None = None
    department: str | None = None


class PolicyDecision(FrozenStrictModel):
    allowed: bool
    reason_code: PolicyReason
    capability: Capability
