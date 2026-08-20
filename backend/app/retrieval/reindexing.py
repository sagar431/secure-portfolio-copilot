from sqlalchemy import and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking import GeneratedChunk
from app.embeddings.contracts import EmbeddingProvider
from app.ingestion.contracts import FileKind
from app.models.documents import Document, DocumentChunk, DocumentVersion, IngestionStatus
from app.models.identity import Capability, Company, CompanyStatus, Department, Tenant, TenantStatus
from app.policies.models import AuthorizationScope
from app.retrieval.indexing import embed_generated_chunks


def _manageable_clause(scope: AuthorizationScope):  # type: ignore[no-untyped-def]
    predicates = [
        and_(
            DocumentChunk.tenant_id == grant.workspace_id,
            DocumentChunk.company_id.in_(grant.company_ids),
        )
        for grant in scope.grants
        if Capability.MANAGE_UPLOADS in grant.capabilities
        and grant.role == "admin"
        and grant.company_ids
    ]
    return or_(*predicates) if predicates else false()


async def reindex_authorized_pending_chunks(
    session: AsyncSession,
    scope: AuthorizationScope,
    provider: EmbeddingProvider,
    *,
    batch_size: int,
    max_chunks: int,
    timeout_seconds: float,
) -> int:
    """Bounded upgrade/backfill for rows manageable by the trusted database scope."""
    statement = (
        select(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .join(Tenant, Tenant.id == DocumentChunk.tenant_id)
        .join(Company, Company.id == DocumentChunk.company_id)
        .join(Department, Department.id == DocumentChunk.department_id)
        .where(
            _manageable_clause(scope),
            DocumentChunk.active.is_(True),
            DocumentChunk.embedding_status.in_(("PENDING", "FAILED")),
            DocumentChunk.version_status == IngestionStatus.APPROVED.value,
            DocumentChunk.document_deleted.is_(False),
            DocumentChunk.version_deleted.is_(False),
            Document.deleted_at.is_(None),
            DocumentVersion.deleted_at.is_(None),
            DocumentVersion.status == IngestionStatus.APPROVED.value,
            Document.current_approved_version_id == DocumentChunk.document_version_id,
            Document.tenant_id == DocumentChunk.tenant_id,
            Document.company_id == DocumentChunk.company_id,
            Document.department_id == DocumentChunk.department_id,
            Department.key == DocumentChunk.department,
            Document.visibility == DocumentChunk.visibility,
            Document.classification == DocumentChunk.classification,
            DocumentVersion.document_id == DocumentChunk.document_id,
            Tenant.status == TenantStatus.ACTIVE.value,
            Company.status == CompanyStatus.ACTIVE.value,
            Company.tenant_id == DocumentChunk.tenant_id,
        )
        .order_by(DocumentChunk.id)
        .limit(max_chunks)
        .with_for_update(of=DocumentChunk, skip_locked=True)
    )
    rows = tuple((await session.execute(statement)).scalars())
    generated = tuple(
        GeneratedChunk(
            ordinal=row.ordinal,
            tenant_id=row.tenant_id,
            company_id=row.company_id,
            department=row.department,
            visibility=row.visibility,
            classification=row.classification,
            document_id=row.document_id,
            document_version_id=row.document_version_id,
            document_version=row.version_number,
            version_status=row.version_status,
            active=row.active,
            source_type=FileKind(row.source_type),
            content=row.content,
            content_hash=row.content_hash,
            page_number=row.page_number,
            sheet_name=row.sheet_name,
            row_start=row.row_start,
            row_end=row.row_end,
            cell_start=row.cell_start,
            cell_end=row.cell_end,
        )
        for row in rows
    )
    embedded = await embed_generated_chunks(
        provider,
        generated,
        batch_size=batch_size,
        max_chunks=max_chunks,
        timeout_seconds=timeout_seconds,
    )
    model = provider.model
    for row, item in zip(rows, embedded, strict=True):
        row.embedding = list(item.embedding)
        row.embedding_model_name = model.name
        row.embedding_model_version = model.version
        row.embedding_dimensions = model.dimensions
        row.embedding_chunk_hash = row.content_hash
        row.embedding_status = "READY"
    return len(rows)
