import logging
import re
import time
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.contracts import (
    GroundedAnswerDraft,
    GroundedEvidence,
    GroundedGenerationRequest,
    LLMErrorCode,
    LLMProvider,
    LLMProviderError,
    LLMUsage,
)
from app.chat.repository import (
    add_message,
    add_trace,
    create_conversation,
    get_owned_conversation,
    list_owned_conversations,
)
from app.core.errors import APIError
from app.models.chat import Conversation
from app.models.identity import Capability
from app.policies.models import AuthorizationContext
from app.retrieval.service import AuthorizedSearchService
from app.schemas.chat import (
    ConversationData,
    ConversationListData,
    CreatedConversationData,
    GroundedCitationData,
    GroundedClaimData,
    GroundedMessageData,
)
from app.schemas.retrieval import AuthorizedSearchResultData

logger = logging.getLogger("app.chat.audit")

INSUFFICIENT_ANSWER = "I don't have sufficient authorized evidence to answer that question."
_TARGET_BEFORE_DOMAIN = re.compile(
    r"\b([a-z0-9_-]+)(?:'s)?\s+"
    r"(?:finance|financial|legal|company|portfolio|documents?|data)\b",
    re.IGNORECASE,
)
_TARGET_BEFORE_METRIC = re.compile(
    r"(?:^|\bwhat\s+(?:was|is)|\bwhy\s+did|\bshow\s+me|\bsummarize)\s+"
    r"([a-z0-9_-]+)(?:'s)?\s+"
    r"(?:revenue|ebitda|margin|agreement|contract|board)\b",
    re.IGNORECASE,
)
_TARGET_AFTER_PREPOSITION = re.compile(r"\b(?:for|from|about|at)\s+([a-z0-9_-]+)\b", re.IGNORECASE)
_TARGET_STOP_WORDS = {
    "authorized",
    "company",
    "document",
    "documents",
    "ebitda",
    "evidence",
    "financial",
    "gross",
    "is",
    "legal",
    "margin",
    "me",
    "my",
    "net",
    "operating",
    "of",
    "our",
    "portfolio",
    "revenue",
    "the",
    "this",
    "was",
    "were",
}


class GroundingValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _ValidatedAnswer:
    claims: tuple[GroundedClaimData, ...]
    citations: tuple[GroundedCitationData, ...]
    limitations: tuple[str, ...]


def _home_tenant_id(context: AuthorizationContext) -> UUID:
    tenant_ids = {grant.home_tenant_id for grant in context.scope.grants}
    if len(tenant_ids) != 1:
        raise APIError(403, "forbidden", "Conversation access is not permitted.")
    return next(iter(tenant_ids))


