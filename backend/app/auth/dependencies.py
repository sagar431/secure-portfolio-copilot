from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.audit import record_auth_event
from app.auth.repository import build_authorization_context, get_user_by_id
from app.auth.tokens import TokenService, TokenValidationError
from app.core.config import Settings, get_settings
from app.core.errors import APIError
from app.db.session import get_db_session
from app.policies.models import AuthorizationContext

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_authorization_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthorizationContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        record_auth_event(
            event="session_validation",
            outcome="deny",
            reason_code="MISSING_BEARER_TOKEN",
            request_id=request.state.request_id,
        )
        raise APIError(401, "invalid_session", "Session is invalid or expired.")

    try:
        claims = TokenService(settings).decode_access_token(credentials.credentials)
    except TokenValidationError:
        record_auth_event(
            event="session_validation",
            outcome="deny",
            reason_code="INVALID_TOKEN",
            request_id=request.state.request_id,
        )
        raise APIError(401, "invalid_session", "Session is invalid or expired.") from None

    user = await get_user_by_id(session, claims.subject)
    context = build_authorization_context(user) if user is not None else None
    if context is None:
        record_auth_event(
            event="session_validation",
            outcome="deny",
            reason_code="INACTIVE_IDENTITY",
            request_id=request.state.request_id,
            user_id=claims.subject,
        )
        raise APIError(401, "invalid_session", "Session is invalid or expired.")
    return context


CurrentAuthorizationContext = Annotated[
    AuthorizationContext, Depends(get_current_authorization_context)
]
