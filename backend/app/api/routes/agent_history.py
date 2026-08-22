from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.history_service import AgentHistoryService
from app.auth.dependencies import CurrentAuthorizationContext
from app.db.session import get_db_session
from app.schemas.agent_runs import AgentRunHistoryDetailData, AgentRunHistoryListData
from app.schemas.api import SuccessResponse

router = APIRouter(prefix="/api/agent-runs", tags=["agent-runs"])


def get_agent_history_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentHistoryService:
    return AgentHistoryService(session)


AgentHistory = Annotated[AgentHistoryService, Depends(get_agent_history_service)]


@router.get("", response_model=SuccessResponse[AgentRunHistoryListData])
async def list_agent_runs(
    request: Request,
    context: CurrentAuthorizationContext,
    service: AgentHistory,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SuccessResponse[AgentRunHistoryListData]:
    return SuccessResponse(
        data=await service.list(context, cursor=cursor, limit=limit),
        request_id=request.state.request_id,
    )


@router.get("/{run_id}", response_model=SuccessResponse[AgentRunHistoryDetailData])
async def get_agent_run(
    run_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: AgentHistory,
) -> SuccessResponse[AgentRunHistoryDetailData]:
    return SuccessResponse(
        data=await service.get(context, run_id=run_id),
        request_id=request.state.request_id,
    )
