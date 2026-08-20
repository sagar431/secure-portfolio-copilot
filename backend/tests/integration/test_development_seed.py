import pytest
from sqlalchemy import func, select

from app.auth.passwords import password_service
from app.models.identity import (
    Company,
    CompanyGrant,
    Department,
    DepartmentGrant,
    Membership,
    Role,
    Tenant,
    User,
    WorkspaceGrant,
)
from app.scripts.seed_development import seed_database
from tests.conftest import DEMO_PASSWORD, AuthHarness


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_stores_only_argon2_hashes(
    auth_harness: AuthHarness,
) -> None:
    async with auth_harness.session_factory() as session:
        await seed_database(session, DEMO_PASSWORD)
        expected_counts = {
            Tenant: 3,
            Company: 2,
            Department: 5,
            Role: 4,
            User: 6,
            Membership: 6,
            WorkspaceGrant: 8,
            CompanyGrant: 7,
            DepartmentGrant: 11,
        }
        for model, expected in expected_counts.items():
            actual = await session.scalar(select(func.count()).select_from(model))
            assert actual == expected

        users = (await session.scalars(select(User))).all()
        assert {user.email for user in users} == {
            "nora@example.com",
            "alice@example.com",
            "leo@example.com",
            "maya@example.com",
            "amir@example.com",
            "lina@example.com",
        }
        assert all(user.password_hash != DEMO_PASSWORD for user in users)
        assert all(user.password_hash.startswith("$argon2id$") for user in users)
        assert all(password_service.verify(DEMO_PASSWORD, user.password_hash) for user in users)
