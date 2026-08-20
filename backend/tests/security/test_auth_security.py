from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.auth.tokens import TokenService
from app.models.identity import Capability
from app.scripts.seed_development import seed_id
from tests.conftest import AuthHarness


@pytest.mark.asyncio
@pytest.mark.parametrize("token_kind", ["malformed", "expired", "wrong_signature"])
async def test_invalid_jwt_variants_fail_generically(
    auth_harness: AuthHarness, token_kind: str
) -> None:
    service = TokenService(auth_harness.settings)
    if token_kind == "malformed":
        token = "not-a-jwt"
    elif token_kind == "expired":
        token = service.issue_access_token(
            seed_id("user", "alice"), now=datetime.now(UTC) - timedelta(minutes=16)
        )
    else:
        different_settings = auth_harness.settings.model_copy(
            update={
                "jwt_secret_key": SecretStr("wrong-signing-key-with-at-least-thirty-two-characters")
            }
        )
        token = TokenService(different_settings).issue_access_token(seed_id("user", "alice"))

    response = await auth_harness.client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "invalid_session",
        "message": "Session is invalid or expired.",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_setting", ["jwt_issuer", "jwt_audience"])
async def test_wrong_issuer_and_audience_fail_generically(
    auth_harness: AuthHarness, changed_setting: str
) -> None:
    wrong_settings = auth_harness.settings.model_copy(
        update={changed_setting: f"wrong-{changed_setting}"}
    )
    token = TokenService(wrong_settings).issue_access_token(seed_id("user", "alice"))

    response = await auth_harness.client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


def test_capability_enum_contains_no_dynamic_or_model_controlled_authority() -> None:
    assert {capability.value for capability in Capability} == {
        "QUERY_DOCUMENTS",
        "MANAGE_UPLOADS",
        "ADMINISTER_PLATFORM",
    }
