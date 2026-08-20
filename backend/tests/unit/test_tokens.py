from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import SecretStr

from app.auth.tokens import TokenService, TokenValidationError
from app.core.config import Settings
from app.scripts.seed_development import seed_id


def token_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "jwt_secret_key": SecretStr("test-jwt-key-with-at-least-thirty-two-characters"),
        "jwt_issuer": "test-issuer",
        "jwt_audience": "test-audience",
        "jwt_access_token_minutes": 15,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_access_token_contains_no_authorization_claims() -> None:
    service = TokenService(token_settings())
    token = service.issue_access_token(seed_id("user", "alice"))

    payload = jwt.decode(token, options={"verify_signature": False})

    assert set(payload) == {"sub", "iss", "aud", "iat", "exp", "jti"}
    assert service.decode_access_token(token).subject == seed_id("user", "alice")


def test_expired_token_fails() -> None:
    service = TokenService(token_settings())
    token = service.issue_access_token(
        seed_id("user", "alice"), now=datetime.now(UTC) - timedelta(minutes=16)
    )

    with pytest.raises(TokenValidationError):
        service.decode_access_token(token)


@pytest.mark.parametrize(
    ("setting", "value"),
    [("jwt_issuer", "wrong-issuer"), ("jwt_audience", "wrong-audience")],
)
def test_wrong_issuer_or_audience_fails(setting: str, value: str) -> None:
    issuer = TokenService(token_settings())
    token = issuer.issue_access_token(seed_id("user", "alice"))
    validator = TokenService(token_settings(**{setting: value}))

    with pytest.raises(TokenValidationError):
        validator.decode_access_token(token)


def test_malformed_and_wrongly_signed_tokens_fail() -> None:
    validator = TokenService(token_settings())
    wrong_signer = TokenService(
        token_settings(jwt_secret_key=SecretStr("different-test-key-with-thirty-two-characters"))
    )

    with pytest.raises(TokenValidationError):
        validator.decode_access_token("not-a-jwt")
    with pytest.raises(TokenValidationError):
        validator.decode_access_token(wrong_signer.issue_access_token(seed_id("user", "alice")))
