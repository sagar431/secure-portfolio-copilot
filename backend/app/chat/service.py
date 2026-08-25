import hashlib
import logging
import time
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.contracts import (
    GroundedAnswerDraft,
    GroundedEvidence,
    GroundedGenerationRequest,
    GroundedMemory,
    GroundedWorkingMessage,
    LLMErrorCode,
    LLMProvider,
    LLMProviderError,
    LLMUsage,
)
from app.chat.intent import IntentRouter, RequestIntent, obvious_intent
from app.chat.repository import (
    add_message,
    add_trace,
    bounded_user_messages_for_conversations,
    count_owned_conversation_messages,
    create_chat_message_request,
    create_conversation,
    get_chat_message_request,
    get_owned_conversation,
    list_owned_conversations,
    load_bounded_conversation_messages,
)
from app.chat.scope_guard import request_matches_authorized_scope, resolve_home_tenant_id
from app.chat.streaming import (
    ChatProgressCallback,
    MemoryLoaded,
    RetrievalCompleted,
    RetrievalStarted,
    RouteSelected,
)
from app.core.errors import APIError
from app.memory.contracts import (
    ConversationSummarizer,
    ConversationSummaryRequest,
    MemoryCandidateExtractor,
    MemoryExtractionRequest,
)
from app.memory.extractor import DeterministicMemoryCandidateExtractor
from app.memory.repository import list_visible_memories, resolve_authorized_company_ids
from app.memory.service import MemoryService
from app.memory.summarizer import DeterministicConversationSummarizer
from app.model_routing import ResponseMode, RoutingSignals, WorkloadKind, route_model
from app.models.chat import ChatMessageRequest, Conversation, Message
from app.models.identity import Capability
from app.policies.models import AuthorizationContext
from app.retrieval.service import AuthorizedSearchService
from app.schemas.chat import (
    ConversationData,
    ConversationListData,
    ConversationMessageData,
    ConversationMessagesData,
    CreatedConversationData,
    GroundedCitationData,
    GroundedClaimData,
    GroundedMessageData,
    safe_model_name,
)
from app.schemas.retrieval import AuthorizedSearchResultData

logger = logging.getLogger("app.chat.audit")

INSUFFICIENT_ANSWER = "I don't have sufficient authorized evidence to answer that question."


class GroundingValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__("Grounded answer validation failed safely.")
        self.code = code


@dataclass(frozen=True, slots=True)
class _ValidatedAnswer:
    claims: tuple[GroundedClaimData, ...]
    citations: tuple[GroundedCitationData, ...]
    limitations: tuple[str, ...]


