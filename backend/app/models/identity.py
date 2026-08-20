from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TenantStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class CompanyStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class Capability(StrEnum):
    QUERY_DOCUMENTS = "QUERY_DOCUMENTS"
    MANAGE_UPLOADS = "MANAGE_UPLOADS"
    ADMINISTER_PLATFORM = "ADMINISTER_PLATFORM"


class GrantSource(StrEnum):
    PRIMARY_DEPARTMENT = "PRIMARY_DEPARTMENT"
    TENANT_SHARED = "TENANT_SHARED"
    EXPLICIT_CROSS_DEPARTMENT = "EXPLICIT_CROSS_DEPARTMENT"
    ADMIN_ASSIGNMENT = "ADMIN_ASSIGNMENT"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Tenant(TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_tenants_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=TenantStatus.ACTIVE, nullable=False)

    companies: Mapped[list[Company]] = relationship(back_populates="tenant")


class Company(TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_companies_tenant_slug"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_companies_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=CompanyStatus.ACTIVE, nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="companies")


class Department(TimestampMixin, Base):
    __tablename__ = "departments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=UserStatus.ACTIVE, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_memberships_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    primary_department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id"), nullable=False
    )
    role_id: Mapped[UUID] = mapped_column(ForeignKey("roles.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=MembershipStatus.ACTIVE, nullable=False)

    user: Mapped[User] = relationship(back_populates="memberships")
    tenant: Mapped[Tenant] = relationship(foreign_keys=[tenant_id])
    primary_department: Mapped[Department] = relationship(foreign_keys=[primary_department_id])
    role: Mapped[Role] = relationship(foreign_keys=[role_id])
    workspace_grants: Mapped[list[WorkspaceGrant]] = relationship(
        back_populates="membership", cascade="all, delete-orphan"
    )
    company_grants: Mapped[list[CompanyGrant]] = relationship(
        back_populates="membership", cascade="all, delete-orphan"
    )
    department_grants: Mapped[list[DepartmentGrant]] = relationship(
        back_populates="membership", cascade="all, delete-orphan"
    )


class WorkspaceGrant(TimestampMixin, Base):
    __tablename__ = "workspace_grants"
    __table_args__ = (
        UniqueConstraint(
            "membership_id", "workspace_tenant_id", "capability", name="uq_workspace_grant"
        ),
        CheckConstraint(
            "capability IN ('QUERY_DOCUMENTS', 'MANAGE_UPLOADS', 'ADMINISTER_PLATFORM')",
            name="ck_workspace_grants_capability",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    membership: Mapped[Membership] = relationship(back_populates="workspace_grants")
    workspace_tenant: Mapped[Tenant] = relationship(foreign_keys=[workspace_tenant_id])


class CompanyGrant(TimestampMixin, Base):
    __tablename__ = "company_grants"
    __table_args__ = (
        UniqueConstraint("membership_id", "company_id", "capability", name="uq_company_grant"),
        CheckConstraint(
            "capability IN ('QUERY_DOCUMENTS', 'MANAGE_UPLOADS', 'ADMINISTER_PLATFORM')",
            name="ck_company_grants_capability",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    membership: Mapped[Membership] = relationship(back_populates="company_grants")
    company: Mapped[Company] = relationship(foreign_keys=[company_id])


class DepartmentGrant(TimestampMixin, Base):
    __tablename__ = "department_grants"
    __table_args__ = (
        UniqueConstraint(
            "membership_id",
            "workspace_tenant_id",
            "department_id",
            "capability",
            name="uq_department_grant",
        ),
        CheckConstraint(
            "capability IN ('QUERY_DOCUMENTS', 'MANAGE_UPLOADS', 'ADMINISTER_PLATFORM')",
            name="ck_department_grants_capability",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    membership_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    membership: Mapped[Membership] = relationship(back_populates="department_grants")
    workspace_tenant: Mapped[Tenant] = relationship(foreign_keys=[workspace_tenant_id])
    department: Mapped[Department] = relationship(foreign_keys=[department_id])
