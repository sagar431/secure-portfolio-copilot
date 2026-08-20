from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class IdentityData(BaseModel):
    id: UUID
    email: EmailStr
    display_name: str


class TenantData(BaseModel):
    id: UUID
    slug: str
    name: str


class MembershipData(BaseModel):
    id: UUID
    tenant: TenantData
    role: str
    primary_department: str


class ScopeGrantData(BaseModel):
    workspace: TenantData
    company_ids: tuple[UUID, ...]
    company_slugs: tuple[str, ...]
    query_departments: tuple[str, ...]
    capabilities: tuple[str, ...]


class AuthorizationScopeData(BaseModel):
    grants: tuple[ScopeGrantData, ...]


class MeData(BaseModel):
    identity: IdentityData
    active_memberships: tuple[MembershipData, ...]
    authorization_scope: AuthorizationScopeData