def _conversation_data(
    conversation: Conversation, *, title_override: str | None = None
) -> ConversationData:
    return ConversationData(
        id=conversation.id,
        title=title_override or conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _conversation_title(question: str) -> str:
    normalized = " ".join(question.split()).strip(" .?!")
    if len(normalized) <= 64:
        return normalized
    return normalized[:61].rstrip() + "…"


def _first_meaningful_title(messages: tuple[str, ...]) -> str | None:
    for message in messages:
        route = obvious_intent(message, scope_allowed=True)
        if route is None or route.intent != RequestIntent.CASUAL:
            return _conversation_title(message)
    return None


def _evidence_from_result(result: AuthorizedSearchResultData, evidence_id: str) -> GroundedEvidence:
    citation = result.citation
    source = result.source
    if (
        citation.document_id != result.document_id
        or citation.document_version_id != result.document_version_id
        or citation.chunk_id != result.chunk_id
        or citation.version_number != result.version_number
        or citation.excerpt != result.excerpt
        or citation.page_number != source.page_number
        or citation.sheet_name != source.sheet_name
        or citation.row_start != source.row_start
        or citation.row_end != source.row_end
        or citation.cell_start != source.cell_start
        or citation.cell_end != source.cell_end
    ):
        raise GroundingValidationError("PROVENANCE_INCONSISTENT")
    return GroundedEvidence(
        evidence_id=evidence_id,
        chunk_id=result.chunk_id,
        document_id=result.document_id,
        document_version_id=result.document_version_id,
        version_number=result.version_number,
        document_title=citation.document_title,
        excerpt=result.excerpt,
        page_number=source.page_number,
        sheet_name=source.sheet_name,
        row_start=source.row_start,
        row_end=source.row_end,
        cell_start=source.cell_start,
        cell_end=source.cell_end,
    )


def validate_grounded_answer(
    draft: GroundedAnswerDraft, evidence: tuple[GroundedEvidence, ...]
) -> _ValidatedAnswer:
    if draft.status != "supported" or not draft.claims:
        raise GroundingValidationError("PROVIDER_UNSUPPORTED")
    by_id = {item.evidence_id: item for item in evidence}
    if len(by_id) != len(evidence):
        raise GroundingValidationError("EVIDENCE_IDS_DUPLICATE")
    claims: list[GroundedClaimData] = []
    referenced: set[str] = set()
    for draft_claim in draft.claims:
        text = " ".join(draft_claim.text.split())
        citation_ids = tuple(dict.fromkeys(draft_claim.evidence_ids))
        if not text or len(text) > 500 or not citation_ids:
            raise GroundingValidationError("CLAIM_INVALID")
        if any(item not in by_id for item in citation_ids):
            raise GroundingValidationError("UNKNOWN_EVIDENCE")
        referenced.update(citation_ids)
        claims.append(GroundedClaimData(text=text, citation_ids=citation_ids))
    citations = tuple(
        GroundedCitationData(
            citation_id=item.evidence_id,
            document_id=item.document_id,
            document_version_id=item.document_version_id,
            chunk_id=item.chunk_id,
            document_title=item.document_title,
            version_number=item.version_number,
            excerpt=item.excerpt,
            page_number=item.page_number,
            sheet_name=item.sheet_name,
            row_start=item.row_start,
            row_end=item.row_end,
            cell_start=item.cell_start,
            cell_end=item.cell_end,
        )
        for item in evidence
        if item.evidence_id in referenced
    )
    if {item.citation_id for item in citations} != referenced:
        raise GroundingValidationError("RECONSTRUCTION_INCOMPLETE")
    limitations = tuple(
        normalized for item in draft.limitations[:5] if (normalized := " ".join(item.split())[:300])
    )
    return _ValidatedAnswer(tuple(claims), citations, limitations)


def _sufficient_results(
    results: tuple[AuthorizedSearchResultData, ...],
) -> tuple[AuthorizedSearchResultData, ...]:
    lexical = tuple(item for item in results if item.scores.keyword > 0)
    relevant = lexical or tuple(item for item in results if item.scores.vector >= 0.25)
    if not relevant:
        return ()
    return relevant


def _episode_goal(content: str) -> str:
    """Recover the prior goal without treating a historical outcome as current evidence."""
    normalized = " ".join(content.split())
    if normalized.startswith("Goal: "):
        goal, separator, _ = normalized[6:].partition(" Outcome: ")
        if separator and goal:
            return goal[:180]
    return normalized[:180]


class GroundedChatService:
    def __init__(
        self,
        session: AsyncSession,
        search_service: AuthorizedSearchService,
        llm_provider: LLMProvider,
        memory_extractor: MemoryCandidateExtractor | None = None,
        intent_router: IntentRouter | None = None,
        conversation_summarizer: ConversationSummarizer | None = None,
        *,
        max_evidence_chunks: int,
        max_memory_items: int = 0,
        max_recent_messages: int = 8,
        max_memory_context_chars: int = 2400,
        semantic_expiry_days: int = 90,
        episodic_expiry_days: int = 30,
        low_confidence_threshold: float = 0.55,
    ) -> None:
        self.session = session
        self.search_service = search_service
        self.llm_provider = llm_provider
        self.memory_extractor = memory_extractor or DeterministicMemoryCandidateExtractor()
        self.intent_router = intent_router or IntentRouter()
        self.conversation_summarizer = (
            conversation_summarizer or DeterministicConversationSummarizer()
        )
        self.memory_service = MemoryService(
            session,
            semantic_expiry_days=semantic_expiry_days,
            episodic_expiry_days=episodic_expiry_days,
        )
        self.max_evidence_chunks = max_evidence_chunks
        self.max_memory_items = max_memory_items
        self.max_recent_messages = max_recent_messages
        self.max_memory_context_chars = max_memory_context_chars
        self.low_confidence_threshold = low_confidence_threshold

    async def create(
        self, context: AuthorizationContext, *, title: str | None
    ) -> CreatedConversationData:
        tenant_id = resolve_home_tenant_id(context)
        conversation = await create_conversation(
            self.session,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
            title=title or "New conversation",
        )
        await self.session.commit()
        return CreatedConversationData(conversation=_conversation_data(conversation))

    async def list(self, context: AuthorizationContext) -> ConversationListData:
        tenant_id = resolve_home_tenant_id(context)
        conversations = await list_owned_conversations(
            self.session,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
        )
        legacy_ids = tuple(
            item.id for item in conversations if item.title in {"Evaluation", "New conversation"}
        )
        legacy_messages = await bounded_user_messages_for_conversations(
            self.session,
            conversation_ids=legacy_ids,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
        )
        return ConversationListData(
            conversations=tuple(
                _conversation_data(
                    item,
                    title_override=(
                        _first_meaningful_title(legacy_messages[item.id])
                        if item.id in legacy_messages
                        else None
                    ),
                )
                for item in conversations
            )
        )

    async def history(
        self, context: AuthorizationContext, *, conversation_id: UUID, limit: int
    ) -> ConversationMessagesData:
        tenant_id = resolve_home_tenant_id(context)
        conversation = await get_owned_conversation(
            self.session,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
        )
        if conversation is None:
            raise APIError(404, "not_found", "Conversation was not found.")
        rows = await load_bounded_conversation_messages(
            self.session,
            conversation_id=conversation.id,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
            limit=limit,
        )
        total = await count_owned_conversation_messages(
            self.session,
            conversation_id=conversation.id,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
        )
        return ConversationMessagesData(
            messages=tuple(
                ConversationMessageData(
                    id=item.id,
                    role=item.role,  # type: ignore[arg-type]
                    content=item.content,
                    created_at=item.created_at,
                )
                for item in rows
            ),
            has_more=total > len(rows),
        )

    async def answer(
        self,
        context: AuthorizationContext,
        *,
        conversation_id: UUID,
        question: str,
        response_mode: ResponseMode = ResponseMode.AUTO,
        request_id: str,
        progress: ChatProgressCallback | None = None,
        client_message_id: UUID | None = None,
    ) -> GroundedMessageData:
        started = time.monotonic()
        tenant_id = resolve_home_tenant_id(context)
        conversation = await get_owned_conversation(
            self.session,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
        )
        if conversation is None:
            raise APIError(404, "not_found", "Conversation was not found.")
        if not any(
            Capability.QUERY_DOCUMENTS in grant.capabilities for grant in context.scope.grants
        ):
            raise APIError(403, "forbidden", "Grounded chat is not permitted.")

        delivery: ChatMessageRequest | None = None
        if client_message_id is not None:
            normalized_question = " ".join(question.split())
            request_fingerprint = hashlib.sha256(
                f"{response_mode.value}\0{normalized_question}".encode()
            ).hexdigest()
            existing = await get_chat_message_request(
                self.session,
                conversation_id=conversation.id,
                tenant_id=tenant_id,
                user_id=context.identity.user_id,
                client_message_id=client_message_id,
            )
            if existing is not None:
                if existing.request_fingerprint != request_fingerprint:
                    raise APIError(
                        409,
                        "idempotency_conflict",
                        "That message identifier was already used for different content.",
                    )
                if existing.status == "COMPLETED" and existing.response_payload is not None:
                    replay = GroundedMessageData.model_validate(existing.response_payload)
                    if progress is not None:
                        progress(RouteSelected(intent=replay.intent_route))
                    return replay
                raise APIError(
                    409,
                    "message_already_processing",
                    "That message is already processing or previously failed safely.",
                )
            delivery = await create_chat_message_request(
                self.session,
                conversation_id=conversation.id,
                tenant_id=tenant_id,
                user_id=context.identity.user_id,
                client_message_id=client_message_id,
                request_fingerprint=request_fingerprint,
            )

        scope_allowed = request_matches_authorized_scope(context, question)
        route = obvious_intent(question, scope_allowed=scope_allowed)
        recent_rows: tuple[Message, ...] = ()
        if route is None:
            recent_rows = (
                await load_bounded_conversation_messages(
                    self.session,
                    conversation_id=conversation.id,
                    tenant_id=tenant_id,
                    user_id=context.identity.user_id,
                    limit=self.max_recent_messages,
                )
                if hasattr(self.session, "execute")
                else ()
            )
            route = await self.intent_router.classify(
                query=question,
                scope_allowed=scope_allowed,
                has_recent_conversation=bool(recent_rows),
            )
        assert route is not None
        if progress is not None:
            progress(RouteSelected(intent=route.intent))
        if (
            getattr(conversation, "title", None) == "New conversation"
            and route.intent != RequestIntent.CASUAL
        ):
            conversation.title = _conversation_title(question)
        recent_messages = tuple(
            GroundedWorkingMessage(role=item.role, content=item.content[:500])  # type: ignore[arg-type]
            for item in recent_rows
        )
        conversation_summary = (
            await self.memory_service.get_conversation_summary(
                context, conversation_id=conversation.id
            )
            if hasattr(self.session, "execute")
            else None
        )

        if route.intent == RequestIntent.CASUAL:
            user_message = await add_message(
                self.session,
                conversation=conversation,
                user_id=context.identity.user_id,
                role="user",
                content=question,
                request_id=request_id,
            )
            first_name = context.identity.display_name.split()[0]
            home_grant = next(
                grant
                for grant in context.scope.grants
                if Capability.QUERY_DOCUMENTS in grant.capabilities
            )
            workspace_label = home_grant.workspace_slug.replace("-", " ").title()
            work_label = f"{workspace_label} {home_grant.primary_department.title()}"
            return await self._persist_answer(
                context=context,
                delivery=delivery,
                conversation=conversation,
                user_message_id=user_message.id,
                request_id=request_id,
                status="casual",
                intent_route=route.intent,
                answer=(
                    f"Hi {first_name}! I’m ready to help with your authorized {work_label} work. "
                    "You can ask about documents, calculations, memories, or continue recent work."
                ),
                claims=(),
                citations=(),
                limitations=(),
                evidence=(),
                usage=LLMUsage(
                    latency_ms=int((time.monotonic() - started) * 1000),
                    requested_response_mode=response_mode,
                ),
                reason_code=route.reason_code,
            )

        if route.intent == RequestIntent.MEMORY_WRITE:
            user_message = await add_message(
                self.session,
                conversation=conversation,
                user_id=context.identity.user_id,
                role="user",
                content=question,
                request_id=request_id,
            )
            memory_notifications = await self._extract_semantic_safely(
                context,
                conversation=conversation,
                user_message_id=user_message.id,
                question=question,
                assistant_text="Preference acknowledged.",
                company_ids=self._single_authorized_company_ids(context),
                request_id=request_id,
            )
            return await self._persist_answer(
                context=context,
                delivery=delivery,
                conversation=conversation,
                user_message_id=user_message.id,
                request_id=request_id,
                status="memory_write",
                intent_route=route.intent,
                answer=(
                    "I’ll remember that private preference."
                    if memory_notifications
                    else "I couldn’t safely save that as a stable private preference."
                ),
                claims=(),
                citations=(),
                limitations=(),
                evidence=(),
                usage=LLMUsage(
                    latency_ms=int((time.monotonic() - started) * 1000),
                    requested_response_mode=response_mode,
                ),
                reason_code=route.reason_code,
                memory_notifications=memory_notifications,
            )

        if route.intent == RequestIntent.MEMORY_RECALL and not route.requires_regrounding:
            user_message = await add_message(
                self.session,
                conversation=conversation,
                user_id=context.identity.user_id,
                role="user",
                content=question,
                request_id=request_id,
            )
            episode = await self.memory_service.latest_episode(context)
            answer = (
                "I don’t have a recent authorized investigation in your private memory yet."
                if episode is None
                else (
                    "From your private memory/history: "
                    f"{episode.content} This describes prior activity, not current "
                    "financial facts. "
                    "I can re-run the investigation against current authorized documents."
                )
            )
            return await self._persist_answer(
                context=context,
                delivery=delivery,
                conversation=conversation,
                user_message_id=user_message.id,
                request_id=request_id,
                status="memory_recall",
                intent_route=route.intent,
                answer=answer,
                claims=(),
                citations=(),
                limitations=(
                    "Re-run the investigation before treating prior conclusions as current.",
                )
                if episode is not None
                else (),
                evidence=(),
                usage=LLMUsage(
                    latency_ms=int((time.monotonic() - started) * 1000),
                    requested_response_mode=response_mode,
                ),
                reason_code=route.reason_code,
            )

        if route.intent == RequestIntent.CLARIFICATION:
            user_message = await add_message(
                self.session,
                conversation=conversation,
                user_id=context.identity.user_id,
                role="user",
                content=question,
                request_id=request_id,
            )
            return await self._persist_answer(
                context=context,
                delivery=delivery,
                conversation=conversation,
                user_message_id=user_message.id,
                request_id=request_id,
                status="clarification",
                intent_route=route.intent,
                answer="Which authorized portfolio company and reporting period should I use?",
                claims=(),
                citations=(),
                limitations=(),
                evidence=(),
                usage=LLMUsage(
                    latency_ms=int((time.monotonic() - started) * 1000),
                    requested_response_mode=response_mode,
                ),
                reason_code=route.reason_code,
            )

        if route.intent == RequestIntent.REFUSE:
            user_message = await add_message(
                self.session,
                conversation=conversation,
                user_id=context.identity.user_id,
                role="user",
                content=question,
                request_id=request_id,
            )
            return await self._persist_answer(
                context=context,
                delivery=delivery,
                conversation=conversation,
                user_message_id=user_message.id,
                request_id=request_id,
                status="refused",
                intent_route=route.intent,
                answer="I can’t perform that request within your authorized scope.",
                claims=(),
                citations=(),
                limitations=("The requested scope is not available in authorized evidence.",),
                evidence=(),
                usage=LLMUsage(
                    latency_ms=int((time.monotonic() - started) * 1000),
                    requested_response_mode=response_mode,
                ),
                reason_code=route.reason_code,
            )

        retrieval_query = question
        generation_question = question
        if route.intent == RequestIntent.CONVERSATION_FOLLOW_UP and recent_messages:
            prior_user = next(
                (item.content for item in reversed(recent_messages) if item.role == "user"),
                "",
            )
            retrieval_query = f"{prior_user} {question}"[:1000]
        elif route.intent == RequestIntent.MEMORY_RECALL and route.requires_regrounding:
            episodes = await self.memory_service.relevant_episodes(context, query=question, limit=2)
            if not episodes:
                latest = await self.memory_service.latest_episode(context)
                episodes = (latest,) if latest is not None else ()
            remembered_goals = tuple(_episode_goal(item.content) for item in episodes)
            retrieval_query = " ".join((question, *remembered_goals))[:1000]
            if remembered_goals:
                generation_question = (
                    f"Continue this prior goal using only current authorized evidence: "
                    f"{remembered_goals[0]}"
                )[:1000]
            if progress is not None:
                progress(MemoryLoaded(memory_count=len(episodes)))
        if progress is not None:
            progress(RetrievalStarted())
        search = await self.search_service.search(
            context,
            query=retrieval_query,
            top_k=self.max_evidence_chunks,
            request_id=request_id,
        )
        sufficient_results = _sufficient_results(search.results)
        try:
            evidence = tuple(
                _evidence_from_result(result, f"ev_{index}")
                for index, result in enumerate(sufficient_results, start=1)
            )
        except GroundingValidationError:
            evidence = ()
        if progress is not None:
            progress(RetrievalCompleted(citation_count=len(evidence)))

        if not evidence:
            user_message = await add_message(
                self.session,
                conversation=conversation,
                user_id=context.identity.user_id,
                role="user",
                content=question,
                request_id=request_id,
            )
            memory_notifications = await self._extract_semantic_safely(
                context,
                conversation=conversation,
                user_message_id=user_message.id,
                question=question,
                assistant_text="Preference acknowledged.",
                company_ids=self._single_authorized_company_ids(context),
                request_id=request_id,
            )
            memory_answer = (
                "I’ll remember that private preference."
                if memory_notifications
                else INSUFFICIENT_ANSWER
            )
            company_ids = self._single_authorized_company_ids(context)
            if len(company_ids) == 1 and len(recent_messages) >= self.max_recent_messages:
                await self._summarize_safely(
                    context,
                    conversation=conversation,
                    company_id=company_ids[0],
                    recent_messages=recent_messages,
                    previous_summary=conversation_summary,
                    question=question,
                    answer=memory_answer,
                    request_id=request_id,
                )
            return await self._persist_answer(
                context=context,
                delivery=delivery,
                conversation=conversation,
                user_message_id=user_message.id,
                request_id=request_id,
                status="insufficient_evidence",
                intent_route=route.intent,
                answer=memory_answer,
                claims=(),
                citations=(),
                limitations=("No sufficient authorized evidence was retrieved.",),
                evidence=(),
                usage=LLMUsage(
                    latency_ms=int((time.monotonic() - started) * 1000),
                    requested_response_mode=response_mode,
                ),
                reason_code="INSUFFICIENT_AUTHORIZED_EVIDENCE",
                memory_notifications=memory_notifications,
            )

        evidence_companies = tuple(
            dict.fromkeys(
                (item.document.tenant_slug, item.document.company_slug)
                for item in sufficient_results
            )
        )
        try:
            evidence_company_ids = await resolve_authorized_company_ids(
                self.session, context.scope, evidence_companies=evidence_companies
            )
        except AttributeError:
            evidence_company_ids = tuple(
                company_id
                for grant in context.scope.grants
                for company_id, company_slug in zip(
                    grant.company_ids, grant.company_slugs, strict=True
                )
                if (grant.workspace_slug, company_slug) in evidence_companies
            )
        memories: tuple[GroundedMemory, ...] = ()
        if self.max_memory_items > 0:
            if hasattr(self.session, "execute"):
                visible_memories = await self.memory_service.retrieve_relevant(
                    context,
                    query=question,
                    semantic_limit=min(3, self.max_memory_items),
                    episodic_limit=min(2, self.max_memory_items),
                )
                visible_memories = tuple(
                    item for item in visible_memories if item.company_id in evidence_company_ids
                )[: self.max_memory_items]
            else:
                # Lightweight repository doubles in contract tests retain the pre-existing seam.
                visible_memories = await list_visible_memories(
                    self.session,
                    context.scope,
                    company_ids=evidence_company_ids,
                    limit=self.max_memory_items,
                )
            used_chars = 0
            bounded_memories = []
            for item in visible_memories:
                if used_chars + len(item.content) > self.max_memory_context_chars:
                    continue
                bounded_memories.append(item)
                used_chars += len(item.content)
            memories = tuple(
                GroundedMemory(
                    memory_id=item.id,
                    scope=item.scope,
                    memory_type=getattr(item, "memory_type", "SEMANTIC"),
                    content=item.content,
                )
                for item in bounded_memories
            )
        if progress is not None:
            progress(MemoryLoaded(memory_count=len(memories)))

        routing_signals = RoutingSignals(
            workload=WorkloadKind.GROUNDED_ANSWER,
            question=question,
            authorized_document_count=len({item.document_id for item in sufficient_results}),
            top_retrieval_score=max(item.scores.final for item in sufficient_results),
        )
        routing_decision = route_model(
            routing_signals,
            low_confidence_threshold=self.low_confidence_threshold,
            response_mode=response_mode,
        )
        if routing_decision.upgrade_required:
            raise APIError(
                409,
                "deep_mode_required",
                "This request requires broader analysis.",
            )

        user_message = await add_message(
            self.session,
            conversation=conversation,
            user_id=context.identity.user_id,
            role="user",
            content=question,
            request_id=request_id,
        )

        try:
            generation = await self.llm_provider.generate(
                GroundedGenerationRequest(
                    question=generation_question,
                    evidence=evidence,
                    memories=memories,
                    recent_messages=recent_messages,
                    conversation_summary=conversation_summary,
                    routing=routing_signals,
                    response_mode=response_mode,
                )
            )
        except LLMProviderError as exc:
            add_trace(
                self.session,
                request_id=request_id,
                conversation=conversation,
                user_id=context.identity.user_id,
                model_name=exc.model_name or self.llm_provider.model_name,
                status="provider_error",
                reason_code=f"LLM_{exc.code.value}",
                document_ids=tuple(dict.fromkeys(item.document_id for item in evidence)),
                chunk_ids=tuple(item.chunk_id for item in evidence),
                input_tokens=None,
                output_tokens=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                retry_count=exc.retry_count,
                route_reason_code=exc.route_reason or "PROVIDER_SELECTED",
                fallback_used=exc.fallback_used,
                fallback_reason_code=exc.fallback_reason,
                intent_route=route.intent.value,
            )
            if delivery is not None:
                delivery.status = "FAILED"
            await self.session.commit()
            logger.warning(
                "grounded_chat_event",
                extra={
                    "request_id": request_id,
                    "conversation_id": str(conversation.id),
                    "status": "provider_error",
                    "reason_code": f"LLM_{exc.code.value}",
                },
            )
            if exc.code == LLMErrorCode.TIMEOUT:
                raise APIError(504, "llm_timeout", "The answer service timed out.") from None
            raise APIError(
                503, "llm_unavailable", "The answer service is temporarily unavailable."
            ) from None

        generation = replace(
            generation,
            usage=replace(
                generation.usage,
                route_reason=generation.usage.route_reason or routing_decision.reason.value,
                requested_response_mode=response_mode,
                resolved_response_mode=(
                    generation.usage.resolved_response_mode
                    or routing_decision.resolved_response_mode
                ),
            ),
        )

        try:
            validated = validate_grounded_answer(generation.answer, evidence)
        except GroundingValidationError as exc:
            return await self._persist_answer(
                context=context,
                delivery=delivery,
                conversation=conversation,
                user_message_id=user_message.id,
                request_id=request_id,
                status="insufficient_evidence",
                intent_route=route.intent,
                answer=INSUFFICIENT_ANSWER,
                claims=(),
                citations=(),
                limitations=("The generated answer could not be validated against evidence.",),
                evidence=evidence,
                usage=generation.usage,
                reason_code=f"CITATION_{exc.code}",
            )

        answer = " ".join(
            f"{claim.text} [{', '.join(claim.citation_ids)}]" for claim in validated.claims
        )
        memory_notifications = await self._extract_semantic_safely(
            context,
            conversation=conversation,
            user_message_id=user_message.id,
            question=question,
            assistant_text=answer,
            company_ids=evidence_company_ids,
            request_id=request_id,
        )
        if len(evidence_company_ids) == 1:
            try:
                async with self.session.begin_nested():
                    await self.memory_service.create_episode(
                        context,
                        company_id=evidence_company_ids[0],
                        conversation_id=conversation.id,
                        source_message_id=user_message.id,
                        question=generation_question,
                        outcome=answer,
                        # Episodes inherit ACL/provenance from the evidence that actually
                        # supports the persisted answer. Retrieved distractors may span
                        # departments and must not suppress an otherwise valid episode.
                        source_chunk_ids=tuple(item.chunk_id for item in validated.citations),
                    )
            except Exception:
                logger.warning(
                    "optional_memory_postprocessing_failed",
                    extra={"request_id": request_id, "conversation_id": str(conversation.id)},
                )
            if len(recent_messages) >= self.max_recent_messages:
                await self._summarize_safely(
                    context,
                    conversation=conversation,
                    company_id=evidence_company_ids[0],
                    recent_messages=recent_messages,
                    previous_summary=conversation_summary,
                    question=question,
                    answer=answer,
                    request_id=request_id,
                )
        return await self._persist_answer(
            context=context,
            delivery=delivery,
            conversation=conversation,
            user_message_id=user_message.id,
            request_id=request_id,
            status="grounded",
            intent_route=route.intent,
            answer=answer,
            claims=validated.claims,
            citations=validated.citations,
            limitations=validated.limitations,
            evidence=evidence,
            usage=generation.usage,
            reason_code="GROUNDED_ANSWER_VALIDATED",
            memory_notifications=memory_notifications,
        )

    @staticmethod
    def _single_authorized_company_ids(context: AuthorizationContext) -> tuple[UUID, ...]:
        ids = {
            company_id
            for grant in context.scope.grants
            if Capability.QUERY_DOCUMENTS in grant.capabilities
            for company_id in grant.company_ids
        }
        return tuple(ids) if len(ids) == 1 else ()

    async def _extract_semantic_safely(
        self,
        context: AuthorizationContext,
        *,
        conversation: Conversation,
        user_message_id: UUID,
        question: str,
        assistant_text: str,
        company_ids: tuple[UUID, ...],
        request_id: str,
    ) -> tuple[str, ...]:
        if len(company_ids) != 1:
            return ()
        try:
            candidates = await self.memory_extractor.extract(
                MemoryExtractionRequest(
                    user_text=question,
                    assistant_text=assistant_text,
                    conversation_id=conversation.id,
                    source_message_id=user_message_id,
                )
            )
            async with self.session.begin_nested():
                return await self.memory_service.apply_semantic_candidates(
                    context,
                    candidates=candidates,
                    company_id=company_ids[0],
                    conversation_id=conversation.id,
                    source_message_id=user_message_id,
                )
        except Exception:
            logger.warning(
                "optional_memory_extraction_failed",
                extra={"request_id": request_id, "conversation_id": str(conversation.id)},
            )
            return ()

    async def _summarize_safely(
        self,
        context: AuthorizationContext,
        *,
        conversation: Conversation,
        company_id: UUID,
        recent_messages: tuple[GroundedWorkingMessage, ...],
        previous_summary: str | None,
        question: str,
        answer: str,
        request_id: str,
    ) -> None:
        try:
            summary = await self.conversation_summarizer.summarize(
                ConversationSummaryRequest(
                    messages=tuple((item.role, item.content) for item in recent_messages)
                    + (("user", question), ("assistant", answer)),
                    previous_summary=previous_summary,
                )
            )
            async with self.session.begin_nested():
                await self.memory_service.upsert_conversation_summary(
                    context,
                    company_id=company_id,
                    conversation_id=conversation.id,
                    summary=summary,
                )
        except Exception:
            logger.warning(
                "optional_memory_summary_failed",
                extra={"request_id": request_id, "conversation_id": str(conversation.id)},
            )

    async def _persist_answer(
        self,
        *,
        context: AuthorizationContext,
        delivery: ChatMessageRequest | None,
        conversation: Conversation,
        user_message_id: UUID,
        request_id: str,
        status: Literal[
            "grounded",
            "insufficient_evidence",
            "casual",
            "memory_recall",
            "memory_write",
            "clarification",
            "refused",
        ],
        answer: str,
        claims: tuple[GroundedClaimData, ...],
        citations: tuple[GroundedCitationData, ...],
        limitations: tuple[str, ...],
        evidence: tuple[GroundedEvidence, ...],
        usage: LLMUsage,
        reason_code: str,
        memory_notifications: tuple[str, ...] = (),
        intent_route: RequestIntent = RequestIntent.DOCUMENT_QUESTION,
    ) -> GroundedMessageData:
        assistant_message = await add_message(
            self.session,
            conversation=conversation,
            user_id=context.identity.user_id,
            role="assistant",
            content=answer,
            request_id=request_id,
        )
        trace_status = (
            "grounded"
            if status in {"grounded", "casual", "memory_recall", "memory_write"}
            else "insufficient_evidence"
        )
        model_was_called = usage.resolved_response_mode is not None
        trace_model_name = (
            usage.model_name or self.llm_provider.model_name
            if model_was_called
            else "NO_MODEL_CALL"
        )
        add_trace(
            self.session,
            request_id=request_id,
            conversation=conversation,
            user_id=context.identity.user_id,
            model_name=trace_model_name,
            status=trace_status,
            reason_code=reason_code,
            document_ids=tuple(dict.fromkeys(item.document_id for item in evidence)),
            chunk_ids=tuple(item.chunk_id for item in evidence),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            retry_count=usage.retry_count,
            route_reason_code=(
                usage.route_reason or "PROVIDER_SELECTED" if model_was_called else "NO_MODEL_CALL"
            ),
            fallback_used=usage.fallback_used,
            fallback_reason_code=usage.fallback_reason,
            intent_route=intent_route.value,
        )
        result = GroundedMessageData(
            conversation_id=conversation.id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message.id,
            status=status,
            intent_route=intent_route,
            answer=answer,
            claims=claims,
            citations=citations,
            limitations=limitations,
            model_name=(
                safe_model_name(usage.model_name or self.llm_provider.model_name)
                if model_was_called
                else None
            ),
            route_reason=usage.route_reason,
            fallback_used=usage.fallback_used,
            requested_response_mode=usage.requested_response_mode,
            resolved_response_mode=usage.resolved_response_mode,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            estimated_model_cost_usd=None,
            pricing_snapshot_date=None,
            memory_notifications=memory_notifications,
        )
        if delivery is not None:
            delivery.status = "COMPLETED"
            delivery.response_payload = result.model_dump(mode="json")
        await self.session.commit()
        logger.info(
            "grounded_chat_event",
            extra={
                "request_id": request_id,
                "conversation_id": str(conversation.id),
                "status": trace_status,
                "reason_code": reason_code,
                "evidence_count": len(evidence),
                "citation_count": len(citations),
            },
        )
        return result
