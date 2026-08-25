from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.approval_service import AgentApprovalService
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
    CalculateCagrAdapter,
    CalculateCashRunwayAdapter,
    CalculateDebtToEquityAdapter,
    CalculateEbitdaMarginAdapter,
    CalculateNetProfitMarginAdapter,
    CalculateRevenueGrowthAdapter,
    GetDocumentExcerptAdapter,
    ProposeMemoryAdapter,
    QueryFinancialMetricsAdapter,
    SearchAuthorizedDocumentsAdapter,
    SearchMemoryAdapter,
)
from app.mcp_gateway.gateway import ApprovedToolAdapter, ApprovedToolGateway
from app.schemas.agent_runs import (
    ApprovalStateData,
    AwaitingApprovalData,
    ChangeAgentRequest,
    ResolveApprovalRequest,
    SafelyTerminatedData,
)
from app.schemas.api import SuccessResponse
from app.schemas.chat import AgentRunMessageData, CreateAgentRunRequest

router = APIRouter(prefix="/api/conversations", tags=["agent-runs"])
approval_router = APIRouter(prefix="/api/agent-runs", tags=["agent-approvals"])


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
            cast(ApprovedToolAdapter, QueryFinancialMetricsAdapter(session)),
            cast(ApprovedToolAdapter, CalculateDebtToEquityAdapter(session)),
            cast(ApprovedToolAdapter, CalculateCashRunwayAdapter(session)),
            cast(ApprovedToolAdapter, CalculateCagrAdapter(session)),
            cast(ApprovedToolAdapter, SearchMemoryAdapter(session)),
            cast(ApprovedToolAdapter, ProposeMemoryAdapter(session)),
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
        low_confidence_threshold=settings.router_low_confidence_threshold,
        max_recent_messages=settings.memory_recent_message_limit,
    )


AgentService = Annotated[AgentRunService, Depends(get_agent_run_service)]


def get_agent_approval_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    runner: AgentService,
) -> AgentApprovalService:
    return AgentApprovalService(session, runner)


ApprovalService = Annotated[AgentApprovalService, Depends(get_agent_approval_service)]


@router.post(
    "/{conversation_id}/agent-runs",
    response_model=SuccessResponse[AgentRunMessageData | AwaitingApprovalData],
)
async def create_agent_run(
    conversation_id: UUID,
    payload: CreateAgentRunRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    service: AgentService,
) -> SuccessResponse[AgentRunMessageData | AwaitingApprovalData]:
    data = await service.run(
        context,
        conversation_id=conversation_id,
        question=payload.content,
        response_mode=payload.response_mode,
        agent_control_mode=payload.agent_control_mode,
        request_id=request.state.request_id,
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)


@approval_router.get(
    "/{run_id}/approval",
    response_model=SuccessResponse[ApprovalStateData],
)
async def get_current_approval(
    run_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: ApprovalService,
) -> SuccessResponse[ApprovalStateData]:
    return SuccessResponse(
        data=await service.current(context, run_id=run_id),
        request_id=request.state.request_id,
    )


@approval_router.post(
    "/{run_id}/approvals/{approval_id}/resolve",
    response_model=SuccessResponse[
        AgentRunMessageData | AwaitingApprovalData | SafelyTerminatedData
    ],
)
async def resolve_approval(
    run_id: UUID,
    approval_id: UUID,
    payload: ResolveApprovalRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    service: ApprovalService,
) -> SuccessResponse[AgentRunMessageData | AwaitingApprovalData | SafelyTerminatedData]:
    data: AgentRunMessageData | AwaitingApprovalData | SafelyTerminatedData
    if payload.action == "reject":
        data = await service.reject(context, run_id=run_id, approval_id=approval_id)
    else:
        data = await service.approve_once(
            context,
            run_id=run_id,
            approval_id=approval_id,
            request_id=request.state.request_id,
        )
    return SuccessResponse(data=data, request_id=request.state.request_id)


@approval_router.post(
    "/{run_id}/stop",
    response_model=SuccessResponse[SafelyTerminatedData],
)
async def stop_agent_run(
    run_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: ApprovalService,
) -> SuccessResponse[SafelyTerminatedData]:
    return SuccessResponse(
        data=await service.stop(context, run_id=run_id),
        request_id=request.state.request_id,
    )


@approval_router.post(
    "/{run_id}/approvals/{approval_id}/change-request",
    response_model=SuccessResponse[AgentRunMessageData | AwaitingApprovalData],
)
async def change_agent_request(
    run_id: UUID,
    approval_id: UUID,
    payload: ChangeAgentRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    service: ApprovalService,
) -> SuccessResponse[AgentRunMessageData | AwaitingApprovalData]:
    return SuccessResponse(
        data=await service.change_request(
            context,
            run_id=run_id,
            approval_id=approval_id,
            content=payload.content,
            request_id=request.state.request_id,
        ),
        request_id=request.state.request_id,
    )
