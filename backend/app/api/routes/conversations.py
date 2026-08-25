import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuthorizationContext
from app.chat.factory import (
    create_conversation_summarizer,
    create_intent_router,
    create_llm_provider,
    create_memory_extractor,
)
from app.chat.service import GroundedChatService
from app.chat.streaming import (
    AnswerDelta,
    ChatProgressEvent,
    CitationEvent,
    MemoryNotification,
    MessageCompleted,
    MessageStarted,
    SafeError,
    encode_event,
    validated_answer_deltas,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.embeddings.factory import create_embedding_provider
from app.retrieval.service import AuthorizedSearchService
from app.schemas.api import SuccessResponse
from app.schemas.chat import (
    ConversationListData,
    ConversationMessagesData,
    CreateConversationRequest,
    CreatedConversationData,
    CreateMessageRequest,
    GroundedMessageData,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def get_grounded_chat_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GroundedChatService:
    return GroundedChatService(
        session,
        AuthorizedSearchService(session, create_embedding_provider(settings)),
        create_llm_provider(settings),
        create_memory_extractor(settings),
        create_intent_router(settings),
        create_conversation_summarizer(settings),
        max_evidence_chunks=settings.llm_max_evidence_chunks,
        max_memory_items=settings.memory_max_items,
        max_recent_messages=settings.memory_recent_message_limit,
        max_memory_context_chars=settings.memory_context_char_budget,
        semantic_expiry_days=settings.memory_semantic_expiry_days,
        episodic_expiry_days=settings.memory_episodic_expiry_days,
        low_confidence_threshold=settings.router_low_confidence_threshold,
    )


ChatService = Annotated[GroundedChatService, Depends(get_grounded_chat_service)]


@router.post(
    "",
    response_model=SuccessResponse[CreatedConversationData],
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: CreateConversationRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    service: ChatService,
) -> SuccessResponse[CreatedConversationData]:
    data = await service.create(context, title=payload.title)
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.get("", response_model=SuccessResponse[ConversationListData])
async def list_conversations(
    request: Request,
    context: CurrentAuthorizationContext,
    service: ChatService,
) -> SuccessResponse[ConversationListData]:
    data = await service.list(context)
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.get(
    "/{conversation_id}/messages",
    response_model=SuccessResponse[ConversationMessagesData],
)
async def list_conversation_messages(
    conversation_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: ChatService,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> SuccessResponse[ConversationMessagesData]:
    data = await service.history(context, conversation_id=conversation_id, limit=limit)
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.post(
    "/{conversation_id}/messages",
    response_model=SuccessResponse[GroundedMessageData],
)
async def create_message(
    conversation_id: UUID,
    payload: CreateMessageRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    service: ChatService,
) -> SuccessResponse[GroundedMessageData]:
    data = await service.answer(
        context,
        conversation_id=conversation_id,
        question=payload.content,
        response_mode=payload.response_mode,
        request_id=request.state.request_id,
        client_message_id=payload.client_message_id,
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.post("/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: UUID,
    payload: CreateMessageRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    service: ChatService,
) -> StreamingResponse:
    """NDJSON progress with progressive delivery only after host validation and persistence."""

    async def events() -> AsyncIterator[bytes]:
        yield encode_event(MessageStarted())
        progress_queue: asyncio.Queue[ChatProgressEvent | None] = asyncio.Queue(maxsize=8)

        def report_progress(event: ChatProgressEvent) -> None:
            progress_queue.put_nowait(event)

        async def produce() -> GroundedMessageData:
            try:
                return await service.answer(
                    context,
                    conversation_id=conversation_id,
                    question=payload.content,
                    response_mode=payload.response_mode,
                    request_id=request.state.request_id,
                    progress=report_progress,
                    client_message_id=payload.client_message_id,
                )
            finally:
                progress_queue.put_nowait(None)

        answer_task = asyncio.create_task(produce())
        try:
            while (event := await progress_queue.get()) is not None:
                yield encode_event(event)
            result = await answer_task
            for delta in validated_answer_deltas(result.answer):
                yield encode_event(AnswerDelta(delta=delta))
                await asyncio.sleep(0)
            for citation in result.citations:
                yield encode_event(CitationEvent(citation=citation))
            for notification in result.memory_notifications:
                yield encode_event(MemoryNotification(message=notification))
            yield encode_event(MessageCompleted(result=result))
        except asyncio.CancelledError:
            answer_task.cancel()
            with suppress(asyncio.CancelledError):
                await answer_task
            await service.session.rollback()
            raise
        except Exception:
            if not answer_task.done():
                answer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await answer_task
            await service.session.rollback()
            yield encode_event(SafeError())
        finally:
            # Async-generator close (client disconnect) raises GeneratorExit rather than
            # CancelledError. Always cancel unfinished work so no provider/DB task is orphaned.
            if not answer_task.done():
                answer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await answer_task
                await service.session.rollback()

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )
