from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.factory import agent_route_reason, create_agent_stage_providers
from app.agent.gateway_adapter import AgentGatewayAdapter
from app.agent.loop import AgentLoop
from app.agent.models import AgentLoopLimits
from app.agent.service import AgentRunService
from app.auth.dependencies import CurrentAuthorizationContext
from app.chat.factory import create_agent_finalizer
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.embeddings.factory import create_embedding_provider
from app.mcp_gateway.adapters import (
    CalculateEbitdaMarginAdapter,
    CalculateNetProfitMarginAdapter,
    CalculateRevenueGrowthAdapter,
    GetDocumentExcerptAdapter,
    SearchAuthorizedDocumentsAdapter,
)
from app.mcp_gateway.gateway import ApprovedToolAdapter, ApprovedToolGateway
from app.schemas.api import SuccessResponse
from app.schemas.chat import AgentRunMessageData, CreateMessageRequest

router = APIRouter(prefix="/api/conversations", tags=["agent-runs"])


def get_agent_run_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentRunService:
    embedding_provider = create_embedding_provider(settings)
    gateway = ApprovedToolGateway(
        (
            cast(
                ApprovedToolAdapter,
                SearchAuthorizedDocumentsAdapter(session, embedding_provider),
            ),
            cast(ApprovedToolAdapter, GetDocumentExcerptAdapter(session)),
            cast(ApprovedToolAdapter, CalculateEbitdaMarginAdapter(session)),
            cast(ApprovedToolAdapter, CalculateRevenueGrowthAdapter(session)),
            cast(ApprovedToolAdapter, CalculateNetProfitMarginAdapter(session)),
        ),
        timeout_seconds=settings.agent_tool_timeout_seconds,
        max_transient_retries=settings.agent_tool_max_transient_retries,
    )
    perception, decision = create_agent_stage_providers(settings)
    loop = AgentLoop(
        perception=perception,
        decision=decision,
        gateway=AgentGatewayAdapter(gateway),
        finalizer=create_agent_finalizer(settings),
        limits=AgentLoopLimits(
            max_steps=settings.agent_max_steps,
            max_replans=settings.agent_max_replans,
            max_retrieval_rewrites=settings.agent_max_retrieval_rewrites,
            max_duration_seconds=settings.agent_max_duration_seconds,
        ),
    )
    return AgentRunService(
        session,
        loop,
        gateway,
        model_name=perception.model_name,
        route_reason_code=agent_route_reason(settings),
    )


AgentService = Annotated[AgentRunService, Depends(get_agent_run_service)]


@router.post(
    "/{conversation_id}/agent-runs",
    response_model=SuccessResponse[AgentRunMessageData],
)
async def create_agent_run(
    conversation_id: UUID,
    payload: CreateMessageRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    service: AgentService,
) -> SuccessResponse[AgentRunMessageData]:
    data = await service.run(
        context,
        conversation_id=conversation_id,
        question=payload.content,
        request_id=request.state.request_id,
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)
