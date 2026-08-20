from collections.abc import Sequence

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.documents import (
    Document,
    DocumentChunk,
    DocumentClassification,
    DocumentVersion,
    DocumentVisibility,
    IngestionStatus,
)
from app.models.identity import Capability, Company, CompanyStatus, Tenant, TenantStatus
from app.policies.models import AuthorizationScope
from app.retrieval.contracts import AuthorizedIndexStatus, SearchCandidate
from app.retrieval.limits import MAX_EXCERPT_CHARACTERS


def _authorized_chunk_clause(scope: AuthorizationScope) -> ColumnElement[bool]:
    """Build grant-correlated SQL predicates; an empty query scope fails closed."""
    predicates = []
    for grant in scope.grants:
        if Capability.QUERY_DOCUMENTS not in grant.capabilities or not grant.company_ids:
            continue
        departments = tuple(item.key for item in grant.departments)
        if not departments:
            continue
        predicates.append(
            and_(
                DocumentChunk.tenant_id == grant.workspace_id,
                DocumentChunk.company_id.in_(grant.company_ids),
                DocumentChunk.department.in_(departments),
            )
        )
    return or_(*predicates) if predicates else false()


def _visibility_clause() -> ColumnElement[bool]:
    return or_(
        and_(
            DocumentChunk.visibility == DocumentVisibility.DEPARTMENT_PRIVATE.value,
            or_(
                and_(
                    DocumentChunk.department == "finance",
                    DocumentChunk.classification == DocumentClassification.FINANCE_ONLY.value,
                ),
                and_(
                    DocumentChunk.department == "legal",
                    DocumentChunk.classification
                    == DocumentClassification.LEGAL_ONLY_CONFIDENTIAL.value,
                ),
            ),
        ),
        and_(
            DocumentChunk.visibility == DocumentVisibility.TENANT_SHARED.value,
            DocumentChunk.department == "shared",
            DocumentChunk.classification == DocumentClassification.TENANT_SHARED.value,
        ),
    )


def _lifecycle_clause() -> ColumnElement[bool]:
    return and_(
        DocumentChunk.active.is_(True),
        DocumentChunk.version_status == IngestionStatus.APPROVED.value,
        DocumentChunk.document_deleted.is_(False),
        DocumentChunk.version_deleted.is_(False),
        Document.deleted_at.is_(None),
        DocumentVersion.deleted_at.is_(None),
        DocumentVersion.status == IngestionStatus.APPROVED.value,
        Document.current_approved_version_id == DocumentChunk.document_version_id,
    )


def _authorized_base(scope: AuthorizationScope):  # type: ignore[no-untyped-def]
    return (
        select(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .join(Tenant, Tenant.id == DocumentChunk.tenant_id)
        .join(Company, Company.id == DocumentChunk.company_id)
        .where(
            _authorized_chunk_clause(scope),
            _visibility_clause(),
            _lifecycle_clause(),
            Tenant.status == TenantStatus.ACTIVE.value,
            Company.status == CompanyStatus.ACTIVE.value,
            Company.tenant_id == DocumentChunk.tenant_id,
            Document.tenant_id == DocumentChunk.tenant_id,
            Document.company_id == DocumentChunk.company_id,
            Document.department_id == DocumentChunk.department_id,
            DocumentVersion.document_id == DocumentChunk.document_id,
        )
    )


async def search_authorized_chunks(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    query: str,
    top_k: int,
) -> Sequence[SearchCandidate]:
    """Search only candidates authorized by the required immutable scope."""
    search_query = func.plainto_tsquery("simple", query)
    rank = func.ts_rank_cd(DocumentChunk.search_vector, search_query).label("score")
    statement = (
        _authorized_base(scope)
        .with_only_columns(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.document_version_id,
            DocumentChunk.version_number,
            func.left(DocumentChunk.content, MAX_EXCERPT_CHARACTERS).label("excerpt"),
            rank,
            DocumentChunk.page_number,
            DocumentChunk.sheet_name,
            DocumentChunk.row_start,
            DocumentChunk.row_end,
            DocumentChunk.cell_start,
            DocumentChunk.cell_end,
            DocumentVersion.safe_filename,
            DocumentChunk.source_type,
            Document.document_type,
            Document.reporting_period,
            Tenant.slug,
            Company.slug,
            DocumentChunk.department,
            DocumentChunk.visibility,
            DocumentChunk.classification,
        )
        .where(DocumentChunk.search_vector.bool_op("@@")(search_query))
        .order_by(rank.desc(), DocumentChunk.id)
        .limit(top_k)
    )
    rows = (await session.execute(statement)).all()
    return tuple(
        SearchCandidate(
            chunk_id=row[0],
            document_id=row[1],
            document_version_id=row[2],
            version_number=row[3],
            excerpt=row[4],
            score=float(row[5]),
            page_number=row[6],
            sheet_name=row[7],
            row_start=row[8],
            row_end=row[9],
            cell_start=row[10],
            cell_end=row[11],
            filename=row[12],
            source_type=row[13],
            document_type=row[14],
            reporting_period=row[15],
            tenant_slug=row[16],
            company_slug=row[17],
            department=row[18],
            visibility=row[19],
            classification=row[20],
        )
        for row in rows
    )


async def get_authorized_index_status(
    session: AsyncSession, scope: AuthorizationScope
) -> AuthorizedIndexStatus:
    """Count only the caller's searchable chunks and documents."""
    base = _authorized_base(scope).subquery()
    statement = select(
        func.count(base.c.id),
        func.count(func.distinct(base.c.document_id)),
    )
    row = (await session.execute(statement)).one()
    return AuthorizedIndexStatus(
        active_chunk_count=int(row[0]),
        indexed_document_count=int(row[1]),
    )
