import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.passwords import password_service
from app.core.config import get_settings
from app.db.base import Base
from app.models.identity import (
    Capability,
    Company,
    CompanyGrant,
    CompanyStatus,
    Department,
    DepartmentGrant,
    GrantSource,
    Membership,
    MembershipStatus,
    Role,
    Tenant,
    TenantStatus,
    User,
    UserStatus,
    WorkspaceGrant,
)

SEED_NAMESPACE = UUID("6e991c98-98dc-4e83-a806-ef50d97b6291")


def seed_id(kind: str, key: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"{kind}:{key}")


@dataclass(frozen=True)
class DemoUser:
    key: str
    display_name: str
    email: str
    tenant: str
    primary_department: str
    role: str


DEMO_USERS = (
    DemoUser("nora", "Nora Admin", "nora@example.com", "platform", "administration", "admin"),
    DemoUser(
        "alice",
        "Alice Finance Analyst",
        "alice@example.com",
        "orion",
        "finance",
        "analyst",
    ),
    DemoUser("leo", "Leo Legal Counsel", "leo@example.com", "orion", "legal", "counsel"),
    DemoUser(
        "maya",
        "Maya IC Reviewer",
        "maya@example.com",
        "orion",
        "investment-committee",
        "reviewer",
    ),
    DemoUser(
        "amir",
        "Amir Finance Analyst",
        "amir@example.com",
        "atlas",
        "finance",
        "analyst",
    ),
    DemoUser("lina", "Lina Legal Counsel", "lina@example.com", "atlas", "legal", "counsel"),
)


async def _put[ModelT: Base](
    session: AsyncSession, model: type[ModelT], key: UUID, values: dict[str, object]
) -> ModelT:
    row = await session.get(model, key)
    if row is None:
        row = model()
        row.id = key  # type: ignore[attr-defined]
        for field, value in values.items():
            setattr(row, field, value)
        session.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    return row