def _conversation_data(conversation: Conversation) -> ConversationData:
    return ConversationData(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


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
        raise GroundingValidationError("Retrieved citation provenance is inconsistent.")
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
        raise GroundingValidationError("The provider did not return a supported answer.")
    by_id = {item.evidence_id: item for item in evidence}
    if len(by_id) != len(evidence):
        raise GroundingValidationError("Evidence IDs are not unique.")
    claims: list[GroundedClaimData] = []
    referenced: set[str] = set()
    for draft_claim in draft.claims:
        text = " ".join(draft_claim.text.split())
        citation_ids = tuple(dict.fromkeys(draft_claim.evidence_ids))
        if not text or len(text) > 500 or not citation_ids:
            raise GroundingValidationError("Every claim must be bounded and cited.")
        if any(item not in by_id for item in citation_ids):
            raise GroundingValidationError("A claim references evidence that was not retrieved.")
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
        raise GroundingValidationError("Citation reconstruction was incomplete.")
    limitations = tuple(
        normalized for item in draft.limitations[:5] if (normalized := " ".join(item.split())[:300])
    )
    return _ValidatedAnswer(tuple(claims), citations, limitations)


def _request_matches_scope(context: AuthorizationContext, question: str) -> bool:
    query_tokens = set(re.findall(r"[a-z0-9_-]+", question.casefold()))
    authorized_departments = {
        department.key.casefold()
        for grant in context.scope.grants
        if Capability.QUERY_DOCUMENTS in grant.capabilities
        for department in grant.departments
    }
    requested_departments = query_tokens.intersection({"finance", "legal", "shared"})
    if not requested_departments.issubset(authorized_departments):
        return False
    authorized_targets = {
        token
        for grant in context.scope.grants
        if Capability.QUERY_DOCUMENTS in grant.capabilities
        for value in (grant.workspace_slug, *grant.company_slugs)
        for token in (value.casefold(), value.casefold().split("-", 1)[0])
    }
    target_hints = {
        match.group(1).casefold()
        for pattern in (
            _TARGET_BEFORE_DOMAIN,
            _TARGET_BEFORE_METRIC,
            _TARGET_AFTER_PREPOSITION,
        )
        for match in pattern.finditer(question)
        if match.group(1).casefold() not in _TARGET_STOP_WORDS
        and not re.fullmatch(r"fy\d{4}", match.group(1), re.IGNORECASE)
    }
    return not target_hints or target_hints.issubset(authorized_targets)


def _sufficient_results(
    results: tuple[AuthorizedSearchResultData, ...],
) -> tuple[AuthorizedSearchResultData, ...]:
    relevant = tuple(
        item for item in results if item.scores.keyword > 0 or item.scores.vector >= 0.25
    )
    if not relevant:
        return ()
    return relevant


class GroundedChatService:
    def __init__(
        self,
        session: AsyncSession,
        search_service: AuthorizedSearchService,
        llm_provider: LLMProvider,
        *,
        max_evidence_chunks: int,
    ) -> None:
        self.session = session
        self.search_service = search_service
        self.llm_provider = llm_provider
        self.max_evidence_chunks = max_evidence_chunks

    async def create(
        self, context: AuthorizationContext, *, title: str | None
    ) -> CreatedConversationData:
        tenant_id = _home_tenant_id(context)
        conversation = await create_conversation(
            self.session,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
            title=title or "New conversation",
        )
        await self.session.commit()
        return CreatedConversationData(conversation=_conversation_data(conversation))

    async def list(self, context: AuthorizationContext) -> ConversationListData:
        tenant_id = _home_tenant_id(context)
        conversations = await list_owned_conversations(
            self.session,
            tenant_id=tenant_id,
            user_id=context.identity.user_id,
        )
        return ConversationListData(
            conversations=tuple(_conversation_data(item) for item in conversations)
        )

    async def answer(
        self,
        context: AuthorizationContext,
        *,
        conversation_id: UUID,
        question: str,
        request_id: str,
    ) -> GroundedMessageData:
        started = time.monotonic()
        tenant_id = _home_tenant_id(context)
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

        user_message = await add_message(
            self.session,
            conversation=conversation,
            user_id=context.identity.user_id,
            role="user",
            content=question,
            request_id=request_id,
        )
        if not _request_matches_scope(context, question):
            return await self._persist_answer(
                context=context,
                conversation=conversation,
                user_message_id=user_message.id,
                request_id=request_id,
                status="insufficient_evidence",
                answer=INSUFFICIENT_ANSWER,
                claims=(),
                citations=(),
                limitations=("The requested scope is not available in authorized evidence.",),
                evidence=(),
                usage=LLMUsage(latency_ms=int((time.monotonic() - started) * 1000)),
                reason_code="REQUEST_SCOPE_NOT_AUTHORIZED",
            )
        search = await self.search_service.search(
            context,
            query=question,
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

        if not evidence:
            return await self._persist_answer(
                context=context,
                conversation=conversation,
                user_message_id=user_message.id,
                request_id=request_id,
                status="insufficient_evidence",
                answer=INSUFFICIENT_ANSWER,
                claims=(),
                citations=(),
                limitations=("No sufficient authorized evidence was retrieved.",),
                evidence=(),
                usage=LLMUsage(latency_ms=int((time.monotonic() - started) * 1000)),
                reason_code="INSUFFICIENT_AUTHORIZED_EVIDENCE",
            )

        try:
            generation = await self.llm_provider.generate(
                GroundedGenerationRequest(question=question, evidence=evidence)
            )
        except LLMProviderError as exc:
            add_trace(
                self.session,
                request_id=request_id,
                conversation=conversation,
                user_id=context.identity.user_id,
                model_name=self.llm_provider.model_name,
                status="provider_error",
                reason_code=f"LLM_{exc.code.value}",
                document_ids=tuple(dict.fromkeys(item.document_id for item in evidence)),
                chunk_ids=tuple(item.chunk_id for item in evidence),
                input_tokens=None,
                output_tokens=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                retry_count=exc.retry_count,
            )
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

        try:
            validated = validate_grounded_answer(generation.answer, evidence)
        except GroundingValidationError:
            return await self._persist_answer(
                context=context,
                conversation=conversation,
                user_message_id=user_message.id,
                request_id=request_id,
                status="insufficient_evidence",
                answer=INSUFFICIENT_ANSWER,
                claims=(),
                citations=(),
                limitations=("The generated answer could not be validated against evidence.",),
                evidence=evidence,
                usage=generation.usage,
                reason_code="CITATION_VALIDATION_FAILED",
            )

        answer = " ".join(
            f"{claim.text} [{', '.join(claim.citation_ids)}]" for claim in validated.claims
        )
        return await self._persist_answer(
            context=context,
            conversation=conversation,
            user_message_id=user_message.id,
            request_id=request_id,
            status="grounded",
            answer=answer,
            claims=validated.claims,
            citations=validated.citations,
            limitations=validated.limitations,
            evidence=evidence,
            usage=generation.usage,
            reason_code="GROUNDED_ANSWER_VALIDATED",
        )

    async def _persist_answer(
        self,
        *,
        context: AuthorizationContext,
        conversation: Conversation,
        user_message_id: UUID,
        request_id: str,
        status: Literal["grounded", "insufficient_evidence"],
        answer: str,
        claims: tuple[GroundedClaimData, ...],
        citations: tuple[GroundedCitationData, ...],
        limitations: tuple[str, ...],
        evidence: tuple[GroundedEvidence, ...],
        usage: LLMUsage,
        reason_code: str,
    ) -> GroundedMessageData:
        assistant_message = await add_message(
            self.session,
            conversation=conversation,
            user_id=context.identity.user_id,
            role="assistant",
            content=answer,
            request_id=request_id,
        )
        trace_status = "grounded" if status == "grounded" else "insufficient_evidence"
        add_trace(
            self.session,
            request_id=request_id,
            conversation=conversation,
            user_id=context.identity.user_id,
            model_name=self.llm_provider.model_name,
            status=trace_status,
            reason_code=reason_code,
            document_ids=tuple(dict.fromkeys(item.document_id for item in evidence)),
            chunk_ids=tuple(item.chunk_id for item in evidence),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            retry_count=usage.retry_count,
        )
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
        return GroundedMessageData(
            conversation_id=conversation.id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message.id,
            status=status,
            answer=answer,
            claims=claims,
            citations=citations,
            limitations=limitations,
        )
