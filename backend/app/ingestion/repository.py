from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.models.documents import Document, DocumentVersion, IngestionJob, ParsedRow, ParsedSheet
from app.models.identity import Capability, Company, CompanyStatus, Department, Tenant, TenantStatus
from app.policies.models import AuthorizationScope


def manageable_pairs(scope: AuthorizationScope) -> tuple[tuple[UUID, UUID], ...]:
    pairs = {
        (grant.workspace_id, company_id)
        for grant in scope.grants
        if Capability.MANAGE_UPLOADS in grant.capabilities and grant.role == "admin"
        for company_id in grant.company_ids
    }
    return tuple(sorted(pairs, key=lambda pair: (str(pair[0]), str(pair[1]))))


def _manageable_clause(scope: AuthorizationScope):  # type: ignore[no-untyped-def]
    pairs = manageable_pairs(scope)
    if not pairs:
        return Document.id.is_(None)
    return or_(
        *(
            and_(Document.tenant_id == tenant_id, Document.company_id == company_id)
            for tenant_id, company_id in pairs
        )
    )


def _document_load_options() -> tuple[ExecutableOption, ...]:
    version = selectinload(Document.versions)
    return (
        selectinload(Document.tenant),
        selectinload(Document.company),
        selectinload(Document.department),
        version.selectinload(DocumentVersion.ingestion_job),
        version.selectinload(DocumentVersion.pages),
        version.selectinload(DocumentVersion.sheets)
        .selectinload(ParsedSheet.rows)
        .selectinload(ParsedRow.cells),
    )


async def get_active_company(
    session: AsyncSession, tenant_id: UUID, company_id: UUID
) -> Company | None:
    result = await session.execute(
        select(Company)
        .join(Tenant, Tenant.id == Company.tenant_id)
        .where(
            Company.id == company_id,
            Company.tenant_id == tenant_id,
            Company.status == CompanyStatus.ACTIVE,
            Tenant.status == TenantStatus.ACTIVE,
        )
        .options(selectinload(Company.tenant))
    )
    return result.scalar_one_or_none()


async def get_department_by_key(session: AsyncSession, key: str) -> Department | None:
    result = await session.execute(select(Department).where(Department.key == key))
    return result.scalar_one_or_none()


async def get_idempotent_version(
    session: AsyncSession, actor_user_id: UUID, idempotency_key: str
) -> DocumentVersion | None:
    result = await session.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.uploaded_by_user_id == actor_user_id,
            DocumentVersion.idempotency_key == idempotency_key,
        )
        .options(
            selectinload(DocumentVersion.document).options(
                *_document_load_options()  # type: ignore[arg-type]
            )
        )
    )
    return result.scalar_one_or_none()


async def find_initial_duplicate(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    company_id: UUID,
    department_id: UUID,
    visibility: str,
    classification: str,
    document_type: str,
    reporting_period: str | None,
    checksum_sha256: str,
) -> DocumentVersion | None:
    result = await session.execute(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.tenant_id == tenant_id,
            Document.company_id == company_id,
            Document.department_id == department_id,
            Document.visibility == visibility,
            Document.classification == classification,
            Document.document_type == document_type,
            Document.reporting_period.is_not_distinct_from(reporting_period),
            Document.deleted_at.is_(None),
            DocumentVersion.checksum_sha256 == checksum_sha256,
            DocumentVersion.deleted_at.is_(None),
            DocumentVersion.status.in_(("PREVIEW_READY", "APPROVED")),
        )
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
        .options(
            selectinload(DocumentVersion.document).options(
                *_document_load_options()  # type: ignore[arg-type]
            )
        )
    )
    return result.scalar_one_or_none()


async def get_document_for_management(
    session: AsyncSession,
    scope: AuthorizationScope,
    document_id: UUID,
    *,
    include_deleted: bool = False,
    for_update: bool = False,
) -> Document | None:
    statement = select(Document).where(
        Document.id == document_id,
        _manageable_clause(scope),
    )
    if not include_deleted:
        statement = statement.where(Document.deleted_at.is_(None))
    if for_update:
        statement = statement.with_for_update()
    statement = statement.options(*_document_load_options())
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_version_for_management(
    session: AsyncSession,
    scope: AuthorizationScope,
    document_id: UUID,
    version_id: UUID,
) -> tuple[Document, DocumentVersion] | None:
    document = await get_document_for_management(session, scope, document_id)
    if document is None:
        return None
    version = next((item for item in document.versions if item.id == version_id), None)
    if version is None or version.deleted_at is not None:
        return None
    return document, version


async def get_job_for_management(
    session: AsyncSession, scope: AuthorizationScope, job_id: UUID
) -> tuple[Document, DocumentVersion, IngestionJob] | None:
    result = await session.execute(
        select(IngestionJob, DocumentVersion, Document)
        .join(DocumentVersion, DocumentVersion.id == IngestionJob.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            IngestionJob.id == job_id,
            Document.deleted_at.is_(None),
            _manageable_clause(scope),
        )
        .options(
            selectinload(IngestionJob.document_version)
            .selectinload(DocumentVersion.document)
            .options(*_document_load_options())  # type: ignore[arg-type]
        )
    )
    row = result.one_or_none()
    if row is None:
        return None
    job, version, document = row
    return document, version, job


def _apply_library_filters(
    statement: Select[tuple[Document]],
    *,
    tenant_id: UUID | None,
    company_id: UUID | None,
    department: str | None,
    document_type: str | None,
) -> Select[tuple[Document]]:
    if tenant_id is not None:
        statement = statement.where(Document.tenant_id == tenant_id)
    if company_id is not None:
        statement = statement.where(Document.company_id == company_id)
    if department is not None:
        statement = statement.join(Department).where(Department.key == department)
    if document_type is not None:
        statement = statement.where(Document.document_type == document_type)
    return statement


async def list_manageable_documents(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    tenant_id: UUID | None = None,
    company_id: UUID | None = None,
    department: str | None = None,
    document_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Document], int]:
    base = select(Document).where(Document.deleted_at.is_(None), _manageable_clause(scope))
    base = _apply_library_filters(
        base,
        tenant_id=tenant_id,
        company_id=company_id,
        department=department,
        document_type=document_type,
    )
    if status is not None:
        latest_status = (
            select(DocumentVersion.status)
            .where(
                DocumentVersion.document_id == Document.id,
                DocumentVersion.deleted_at.is_(None),
            )
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
            .correlate(Document)
            .scalar_subquery()
        )
        base = base.where(latest_status == status)
    count_statement = select(func.count()).select_from(base.order_by(None).subquery())
    total = int((await session.execute(count_statement)).scalar_one())
    statement = (
        base.order_by(Document.created_at.desc(), Document.id)
        .offset(offset)
        .limit(limit)
        .options(*_document_load_options())
    )
    documents = (await session.execute(statement)).scalars().unique().all()
    return documents, total


async def list_manageable_options(
    session: AsyncSession, scope: AuthorizationScope
) -> Sequence[tuple[Tenant, Company]]:
    pairs = manageable_pairs(scope)
    if not pairs:
        return ()
    result = await session.execute(
        select(Tenant, Company)
        .join(Company, Company.tenant_id == Tenant.id)
        .where(
            or_(
                *(
                    and_(Tenant.id == tenant_id, Company.id == company_id)
                    for tenant_id, company_id in pairs
                )
            ),
            Tenant.status == TenantStatus.ACTIVE,
            Company.status == CompanyStatus.ACTIVE,
        )
        .order_by(Tenant.name, Company.name)
    )
    return result.tuples().all()
