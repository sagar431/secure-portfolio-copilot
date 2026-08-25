import hashlib
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import APIError
from app.memory.audit import record_memory_event
from app.memory.contracts import CandidateAction, MemoryCandidate
from app.memory.policy import MemoryPolicyError, derive_memory_acl
from app.memory.repository import (
    get_visible_memory,
    list_visible_memories,
    load_authorized_source_chunks,
    most_recent_authorized_episode,
    owned_conversation_summary,
    relevant_authorized_episodes,
    relevant_semantic_preferences,
    search_visible_memories,
)
from app.models.identity import Capability
from app.models.memory import (
    Memory,
    MemoryAuditEvent,
    MemoryOrigin,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from app.policies.models import AuthorizationContext
from app.schemas.memory import DeletedMemoryData, MemoryData, MemoryListData, MemorySourceData

SEMANTIC_EXPIRY_DAYS = 90
EPISODIC_EXPIRY_DAYS = 30
SUMMARY_EXPIRY_DAYS = 30
MAX_AUTOMATIC_CONTENT = 500
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_SENSITIVE = re.compile(
    r"\b(password|secret|api[_ -]?key|social security|ssn|medical|diagnosis|credit card)\b",
    re.IGNORECASE,
)


def _require_query_capability(context: AuthorizationContext) -> None:
    if not any(Capability.QUERY_DOCUMENTS in grant.capabilities for grant in context.scope.grants):
        raise APIError(403, "forbidden", "Memory access is not permitted.")


def _authorized_company(context: AuthorizationContext, company_id: UUID) -> tuple[UUID, str, str]:
    matches = [
        (grant.workspace_id, grant.workspace_name, grant.company_slugs[index])
        for grant in context.scope.grants
        if Capability.QUERY_DOCUMENTS in grant.capabilities
        for index, candidate in enumerate(grant.company_ids)
        if candidate == company_id
    ]
    if not matches or len({item[0] for item in matches}) != 1:
        raise APIError(403, "forbidden", "Memory target is not permitted.")
    return matches[0]


def _audit(
    session: AsyncSession,
    context: AuthorizationContext,
    memory: Memory,
    action: str,
    reason_code: str,
) -> None:
    session.add(
        MemoryAuditEvent(
            memory_id=memory.id,
            tenant_id=memory.tenant_id,
            actor_user_id=context.identity.user_id,
            action=action,
            reason_code=reason_code,
        )
    )


def _memory_data(memory: Memory, *, context: AuthorizationContext) -> MemoryData:
    _, tenant_name, company_slug = _authorized_company(context, memory.company_id)
    own = memory.created_by_user_id == context.identity.user_id
    return MemoryData(
        id=memory.id,
        company_id=memory.company_id,
        scope=memory.scope,  # type: ignore[arg-type]
        memory_type=memory.memory_type,  # type: ignore[arg-type]
        origin=memory.origin,  # type: ignore[arg-type]
        status=memory.status,  # type: ignore[arg-type]
        owner_user_id=memory.owner_user_id,
        department=memory.department,  # type: ignore[arg-type]
        visibility=memory.visibility,  # type: ignore[arg-type]
        classification=memory.classification,  # type: ignore[arg-type]
        content=memory.content,
        normalized_key=memory.normalized_key,
        reason=memory.reason,
        confidence=memory.confidence,
        importance=memory.importance,
        owner_display=context.identity.display_name if own else "Authorized workspace member",
        tenant_display=tenant_name,
        company_display=company_slug,
        source_conversation=(memory.conversation.title if memory.conversation else None),
        expires_at=memory.expires_at,
        created_at=memory.created_at,
        can_delete=own,
        can_confirm=(
            own
            and memory.owner_user_id == context.identity.user_id
            and memory.status == MemoryStatus.PENDING_CONFIRMATION.value
        ),
        sources=tuple(
            MemorySourceData(
                chunk_id=source.chunk_id,
                document_id=source.document_id,
                document_version_id=source.document_version_id,
                document_name=source.document_version.original_filename,
            )
            for source in memory.sources
        ),
    )


def _base_private_memory(
    context: AuthorizationContext,
    *,
    tenant_id: UUID,
    company_id: UUID,
    content: str,
    memory_type: MemoryType,
    origin: MemoryOrigin,
    status: MemoryStatus,
    expires_in_days: int,
    reason: str,
    normalized_key: str | None,
    confidence: float,
    importance: float,
    conversation_id: UUID | None = None,
    source_message_id: UUID | None = None,
    agent_run_id: UUID | None = None,
) -> Memory:
    now = datetime.now(UTC)
    return Memory(
        tenant_id=tenant_id,
        company_id=company_id,
        scope=MemoryScope.PRIVATE_USER.value,
        owner_user_id=context.identity.user_id,
        created_by_user_id=context.identity.user_id,
        memory_type=memory_type.value,
        origin=origin.value,
        status=status.value,
        conversation_id=conversation_id,
        agent_run_id=agent_run_id,
        source_message_id=source_message_id,
        department="shared",
        visibility="TENANT_SHARED",
        classification="TENANT_SHARED",
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        normalized_key=normalized_key,
        reason=reason,
        confidence=confidence,
        importance=importance,
        expires_at=now + timedelta(days=expires_in_days),
    )


class MemoryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        semantic_expiry_days: int = SEMANTIC_EXPIRY_DAYS,
        episodic_expiry_days: int = EPISODIC_EXPIRY_DAYS,
    ) -> None:
        self.session = session
        self.semantic_expiry_days = semantic_expiry_days
        self.episodic_expiry_days = episodic_expiry_days

    async def _reload(self, memory_id: UUID) -> Memory:
        return (
            (
                await self.session.execute(
                    select(Memory)
                    .where(Memory.id == memory_id)
                    .options(
                        selectinload(Memory.sources).selectinload(MemorySource.document_version),
                        selectinload(Memory.conversation),
                    )
                )
            )
            .scalars()
            .one()
        )

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
        tenant_id, _, _ = _authorized_company(context, company_id)
        sources = await load_authorized_source_chunks(self.session, context.scope, source_chunk_ids)
        if len(sources) != len(source_chunk_ids) or any(
            source.company_id != company_id for source in sources
        ):
            raise APIError(404, "not_found", "Memory source was not found.")
        try:
            acl = derive_memory_acl(
                MemoryScope(requested_scope),
                tuple((item.department, item.visibility, item.classification) for item in sources),
            )
        except (ValueError, MemoryPolicyError):
            raise APIError(
                422, "invalid_memory_scope", "Memory scope is incompatible with its sources."
            ) from None
        now = datetime.now(UTC)
        memory = Memory(
            tenant_id=tenant_id,
            company_id=company_id,
            scope=acl.scope.value,
            owner_user_id=(
                context.identity.user_id if acl.scope is MemoryScope.PRIVATE_USER else None
            ),
            created_by_user_id=context.identity.user_id,
            memory_type=MemoryType.SEMANTIC.value,
            origin=MemoryOrigin.EXPLICIT_USER.value,
            status=MemoryStatus.ACTIVE.value,
            department=acl.department,
            visibility=acl.visibility,
            classification=acl.classification,
            content=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            reason="Manually saved by the user",
            confidence=1.0,
            importance=0.5,
            expires_at=now + timedelta(days=expires_in_days),
        )
        memory.sources = [
            MemorySource(
                chunk_id=item.id,
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                tenant_id=item.tenant_id,
                company_id=item.company_id,
                department=item.department,
                visibility=item.visibility,
                classification=item.classification,
            )
            for item in sources
        ]
        self.session.add(memory)
        await self.session.flush()
        _audit(self.session, context, memory, "CREATE", "MANUAL_USER_CREATE")
        await self.session.commit()
        return _memory_data(await self._reload(memory.id), context=context)

    async def inspect(
        self,
        context: AuthorizationContext,
        *,
        memory_type: str | None = None,
        status: str | None = None,
    ) -> MemoryListData:
        _require_query_capability(context)
        rows = await list_visible_memories(
            self.session,
            context.scope,
            memory_types=(memory_type,) if memory_type else None,
            statuses=(status,)
            if status
            else (
                MemoryStatus.ACTIVE.value,
                MemoryStatus.PENDING_CONFIRMATION.value,
                MemoryStatus.SUPERSEDED.value,
            ),
        )
        record_memory_event(context, action="inspect", outcome="allow", result_count=len(rows))
        return MemoryListData(memories=tuple(_memory_data(item, context=context) for item in rows))

    async def search(
        self, context: AuthorizationContext, *, query: str, top_k: int
    ) -> MemoryListData:
        _require_query_capability(context)
        rows = await search_visible_memories(self.session, context.scope, query=query, top_k=top_k)
        record_memory_event(context, action="search", outcome="allow", result_count=len(rows))
        return MemoryListData(memories=tuple(_memory_data(item, context=context) for item in rows))

    async def retrieve_relevant(
        self,
        context: AuthorizationContext,
        *,
        query: str,
        semantic_limit: int,
        episodic_limit: int,
    ) -> tuple[Memory, ...]:
        _require_query_capability(context)
        semantic = await relevant_semantic_preferences(
            self.session, context.scope, query=query, limit=semantic_limit
        )
        episodic = await relevant_authorized_episodes(
            self.session, context.scope, query=query, limit=episodic_limit
        )
        rows = tuple({item.id: item for item in (*semantic, *episodic)}.values())
        now = datetime.now(UTC)
        for item in rows:
            item.last_accessed_at = now
        return rows

    async def latest_episode(self, context: AuthorizationContext) -> Memory | None:
        _require_query_capability(context)
        episode = await most_recent_authorized_episode(self.session, context.scope)
        record_memory_event(
            context,
            action="search",
            outcome="allow",
            result_count=1 if episode is not None else 0,
        )
        if episode is not None:
            episode.last_accessed_at = datetime.now(UTC)
        return episode

    async def relevant_episodes(
        self, context: AuthorizationContext, *, query: str, limit: int = 3
    ) -> tuple[Memory, ...]:
        _require_query_capability(context)
        episodes = await relevant_authorized_episodes(
            self.session, context.scope, query=query, limit=limit
        )
        now = datetime.now(UTC)
        for episode in episodes:
            episode.last_accessed_at = now
        return episodes

    async def apply_semantic_candidates(
        self,
        context: AuthorizationContext,
        *,
        candidates: tuple[MemoryCandidate, ...],
        company_id: UUID,
        conversation_id: UUID,
        source_message_id: UUID,
    ) -> tuple[str, ...]:
        _require_query_capability(context)
        tenant_id, _, _ = _authorized_company(context, company_id)
        notifications: list[str] = []
        for candidate in candidates[:3]:
            content = " ".join(candidate.content.split())
            if (
                candidate.memory_type != MemoryType.SEMANTIC.value
                or candidate.action not in {CandidateAction.ADD, CandidateAction.SUPERSEDE}
                or not _SAFE_KEY.fullmatch(candidate.normalized_key)
                or not content
                or len(content) > MAX_AUTOMATIC_CONTENT
                or candidate.sensitivity.upper() not in {"LOW", "NONE"}
                or _SENSITIVE.search(content)
            ):
                continue
            existing = (
                (
                    await self.session.execute(
                        select(Memory)
                        .where(
                            Memory.tenant_id == tenant_id,
                            Memory.company_id == company_id,
                            Memory.owner_user_id == context.identity.user_id,
                            Memory.scope == MemoryScope.PRIVATE_USER.value,
                            Memory.memory_type == MemoryType.SEMANTIC.value,
                            Memory.normalized_key == candidate.normalized_key,
                            Memory.status == MemoryStatus.ACTIVE.value,
                            Memory.deleted_at.is_(None),
                        )
                        .order_by(Memory.created_at.desc())
                    )
                )
                .scalars()
                .first()
            )
            now = datetime.now(UTC)
            digest = hashlib.sha256(content.encode()).hexdigest()
            if existing is not None and existing.content_hash == digest:
                if candidate.explicit:
                    existing.expires_at = now + timedelta(days=self.semantic_expiry_days)
                    existing.last_accessed_at = now
                    _audit(self.session, context, existing, "REFRESH", "EXPLICIT_RECONFIRMATION")
                    notifications.append("Private preference remembered")
                continue
            status = (
                MemoryStatus.ACTIVE if candidate.explicit else MemoryStatus.PENDING_CONFIRMATION
            )
            memory = _base_private_memory(
                context,
                tenant_id=tenant_id,
                company_id=company_id,
                content=content,
                memory_type=MemoryType.SEMANTIC,
                origin=MemoryOrigin.EXPLICIT_USER
                if candidate.explicit
                else MemoryOrigin.AUTOMATIC_EXTRACTOR,
                status=status,
                expires_in_days=self.semantic_expiry_days,
                reason=candidate.reason[:240],
                normalized_key=candidate.normalized_key,
                confidence=candidate.confidence,
                importance=candidate.importance,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
            )
            self.session.add(memory)
            await self.session.flush()
            _audit(self.session, context, memory, "CREATE", "AUTOMATIC_CANDIDATE_ACCEPTED")
            if existing is not None:
                existing.status = MemoryStatus.SUPERSEDED.value
                existing.superseded_by_id = memory.id
                _audit(self.session, context, existing, "SUPERSEDE", "PREFERENCE_CHANGED")
            notifications.append(
                "Private preference remembered"
                if status is MemoryStatus.ACTIVE
                else "Preference awaiting confirmation"
            )
        return tuple(dict.fromkeys(notifications))

    async def create_episode(
        self,
        context: AuthorizationContext,
        *,
        company_id: UUID,
        conversation_id: UUID,
        source_message_id: UUID,
        question: str,
        outcome: str,
        source_chunk_ids: tuple[UUID, ...],
        agent_run_id: UUID | None = None,
    ) -> None:
        if not source_chunk_ids or len(question) < 12:
            return
        tenant_id, _, _ = _authorized_company(context, company_id)
        sources = await load_authorized_source_chunks(self.session, context.scope, source_chunk_ids)
        if len(sources) != len(source_chunk_ids) or any(
            item.company_id != company_id for item in sources
        ):
            return
        acl_tuples = {(item.department, item.visibility, item.classification) for item in sources}
        if len(acl_tuples) != 1:
            return
        content = f"Goal: {question[:180]} Outcome: {outcome[:220]}"[:500]
        memory = _base_private_memory(
            context,
            tenant_id=tenant_id,
            company_id=company_id,
            content=content,
            memory_type=MemoryType.EPISODIC,
            origin=MemoryOrigin.AUTOMATIC_EXTRACTOR,
            status=MemoryStatus.ACTIVE,
            expires_in_days=self.episodic_expiry_days,
            reason="Useful completed grounded chat with authorized document sources",
            normalized_key=None,
            confidence=0.9,
            importance=0.7,
            conversation_id=conversation_id,
            source_message_id=source_message_id,
            agent_run_id=agent_run_id,
        )
        department, visibility, classification = next(iter(acl_tuples))
        memory.department = department
        memory.visibility = visibility
        memory.classification = classification
        memory.sources = [
            MemorySource(
                chunk_id=item.id,
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                tenant_id=item.tenant_id,
                company_id=item.company_id,
                department=item.department,
                visibility=item.visibility,
                classification=item.classification,
            )
            for item in sources
        ]
        self.session.add(memory)
        await self.session.flush()
        _audit(self.session, context, memory, "CREATE", "GROUNDED_EPISODE_CREATED")

    async def upsert_conversation_summary(
        self,
        context: AuthorizationContext,
        *,
        company_id: UUID,
        conversation_id: UUID,
        summary: str,
    ) -> None:
        tenant_id, _, _ = _authorized_company(context, company_id)
        existing = (
            (
                await self.session.execute(
                    select(Memory).where(
                        Memory.tenant_id == tenant_id,
                        Memory.owner_user_id == context.identity.user_id,
                        Memory.conversation_id == conversation_id,
                        Memory.memory_type == MemoryType.CONVERSATION_SUMMARY.value,
                        Memory.status == MemoryStatus.ACTIVE.value,
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        content = " ".join(summary.split())[:1000]
        if existing is None:
            existing = _base_private_memory(
                context,
                tenant_id=tenant_id,
                company_id=company_id,
                content=content,
                memory_type=MemoryType.CONVERSATION_SUMMARY,
                origin=MemoryOrigin.SYSTEM_SUMMARY,
                status=MemoryStatus.ACTIVE,
                expires_in_days=SUMMARY_EXPIRY_DAYS,
                reason="Rolling bounded conversation summary",
                normalized_key=f"conversation_summary_{conversation_id}",
                confidence=1.0,
                importance=0.5,
                conversation_id=conversation_id,
            )
            self.session.add(existing)
            await self.session.flush()
            _audit(self.session, context, existing, "CREATE", "SUMMARY_CREATED")
        else:
            existing.content = content
            existing.content_hash = hashlib.sha256(content.encode()).hexdigest()
            existing.expires_at = datetime.now(UTC) + timedelta(days=SUMMARY_EXPIRY_DAYS)

    async def get_conversation_summary(
        self, context: AuthorizationContext, *, conversation_id: UUID
    ) -> str | None:
        row = await owned_conversation_summary(
            self.session,
            context.scope,
            conversation_id=conversation_id,
        )
        return row.content if row is not None else None

    async def confirm(self, context: AuthorizationContext, *, memory_id: UUID) -> MemoryData:
        memory = await get_visible_memory(self.session, context.scope, memory_id)
        if (
            memory is None
            or memory.owner_user_id != context.identity.user_id
            or memory.status != MemoryStatus.PENDING_CONFIRMATION.value
        ):
            raise APIError(404, "not_found", "Memory was not found.")
        memory.status = MemoryStatus.ACTIVE.value
        memory.expires_at = datetime.now(UTC) + timedelta(days=self.semantic_expiry_days)
        _audit(self.session, context, memory, "CONFIRM", "USER_CONFIRMED")
        await self.session.commit()
        return _memory_data(await self._reload(memory.id), context=context)

    async def dismiss(self, context: AuthorizationContext, *, memory_id: UUID) -> DeletedMemoryData:
        memory = await get_visible_memory(self.session, context.scope, memory_id)
        if (
            memory is None
            or memory.owner_user_id != context.identity.user_id
            or memory.status != MemoryStatus.PENDING_CONFIRMATION.value
        ):
            raise APIError(404, "not_found", "Memory was not found.")
        memory.status = MemoryStatus.DELETED.value
        memory.deleted_at = datetime.now(UTC)
        _audit(self.session, context, memory, "DISMISS", "USER_DISMISSED")
        await self.session.commit()
        return DeletedMemoryData(memory_id=memory_id)

    async def delete(self, context: AuthorizationContext, *, memory_id: UUID) -> DeletedMemoryData:
        _require_query_capability(context)
        memory = await get_visible_memory(self.session, context.scope, memory_id)
        if memory is None or memory.created_by_user_id != context.identity.user_id:
            raise APIError(404, "not_found", "Memory was not found.")
        memory.status = MemoryStatus.DELETED.value
        memory.deleted_at = datetime.now(UTC)
        _audit(self.session, context, memory, "DELETE", "USER_DELETE")
        await self.session.commit()
        record_memory_event(
            context, action="delete", outcome="allow", memory_id=memory.id, scope=memory.scope
        )
        return DeletedMemoryData(memory_id=memory_id)
