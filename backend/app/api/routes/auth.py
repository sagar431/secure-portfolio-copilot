from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit import record_auth_event
from app.auth.dependencies import CurrentAuthorizationContext
from app.auth.passwords import password_service
from app.auth.repository import build_authorization_context, get_user_by_email
from app.auth.tokens import TokenService
from app.core.config import Settings, get_settings
from app.core.errors import APIError
from app.db.session import get_db_session
from app.schemas.api import SuccessResponse
from app.schemas.auth import (
    AuthorizationScopeData,
    IdentityData,
    LoginRequest,
    MeData,
    MembershipData,
    ScopeGrantData,
    TenantData,
    TokenData,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/login", response_model=SuccessResponse[TokenData])
async def login(
    payload: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SuccessResponse[TokenData]:
    if settings.app_env == "production":
        raise APIError(404, "not_found", "Not Found")
    user = await get_user_by_email(session, str(payload.email).lower())
    if user is None:
        password_service.verify_unknown_user(payload.password)
        verified = False
    else:
        verified = password_service.verify(payload.password, user.password_hash)

    context = build_authorization_context(user) if user is not None and verified else None
    if context is None:
        record_auth_event(
            event="login",
            outcome="deny",
            reason_code="INVALID_CREDENTIALS",
            request_id=request.state.request_id,
            user_id=user.id if user is not None else None,
        )
        raise APIError(401, "invalid_credentials", "Invalid email or password.")

    token_service = TokenService(settings)
    token = token_service.issue_access_token(context.identity.user_id)
    record_auth_event(
        event="login",
        outcome="allow",
        reason_code="AUTHENTICATED",
        request_id=request.state.request_id,
        user_id=context.identity.user_id,
    )
    return SuccessResponse(
        data=TokenData(
            access_token=token,
            expires_in=token_service.lifetime_seconds,
        ),
        request_id=request.state.request_id,
    )


@router.get("/me", response_model=SuccessResponse[MeData])
async def me(
    request: Request,
    context: CurrentAuthorizationContext,
) -> SuccessResponse[MeData]:
    active_memberships: dict[UUID, MembershipData] = {}
    scope_grants = []
    for grant in context.scope.grants:
        active_memberships[grant.membership_id] = MembershipData(
            id=grant.membership_id,
            tenant=TenantData(
                id=grant.home_tenant_id,
                slug=grant.home_tenant_slug,
                name=grant.home_tenant_name,
            ),
            role=grant.role,
            primary_department=grant.primary_department,
        )
        scope_grants.append(
            ScopeGrantData(
                workspace=TenantData(
                    id=grant.workspace_id,
                    slug=grant.workspace_slug,
                    name=grant.workspace_name,
                ),
                company_ids=grant.company_ids,
                company_slugs=grant.company_slugs,
                query_departments=tuple(item.key for item in grant.departments),
                capabilities=tuple(item.value for item in grant.capabilities),
            )
        )
    data = MeData(
        identity=IdentityData(
            id=context.identity.user_id,
            email=context.identity.email,
            display_name=context.identity.display_name,
        ),
        active_memberships=tuple(active_memberships.values()),
        authorization_scope=AuthorizationScopeData(grants=tuple(scope_grants)),
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)
