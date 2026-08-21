import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.memory.audit import record_memory_event
from app.memory.policy import MemoryPolicyError, derive_memory_acl
from app.memory.repository import (
    get_visible_memory,
    list_visible_memories,
    load_authorized_source_chunks,
    search_visible_memories,
)
from app.models.identity import Capability
from app.models.memory import Memory, MemoryScope, MemorySource
from app.policies.models import AuthorizationContext
from app.schemas.memory import (
    DeletedMemoryData,
    MemoryData,
    MemoryListData,
    MemorySourceData,
)


def _require_query_capability(context: AuthorizationContext) -> None:
    if not any(Capability.QUERY_DOCUMENTS in grant.capabilities for grant in context.scope.grants):
        raise APIError(403, "forbidden", "Memory access is not permitted.")


def _memory_data(memory: Memory, *, user_id: UUID) -> MemoryData:
    return MemoryData(
        id=memory.id,
        company_id=memory.company_id,
        scope=memory.scope,  # type: ignore[arg-type]
        owner_user_id=memory.owner_user_id,
        department=memory.department,  # type: ignore[arg-type]
        visibility=memory.visibility,  # type: ignore[arg-type]
        classification=memory.classification,  # type: ignore[arg-type]
        content=memory.content,
        expires_at=memory.expires_at,
        created_at=memory.created_at,
        can_delete=(memory.owner_user_id == user_id or memory.created_by_user_id == user_id),
        sources=tuple(
            MemorySourceData(
                chunk_id=source.chunk_id,
                document_id=source.document_id,
                document_version_id=source.document_version_id,
            )
            for source in memory.sources
        ),
    )


class MemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        context: AuthorizationContext,
        *,
        content: str,
        company_id: UUID,
        requested_scope: str,
        source_chunk_ids: tuple[UUID, ...],
        expires_in_days: int,
    ) -> MemoryData:
        _require_query_capability(context)
        matching_grants = tuple(
            grant
            for grant in context.scope.grants
            if Capability.QUERY_DOCUMENTS in grant.capabilities and company_id in grant.company_ids
        )
        tenant_ids = {grant.workspace_id for grant in matching_grants}
        if len(tenant_ids) != 1:
            raise APIError(403, "forbidden", "Memory target is not permitted.")
        sources = await load_authorized_source_chunks(self.session, context.scope, source_chunk_ids)
        if len(sources) != len(source_chunk_ids):
            raise APIError(404, "not_found", "Memory source was not found.")
        if any(source.company_id != company_id for source in sources):
            raise APIError(404, "not_found", "Memory source was not found.")
        try:
            memory_scope = MemoryScope(requested_scope)
            acl = derive_memory_acl(
                memory_scope,
                tuple(
                    (source.department, source.visibility, source.classification)
                    for source in sources
                ),
            )
        except (ValueError, MemoryPolicyError):
            raise APIError(
                422, "invalid_memory_scope", "Memory scope is incompatible with its sources."
            ) from None
        now = datetime.now(UTC)
        memory = Memory(
            tenant_id=tenant_ids.pop(),
            company_id=company_id,
            scope=acl.scope.value,
            owner_user_id=(
                context.identity.user_id if acl.scope is MemoryScope.PRIVATE_USER else None
            ),
            created_by_user_id=context.identity.user_id,
            department=acl.department,
            visibility=acl.visibility,
            classification=acl.classification,
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            expires_at=now + timedelta(days=expires_in_days),
        )
        memory.sources = [
            MemorySource(
                chunk_id=source.id,
                document_id=source.document_id,
                document_version_id=source.document_version_id,
                tenant_id=source.tenant_id,
                company_id=source.company_id,
                department=source.department,
                visibility=source.visibility,
                classification=source.classification,
            )
            for source in sources
        ]
        self.session.add(memory)
        await self.session.commit()
        await self.session.refresh(memory, attribute_names=["sources"])
        record_memory_event(
            context,
            action="create",
            outcome="allow",
            memory_id=memory.id,
            scope=memory.scope,
        )
        return _memory_data(memory, user_id=context.identity.user_id)

    async def inspect(self, context: AuthorizationContext) -> MemoryListData:
        _require_query_capability(context)
        rows = await list_visible_memories(self.session, context.scope)
        record_memory_event(context, action="inspect", outcome="allow", result_count=len(rows))
        return MemoryListData(
            memories=tuple(_memory_data(item, user_id=context.identity.user_id) for item in rows)
        )

    async def search(
        self, context: AuthorizationContext, *, query: str, top_k: int
    ) -> MemoryListData:
        _require_query_capability(context)
        rows = await search_visible_memories(self.session, context.scope, query=query, top_k=top_k)
        record_memory_event(context, action="search", outcome="allow", result_count=len(rows))
        return MemoryListData(
            memories=tuple(_memory_data(item, user_id=context.identity.user_id) for item in rows)
        )

    async def delete(self, context: AuthorizationContext, *, memory_id: UUID) -> DeletedMemoryData:
        _require_query_capability(context)
        memory = await get_visible_memory(self.session, context.scope, memory_id)
        if memory is None or (
            memory.owner_user_id != context.identity.user_id
            and memory.created_by_user_id != context.identity.user_id
        ):
            raise APIError(404, "not_found", "Memory was not found.")
        memory.deleted_at = datetime.now(UTC)
        await self.session.commit()
        record_memory_event(
            context,
            action="delete",
            outcome="allow",
            memory_id=memory.id,
            scope=memory.scope,
        )
        return DeletedMemoryData(memory_id=memory_id)
