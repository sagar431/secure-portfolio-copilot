from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuthorizationContext
from app.chat.factory import create_llm_provider
from app.chat.service import GroundedChatService
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.embeddings.factory import create_embedding_provider
from app.retrieval.service import AuthorizedSearchService
from app.schemas.api import SuccessResponse
from app.schemas.chat import (
    ConversationListData,
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
        max_evidence_chunks=settings.llm_max_evidence_chunks,
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
        request_id=request.state.request_id,
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)
