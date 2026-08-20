from collections.abc import Mapping

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.models.identity import Membership, MembershipStatus, User, UserStatus
from app.scripts.seed_development import seed_id
from tests.conftest import DEMO_PASSWORD, AuthHarness


async def login(client: AsyncClient, email: str, password: str = DEMO_PASSWORD) -> str:
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 900
    return str(data["access_token"])


EXPECTED_SCOPES: Mapping[str, tuple[str, str, list[tuple[str, list[str], list[str]]]]] = {
    "alice@example.com": (
        "Orion Capital",
        "analyst",
        [("orion", ["finance", "shared"], ["QUERY_DOCUMENTS"])],
    ),
    "leo@example.com": (
        "Orion Capital",
        "counsel",
        [("orion", ["legal", "shared"], ["QUERY_DOCUMENTS"])],
    ),
    "maya@example.com": (
        "Orion Capital",
        "reviewer",
        [("orion", ["finance", "legal", "shared"], ["QUERY_DOCUMENTS"])],
    ),
    "amir@example.com": (
        "Atlas Investments",
        "analyst",
        [("atlas", ["finance", "shared"], ["QUERY_DOCUMENTS"])],
    ),
    "lina@example.com": (
        "Atlas Investments",
        "counsel",
        [("atlas", ["legal", "shared"], ["QUERY_DOCUMENTS"])],
    ),
    "nora@example.com": (
        "Platform",
        "admin",
        [
            ("atlas", [], ["MANAGE_UPLOADS"]),
            ("orion", [], ["MANAGE_UPLOADS"]),
            ("platform", [], ["ADMINISTER_PLATFORM"]),
        ],
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("email", EXPECTED_SCOPES)
async def test_seeded_identity_receives_exact_database_scope(
    auth_harness: AuthHarness, email: str
) -> None:
    token = await login(auth_harness.client, email)

    response = await auth_harness.client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    tenant, role, grants = EXPECTED_SCOPES[email]
    assert data["identity"]["email"] == email
    assert data["active_memberships"][0]["tenant"]["name"] == tenant
    assert data["active_memberships"][0]["role"] == role
    assert [
        (
            item["workspace"]["slug"],
            item["query_departments"],
            item["capabilities"],
        )
        for item in data["authorization_scope"]["grants"]
    ] == grants


@pytest.mark.asyncio
async def test_invalid_password_and_unknown_user_are_indistinguishable(
    auth_harness: AuthHarness,
) -> None:
    invalid_password = await auth_harness.client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "incorrect-password"},
    )
    unknown_user = await auth_harness.client.post(
        "/api/auth/login",
        json={"email": "unknown@example.com", "password": "incorrect-password"},
    )

    assert invalid_password.status_code == unknown_user.status_code == 401
    assert (
        invalid_password.json()["error"]
        == unknown_user.json()["error"]
        == {
            "code": "invalid_credentials",
            "message": "Invalid email or password.",
        }
    )


@pytest.mark.asyncio
async def test_forged_identity_fields_are_rejected_or_have_no_effect(
    auth_harness: AuthHarness,
) -> None:
    forged_login = await auth_harness.client.post(
        "/api/auth/login",
        json={
            "email": "alice@example.com",
            "password": DEMO_PASSWORD,
            "tenant": "atlas",
            "user_id": str(seed_id("user", "nora")),
            "role": "admin",
            "department": "legal",
            "company": "atlas-main",
        },
    )
    assert forged_login.status_code == 422
    assert forged_login.json()["error"] == {
        "code": "validation_error",
        "message": "Request validation failed.",
    }

    token = await login(auth_harness.client, "alice@example.com")
    me = await auth_harness.client.get(
        "/api/auth/me?tenant=atlas&role=admin&department=legal&company=atlas-main",
        headers={
            "Authorization": f"Bearer {token}",
            "X-User-ID": str(seed_id("user", "nora")),
            "X-Tenant": "atlas",
            "X-Role": "admin",
        },
    )
    assert me.status_code == 200
    data = me.json()["data"]
    assert data["identity"]["email"] == "alice@example.com"
    assert data["active_memberships"][0]["tenant"]["slug"] == "orion"
    assert data["active_memberships"][0]["role"] == "analyst"
    assert data["authorization_scope"]["grants"][0]["query_departments"] == [
        "finance",
        "shared",
    ]


@pytest.mark.asyncio
async def test_protected_endpoint_requires_backend_authentication(
    auth_harness: AuthHarness,
) -> None:
    response = await auth_harness.client.get(
        "/api/auth/me",
        headers={"X-User-ID": str(seed_id("user", "nora")), "X-Role": "admin"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


@pytest.mark.asyncio
async def test_development_password_login_is_unavailable_in_production(
    auth_harness: AuthHarness,
) -> None:
    auth_harness.settings.app_env = "production"

    response = await auth_harness.client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": DEMO_PASSWORD},
    )

    assert response.status_code == 404
    assert response.json()["error"] == {"code": "not_found", "message": "Not Found"}


@pytest.mark.asyncio
@pytest.mark.parametrize("disable", ["user", "membership"])
async def test_disabled_users_and_revoked_memberships_invalidate_existing_tokens(
    auth_harness: AuthHarness, disable: str
) -> None:
    token = await login(auth_harness.client, "alice@example.com")
    async with auth_harness.session_factory() as session:
        if disable == "user":
            await session.execute(
                update(User)
                .where(User.id == seed_id("user", "alice"))
                .values(status=UserStatus.DISABLED)
            )
        else:
            await session.execute(
                update(Membership)
                .where(Membership.id == seed_id("membership", "alice"))
                .values(status=MembershipStatus.REVOKED)
            )
        await session.commit()

    response = await auth_harness.client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "invalid_session",
        "message": "Session is invalid or expired.",
    }
