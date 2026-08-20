import math
from collections.abc import Sequence

from sqlalchemy import and_, case, false, func, or_, select
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
from app.models.identity import Capability, Company, CompanyStatus, Department, Tenant, TenantStatus
from app.policies.models import AuthorizationScope
from app.retrieval.contracts import AuthorizedIndexStatus, SearchCandidate
from app.retrieval.limits import MAX_EXCERPT_CHARACTERS


def _authorized_chunk_clause(scope: AuthorizationScope) -> ColumnElement[bool]:
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
        .join(Department, Department.id == DocumentChunk.department_id)
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
            Department.key == DocumentChunk.department,
            Document.visibility == DocumentChunk.visibility,
            Document.classification == DocumentChunk.classification,
            DocumentVersion.document_id == DocumentChunk.document_id,
        )
    )


async def search_authorized_chunks(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    query: str,
    query_embedding: tuple[float, ...],
    model_name: str,
    model_version: str,
    dimensions: int,
    top_k: int,
) -> Sequence[SearchCandidate]:
    """Filter authority/lifecycle in a CTE before vector scoring and top-k."""
    if (
        dimensions != 768
        or len(query_embedding) != dimensions
        or not all(math.isfinite(value) for value in query_embedding)
        or math.sqrt(sum(value * value for value in query_embedding)) == 0
    ):
        raise ValueError("Embedding dimensions do not match the retrieval index.")
    authorized = (
        _authorized_base(scope)
        .where(
            DocumentChunk.embedding_status == "READY",
            DocumentChunk.embedding.is_not(None),
            DocumentChunk.embedding_model_name == model_name,
            DocumentChunk.embedding_model_version == model_version,
            DocumentChunk.embedding_dimensions == dimensions,
            DocumentChunk.embedding_chunk_hash == DocumentChunk.content_hash,
        )
        .with_only_columns(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id,
            DocumentChunk.document_version_id,
            DocumentChunk.version_number,
            DocumentChunk.content,
            DocumentChunk.search_vector,
            DocumentChunk.embedding,
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
            Tenant.slug.label("tenant_slug"),
            Company.slug.label("company_slug"),
            DocumentChunk.department,
            DocumentChunk.visibility,
            DocumentChunk.classification,
        )
        .cte("authorized_chunks")
        .prefix_with("MATERIALIZED")
    )
    search_query = func.plainto_tsquery("simple", query)
    keyword_raw = func.ts_rank_cd(authorized.c.search_vector, search_query)
    keyword_score = (keyword_raw / (keyword_raw + 1.0)).label("keyword_score")
    vector_score = func.greatest(
        0.0, 1.0 - authorized.c.embedding.cosine_distance(list(query_embedding))
    ).label("vector_score")
    final_score = (keyword_score * 0.35 + vector_score * 0.65).label("final_score")
    statement = (
        select(
            authorized.c.chunk_id,
            authorized.c.document_id,
            authorized.c.document_version_id,
            authorized.c.version_number,
            func.left(authorized.c.content, MAX_EXCERPT_CHARACTERS),
            keyword_score,
            vector_score,
            final_score,
            authorized.c.page_number,
            authorized.c.sheet_name,
            authorized.c.row_start,
            authorized.c.row_end,
            authorized.c.cell_start,
            authorized.c.cell_end,
            authorized.c.safe_filename,
            authorized.c.source_type,
            authorized.c.document_type,
            authorized.c.reporting_period,
            authorized.c.tenant_slug,
            authorized.c.company_slug,
            authorized.c.department,
            authorized.c.visibility,
            authorized.c.classification,
        )
        .order_by(final_score.desc(), keyword_score.desc(), authorized.c.chunk_id)
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
            keyword_score=float(row[5]),
            vector_score=float(row[6]),
            final_score=float(row[7]),
            page_number=row[8],
            sheet_name=row[9],
            row_start=row[10],
            row_end=row[11],
            cell_start=row[12],
            cell_end=row[13],
            filename=row[14],
            source_type=row[15],
            document_type=row[16],
            reporting_period=row[17],
            tenant_slug=row[18],
            company_slug=row[19],
            department=row[20],
            visibility=row[21],
            classification=row[22],
        )
        for row in rows
    )


async def get_authorized_index_status(
    session: AsyncSession, scope: AuthorizationScope
) -> AuthorizedIndexStatus:
    base = (
        _authorized_base(scope)
        .with_only_columns(
            DocumentChunk.id, DocumentChunk.document_id, DocumentChunk.embedding_status
        )
        .cte("authorized_index_status")
    )
    row = (
        await session.execute(
            select(
                func.count(base.c.id),
                func.count(func.distinct(base.c.document_id)),
                func.sum(case((base.c.embedding_status == "READY", 1), else_=0)),
                func.sum(case((base.c.embedding_status == "PENDING", 1), else_=0)),
                func.sum(case((base.c.embedding_status == "FAILED", 1), else_=0)),
            )
        )
    ).one()
    return AuthorizedIndexStatus(*(int(value or 0) for value in row))
