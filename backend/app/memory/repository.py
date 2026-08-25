from uuid import UUID

from sqlalchemy import Float, and_, case, cast, exists, false, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CTE

from app.models.documents import DocumentChunk, DocumentClassification, DocumentVisibility
from app.models.identity import Capability, Company, CompanyStatus
from app.models.memory import Memory, MemoryScope, MemorySource, MemoryStatus, MemoryType
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


def _visible_memory_ids(
    scope: AuthorizationScope,
    *,
    statuses: tuple[str, ...] = (MemoryStatus.ACTIVE.value,),
) -> CTE:
    # Build source IDs directly from the authoritative chunk statement. Keeping this as a
    # materialized CTE guarantees source lifecycle/ACL checks precede memory ranking.
    authorized_sources = (
        authorized_chunks_statement(scope)
        .with_only_columns(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id.label("document_id"),
            DocumentChunk.document_version_id.label("document_version_id"),
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
            authorized_sources.c.document_id == MemorySource.document_id,
            authorized_sources.c.document_version_id == MemorySource.document_version_id,
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
            Memory.status.in_(statuses),
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


async def resolve_authorized_company_ids(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    evidence_companies: tuple[tuple[str, str], ...],
) -> tuple[UUID, ...]:
    """Resolve retrieved tenant/company slugs without trusting parallel grant tuple positions."""

    predicates = []
    for grant in scope.grants:
        if Capability.QUERY_DOCUMENTS not in grant.capabilities or not grant.company_ids:
            continue
        company_slugs = tuple(
            sorted(
                {
                    company_slug
                    for workspace_slug, company_slug in evidence_companies
                    if workspace_slug == grant.workspace_slug
                }
            )
        )
        if not company_slugs:
            continue
        predicates.append(
            and_(
                Company.tenant_id == grant.workspace_id,
                Company.id.in_(grant.company_ids),
                Company.slug.in_(company_slugs),
                Company.status == CompanyStatus.ACTIVE.value,
            )
        )
    if not predicates:
        return ()
    rows = (
        (await session.execute(select(Company.id).where(or_(*predicates)).order_by(Company.id)))
        .scalars()
        .all()
    )
    return tuple(rows)


async def list_visible_memories(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    company_ids: tuple[UUID, ...] | None = None,
    memory_types: tuple[str, ...] | None = None,
    statuses: tuple[str, ...] = (
        MemoryStatus.ACTIVE.value,
        MemoryStatus.PENDING_CONFIRMATION.value,
        MemoryStatus.SUPERSEDED.value,
    ),
    limit: int = 100,
) -> tuple[Memory, ...]:
    visible = _visible_memory_ids(scope, statuses=statuses)
    filters = [Memory.id.in_(select(visible.c.id))]
    if company_ids is not None:
        filters.append(Memory.company_id.in_(company_ids))
    if memory_types is not None:
        filters.append(Memory.memory_type.in_(memory_types))
    rows = (
        (
            await session.execute(
                select(Memory)
                .where(*filters)
                .options(
                    selectinload(Memory.sources).selectinload(MemorySource.document_version),
                    selectinload(Memory.conversation),
                )
                .order_by(Memory.created_at.desc(), Memory.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


async def search_visible_memories(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    query: str,
    top_k: int,
    memory_types: tuple[str, ...] = (MemoryType.SEMANTIC.value, MemoryType.EPISODIC.value),
    minimum_score: float = 0.05,
) -> tuple[Memory, ...]:
    """Rank only the authorization-materialized candidate set (never filter after ranking)."""
    visible = _visible_memory_ids(scope)
    search_query = func.plainto_tsquery("simple", query)
    keyword = func.ts_rank_cd(Memory.search_vector, search_query)
    financial_query = any(
        term in query.casefold()
        for term in ("financial", "amount", "revenue", "ebitda", "profit", "margin", "currency")
    )
    preference_boost = case(
        (
            and_(
                Memory.memory_type == MemoryType.SEMANTIC.value,
                Memory.normalized_key == "financial_value_format",
                literal(financial_query),
            ),
            0.45,
        ),
        else_=0.0,
    )
    type_weight = case(
        (Memory.memory_type == MemoryType.SEMANTIC.value, 0.08),
        (Memory.memory_type == MemoryType.EPISODIC.value, 0.03),
        else_=0.0,
    )
    recency = 0.05 / (
        1.0 + cast(func.extract("epoch", func.now() - Memory.created_at), Float) / 86400.0
    )
    rank = keyword + preference_boost + type_weight + recency + (Memory.importance * 0.1)
    ids = tuple(
        (
            await session.execute(
                select(Memory.id)
                .where(
                    Memory.id.in_(select(visible.c.id)),
                    Memory.memory_type.in_(memory_types),
                    or_(Memory.search_vector.op("@@")(search_query), preference_boost > 0),
                    rank >= minimum_score,
                )
                .order_by(rank.desc(), Memory.created_at.desc(), Memory.id)
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
                select(Memory)
                .where(Memory.id.in_(ids))
                .options(
                    selectinload(Memory.sources).selectinload(MemorySource.document_version),
                    selectinload(Memory.conversation),
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {item.id: item for item in rows}
    return tuple(by_id[item] for item in ids)


async def most_recent_authorized_episode(
    session: AsyncSession,
    scope: AuthorizationScope,
) -> Memory | None:
    """Return the newest active episode only after complete ACL/source reauthorization."""

    visible = _visible_memory_ids(scope)
    return (
        (
            await session.execute(
                select(Memory)
                .where(
                    Memory.id.in_(select(visible.c.id)),
                    Memory.memory_type == MemoryType.EPISODIC.value,
                )
                .options(
                    selectinload(Memory.sources).selectinload(MemorySource.document_version),
                    selectinload(Memory.conversation),
                )
                .order_by(Memory.created_at.desc(), Memory.id.desc())
                .limit(1)
            )
        )
        .scalars()
        .one_or_none()
    )


async def relevant_authorized_episodes(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    query: str,
    limit: int = 3,
) -> tuple[Memory, ...]:
    return await search_visible_memories(
        session,
        scope,
        query=query,
        top_k=limit,
        memory_types=(MemoryType.EPISODIC.value,),
    )


async def relevant_semantic_preferences(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    query: str,
    limit: int = 3,
) -> tuple[Memory, ...]:
    return await search_visible_memories(
        session,
        scope,
        query=query,
        top_k=limit,
        memory_types=(MemoryType.SEMANTIC.value,),
    )


async def owned_conversation_summary(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    conversation_id: UUID,
) -> Memory | None:
    visible = _visible_memory_ids(scope)
    return (
        (
            await session.execute(
                select(Memory).where(
                    Memory.id.in_(select(visible.c.id)),
                    Memory.owner_user_id == scope.identity.user_id,
                    Memory.conversation_id == conversation_id,
                    Memory.memory_type == MemoryType.CONVERSATION_SUMMARY.value,
                )
            )
        )
        .scalars()
        .one_or_none()
    )


async def get_visible_memory(
    session: AsyncSession,
    scope: AuthorizationScope,
    memory_id: UUID,
    *,
    statuses: tuple[str, ...] = (
        MemoryStatus.ACTIVE.value,
        MemoryStatus.PENDING_CONFIRMATION.value,
        MemoryStatus.SUPERSEDED.value,
    ),
) -> Memory | None:
    visible = _visible_memory_ids(scope, statuses=statuses)
    return (
        (
            await session.execute(
                select(Memory)
                .where(Memory.id == memory_id, Memory.id.in_(select(visible.c.id)))
                .options(
                    selectinload(Memory.sources).selectinload(MemorySource.document_version),
                    selectinload(Memory.conversation),
                )
            )
        )
        .scalars()
        .one_or_none()
    )