async def seed_database(session: AsyncSession, password: str) -> None:
    tenants = {
        "platform": ("Platform", TenantStatus.ACTIVE),
        "orion": ("Orion Capital", TenantStatus.ACTIVE),
        "atlas": ("Atlas Investments", TenantStatus.ACTIVE),
    }
    for slug, (name, status) in tenants.items():
        await _put(
            session,
            Tenant,
            seed_id("tenant", slug),
            {"slug": slug, "name": name, "status": status},
        )

    companies = {
        "orion-main": ("orion", "Orion Portfolio Company"),
        "atlas-main": ("atlas", "Atlas Portfolio Company"),
    }
    for slug, (tenant, name) in companies.items():
        await _put(
            session,
            Company,
            seed_id("company", slug),
            {
                "tenant_id": seed_id("tenant", tenant),
                "slug": slug,
                "name": name,
                "status": CompanyStatus.ACTIVE,
            },
        )

    departments = {
        "administration": "Administration",
        "finance": "Finance",
        "legal": "Legal",
        "shared": "Shared",
        "investment-committee": "Investment Committee",
    }
    for key, name in departments.items():
        await _put(
            session,
            Department,
            seed_id("department", key),
            {"key": key, "name": name},
        )

    roles = {
        "admin": "Admin",
        "analyst": "Analyst",
        "counsel": "Counsel",
        "reviewer": "Reviewer",
    }
    for key, name in roles.items():
        await _put(session, Role, seed_id("role", key), {"key": key, "name": name})
    await session.flush()

    for demo_user in DEMO_USERS:
        user_id = seed_id("user", demo_user.key)
        existing = await session.get(User, user_id)
        password_hash = (
            existing.password_hash
            if existing is not None and password_service.verify(password, existing.password_hash)
            else password_service.hash(password)
        )
        await _put(
            session,
            User,
            user_id,
            {
                "email": demo_user.email,
                "display_name": demo_user.display_name,
                "password_hash": password_hash,
                "status": UserStatus.ACTIVE,
            },
        )
        await _put(
            session,
            Membership,
            seed_id("membership", demo_user.key),
            {
                "user_id": user_id,
                "tenant_id": seed_id("tenant", demo_user.tenant),
                "primary_department_id": seed_id("department", demo_user.primary_department),
                "role_id": seed_id("role", demo_user.role),
                "status": MembershipStatus.ACTIVE,
            },
        )
    await session.flush()

    grant_specs: list[tuple[str, str, Capability, GrantSource]] = [
        ("nora", "platform", Capability.ADMINISTER_PLATFORM, GrantSource.ADMIN_ASSIGNMENT),
        ("nora", "orion", Capability.MANAGE_UPLOADS, GrantSource.ADMIN_ASSIGNMENT),
        ("nora", "atlas", Capability.MANAGE_UPLOADS, GrantSource.ADMIN_ASSIGNMENT),
    ]
    grant_specs.extend(
        (user, workspace, Capability.QUERY_DOCUMENTS, GrantSource.PRIMARY_DEPARTMENT)
        for user, workspace in (
            ("alice", "orion"),
            ("leo", "orion"),
            ("maya", "orion"),
            ("amir", "atlas"),
            ("lina", "atlas"),
        )
    )
    for user, workspace, capability, source in grant_specs:
        await _put(
            session,
            WorkspaceGrant,
            seed_id("workspace-grant", f"{user}:{workspace}:{capability}"),
            {
                "membership_id": seed_id("membership", user),
                "workspace_tenant_id": seed_id("tenant", workspace),
                "capability": capability,
                "source": source,
            },
        )

    company_specs = [
        ("nora", "orion-main", Capability.MANAGE_UPLOADS, GrantSource.ADMIN_ASSIGNMENT),
        ("nora", "atlas-main", Capability.MANAGE_UPLOADS, GrantSource.ADMIN_ASSIGNMENT),
        ("alice", "orion-main", Capability.QUERY_DOCUMENTS, GrantSource.PRIMARY_DEPARTMENT),
        ("leo", "orion-main", Capability.QUERY_DOCUMENTS, GrantSource.PRIMARY_DEPARTMENT),
        (
            "maya",
            "orion-main",
            Capability.QUERY_DOCUMENTS,
            GrantSource.EXPLICIT_CROSS_DEPARTMENT,
        ),
        ("amir", "atlas-main", Capability.QUERY_DOCUMENTS, GrantSource.PRIMARY_DEPARTMENT),
        ("lina", "atlas-main", Capability.QUERY_DOCUMENTS, GrantSource.PRIMARY_DEPARTMENT),
    ]
    for user, company, capability, source in company_specs:
        await _put(
            session,
            CompanyGrant,
            seed_id("company-grant", f"{user}:{company}:{capability}"),
            {
                "membership_id": seed_id("membership", user),
                "company_id": seed_id("company", company),
                "capability": capability,
                "source": source,
            },
        )

    department_specs: Iterable[tuple[str, str, str, GrantSource]] = (
        ("alice", "orion", "finance", GrantSource.PRIMARY_DEPARTMENT),
        ("alice", "orion", "shared", GrantSource.TENANT_SHARED),
        ("leo", "orion", "legal", GrantSource.PRIMARY_DEPARTMENT),
        ("leo", "orion", "shared", GrantSource.TENANT_SHARED),
        ("maya", "orion", "finance", GrantSource.EXPLICIT_CROSS_DEPARTMENT),
        ("maya", "orion", "legal", GrantSource.EXPLICIT_CROSS_DEPARTMENT),
        ("maya", "orion", "shared", GrantSource.TENANT_SHARED),
        ("amir", "atlas", "finance", GrantSource.PRIMARY_DEPARTMENT),
        ("amir", "atlas", "shared", GrantSource.TENANT_SHARED),
        ("lina", "atlas", "legal", GrantSource.PRIMARY_DEPARTMENT),
        ("lina", "atlas", "shared", GrantSource.TENANT_SHARED),
    )
    for user, workspace, department, source in department_specs:
        await _put(
            session,
            DepartmentGrant,
            seed_id("department-grant", f"{user}:{workspace}:{department}"),
            {
                "membership_id": seed_id("membership", user),
                "workspace_tenant_id": seed_id("tenant", workspace),
                "department_id": seed_id("department", department),
                "capability": Capability.QUERY_DOCUMENTS,
                "source": source,
            },
        )
    await session.commit()


async def run() -> None:
    settings = get_settings()
    if settings.app_env not in {"development", "test"}:
        raise RuntimeError("The demo seed is available only in development or test mode.")
    if settings.demo_user_password is None:
        raise RuntimeError("Set DEMO_USER_PASSWORD before running the development seed.")
    password = settings.demo_user_password.get_secret_value()
    if len(password) < 12 or password == "choose-a-local-development-password":
        raise RuntimeError("DEMO_USER_PASSWORD must be a non-placeholder value of 12+ characters.")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await seed_database(session, password)
    finally:
        await engine.dispose()
    print("Seeded six development identities and deterministic authorization grants.")


if __name__ == "__main__":
    asyncio.run(run())
