"""Add deterministic identity and authorization tables.

Revision ID: 20260820_0002
Revises: 20260820_0001
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_tenants_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_companies_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_companies_tenant_slug"),
    )
    op.create_index(op.f("ix_companies_tenant_id"), "companies", ["tenant_id"], unique=False)
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("primary_department_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_memberships_status"),
        sa.ForeignKeyConstraint(["primary_department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),
    )
    op.create_index(op.f("ix_memberships_tenant_id"), "memberships", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"], unique=False)
    op.create_table(
        "workspace_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_tenant_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "capability IN ('QUERY_DOCUMENTS', 'MANAGE_UPLOADS', 'ADMINISTER_PLATFORM')",
            name="ck_workspace_grants_capability",
        ),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "membership_id", "workspace_tenant_id", "capability", name="uq_workspace_grant"
        ),
    )
    op.create_index(
        op.f("ix_workspace_grants_membership_id"),
        "workspace_grants",
        ["membership_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_grants_workspace_tenant_id"),
        "workspace_grants",
        ["workspace_tenant_id"],
        unique=False,
    )
    op.create_table(
        "company_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "capability IN ('QUERY_DOCUMENTS', 'MANAGE_UPLOADS', 'ADMINISTER_PLATFORM')",
            name="ck_company_grants_capability",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", "company_id", "capability", name="uq_company_grant"),
    )
    op.create_index(
        op.f("ix_company_grants_company_id"), "company_grants", ["company_id"], unique=False
    )
    op.create_index(
        op.f("ix_company_grants_membership_id"),
        "company_grants",
        ["membership_id"],
        unique=False,
    )
    op.create_table(
        "department_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_tenant_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "capability IN ('QUERY_DOCUMENTS', 'MANAGE_UPLOADS', 'ADMINISTER_PLATFORM')",
            name="ck_department_grants_capability",
        ),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "membership_id",
            "workspace_tenant_id",
            "department_id",
            "capability",
            name="uq_department_grant",
        ),
    )
    op.create_index(
        op.f("ix_department_grants_department_id"),
        "department_grants",
        ["department_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_department_grants_membership_id"),
        "department_grants",
        ["membership_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_department_grants_workspace_tenant_id"),
        "department_grants",
        ["workspace_tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_department_grants_workspace_tenant_id"), table_name="department_grants")
    op.drop_index(op.f("ix_department_grants_membership_id"), table_name="department_grants")
    op.drop_index(op.f("ix_department_grants_department_id"), table_name="department_grants")
    op.drop_table("department_grants")
    op.drop_index(op.f("ix_company_grants_membership_id"), table_name="company_grants")
    op.drop_index(op.f("ix_company_grants_company_id"), table_name="company_grants")
    op.drop_table("company_grants")
    op.drop_index(op.f("ix_workspace_grants_workspace_tenant_id"), table_name="workspace_grants")
    op.drop_index(op.f("ix_workspace_grants_membership_id"), table_name="workspace_grants")
    op.drop_table("workspace_grants")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_tenant_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_index(op.f("ix_companies_tenant_id"), table_name="companies")
    op.drop_table("companies")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("departments")
    op.drop_table("tenants")
