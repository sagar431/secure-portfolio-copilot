from uuid import UUID

from sqlalchemy import and_, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models.documents import DocumentChunk, DocumentClassification, DocumentVisibility
from app.models.identity import Capability
from app.models.memory import Memory, MemoryScope, MemorySource
from app.policies.models import AuthorizationScope
from app.retrieval.repository import authorized_chunks_statement


def _valid_acl_clause() -> ColumnElement[bool]:
    return or_(
        and_(
            Memory.department == "finance",
            Memory.visibility == DocumentVisibility.DEPARTMENT_PRIVATE.value,
            Memory.classification == DocumentClassification.FINANCE_ONLY.value,
        ),
        and_(
            Memory.department == "legal",
            Memory.visibility == DocumentVisibility.DEPARTMENT_PRIVATE.value,
            Memory.classification == DocumentClassification.LEGAL_ONLY_CONFIDENTIAL.value,
        ),
        and_(
            Memory.department == "shared",
            Memory.visibility == DocumentVisibility.TENANT_SHARED.value,
            Memory.classification == DocumentClassification.TENANT_SHARED.value,
        ),
    )


def _scope_clause(scope: AuthorizationScope) -> ColumnElement[bool]:
    predicates = []
    for grant in scope.grants:
        if Capability.QUERY_DOCUMENTS not in grant.capabilities or not grant.company_ids:
            continue
        departments = tuple(item.key for item in grant.departments)
        if not departments:
            continue
        predicates.append(
            and_(
                Memory.tenant_id == grant.workspace_id,
                Memory.company_id.in_(grant.company_ids),
                Memory.department.in_(departments),
                or_(
                    and_(
                        Memory.scope == MemoryScope.PRIVATE_USER.value,
                        Memory.owner_user_id == scope.identity.user_id,
                    ),
                    and_(
                        Memory.scope == MemoryScope.FINANCE.value,
                        Memory.department == "finance",
                    ),
                    and_(
                        Memory.scope == MemoryScope.LEGAL.value,
                        Memory.department == "legal",
                    ),
                    and_(
                        Memory.scope == MemoryScope.SHARED.value,
                        Memory.department == "shared",
                    ),
                ),
            )
        )
    return or_(*predicates) if predicates else false()


def _visible_memory_ids(scope: AuthorizationScope):  # type: ignore[no-untyped-def]
    # Build source IDs directly from the authoritative chunk statement. Keeping this as a
    # materialized CTE guarantees source lifecycle/ACL checks precede memory ranking.
    authorized_sources = (
        authorized_chunks_statement(scope)
        .with_only_columns(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.tenant_id.label("tenant_id"),
            DocumentChunk.company_id.label("company_id"),
            DocumentChunk.department.label("department"),
            DocumentChunk.visibility.label("visibility"),
            DocumentChunk.classification.label("classification"),
        )
        .cte("authorized_memory_sources")
        .prefix_with("MATERIALIZED")
    )
    authorized_source_match = exists(
        select(authorized_sources.c.chunk_id).where(
            authorized_sources.c.chunk_id == MemorySource.chunk_id,
            authorized_sources.c.tenant_id == MemorySource.tenant_id,
            authorized_sources.c.company_id == MemorySource.company_id,
            authorized_sources.c.department == MemorySource.department,
            authorized_sources.c.visibility == MemorySource.visibility,
            authorized_sources.c.classification == MemorySource.classification,
            MemorySource.tenant_id == Memory.tenant_id,
            MemorySource.company_id == Memory.company_id,
            MemorySource.department == Memory.department,
            MemorySource.visibility == Memory.visibility,
            MemorySource.classification == Memory.classification,
        )
    )
    unauthorized_source_exists = exists(
        select(MemorySource.id).where(
            MemorySource.memory_id == Memory.id,
            ~authorized_source_match,
        )
    )
    return (
        select(Memory.id, Memory.search_vector, Memory.created_at)
        .where(
            _scope_clause(scope),
            _valid_acl_clause(),
            Memory.deleted_at.is_(None),
            Memory.expires_at > func.now(),
            ~unauthorized_source_exists,
        )
        .cte("visible_memories")
        .prefix_with("MATERIALIZED")
    )


async def load_authorized_source_chunks(
    session: AsyncSession, scope: AuthorizationScope, source_ids: tuple[UUID, ...]
) -> tuple[DocumentChunk, ...]:
    if not source_ids:
        return ()
    rows = (
        (
            await session.execute(
                authorized_chunks_statement(scope).where(DocumentChunk.id.in_(source_ids))
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


async def list_visible_memories(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    company_ids: tuple[UUID, ...] | None = None,
    limit: int = 100,
) -> tuple[Memory, ...]:
    visible = _visible_memory_ids(scope)
    filters = [Memory.id.in_(select(visible.c.id))]
    if company_ids is not None:
        filters.append(Memory.company_id.in_(company_ids))
    rows = (
        (
            await session.execute(
                select(Memory)
                .where(*filters)
                .options(selectinload(Memory.sources))
                .order_by(Memory.created_at.desc(), Memory.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


async def search_visible_memories(
    session: AsyncSession, scope: AuthorizationScope, *, query: str, top_k: int
) -> tuple[Memory, ...]:
    visible = _visible_memory_ids(scope)
    search_query = func.plainto_tsquery("simple", query)
    rank = func.ts_rank_cd(visible.c.search_vector, search_query)
    ids = tuple(
        (
            await session.execute(
                select(visible.c.id)
                .where(visible.c.search_vector.op("@@")(search_query))
                .order_by(rank.desc(), visible.c.created_at.desc(), visible.c.id)
                .limit(top_k)
            )
        )
        .scalars()
        .all()
    )
    if not ids:
        return ()
    rows = (
        (
            await session.execute(
                select(Memory).where(Memory.id.in_(ids)).options(selectinload(Memory.sources))
            )
        )
        .scalars()
        .all()
    )
    by_id = {item.id: item for item in rows}
    return tuple(by_id[item] for item in ids)


async def get_visible_memory(
    session: AsyncSession, scope: AuthorizationScope, memory_id: UUID
) -> Memory | None:
    visible = _visible_memory_ids(scope)
    return (
        (
            await session.execute(
                select(Memory)
                .where(Memory.id == memory_id, Memory.id.in_(select(visible.c.id)))
                .options(selectinload(Memory.sources))
            )
        )
        .scalars()
        .one_or_none()
    )
