from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings


class TokenValidationError(Exception):
    """A deliberately detail-free token validation failure."""


class TokenClaims(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    subject: UUID
    token_id: UUID
    expires_at: datetime


class TokenService:
    algorithm = "HS256"

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret_key.get_secret_value()
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._lifetime = timedelta(minutes=settings.jwt_access_token_minutes)

    @property
    def lifetime_seconds(self) -> int:
        return int(self._lifetime.total_seconds())

    def issue_access_token(self, user_id: UUID, *, now: datetime | None = None) -> str:
        issued_at = now or datetime.now(UTC)
        payload = {
            "sub": str(user_id),
            "iss": self._issuer,
            "aud": self._audience,
            "iat": issued_at,
            "exp": issued_at + self._lifetime,
            "jti": str(uuid4()),
        }
        return jwt.encode(payload, self._secret, algorithm=self.algorithm)

    def decode_access_token(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self.algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["sub", "iss", "aud", "iat", "exp", "jti"]},
            )
            subject = UUID(payload["sub"])
            token_id = UUID(payload["jti"])
            expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise TokenValidationError from exc
        return TokenClaims(subject=subject, token_id=token_id, expires_at=expires_at)
