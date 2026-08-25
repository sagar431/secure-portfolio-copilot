from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuthorizationContext
from app.db.session import get_db_session
from app.memory.service import MemoryService
from app.schemas.api import SuccessResponse
from app.schemas.memory import (
    CreateMemoryRequest,
    DeletedMemoryData,
    MemoryData,
    MemoryListData,
    SearchMemoryRequest,
)

router = APIRouter(prefix="/api/memories", tags=["memories"])


def get_memory_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryService:
    return MemoryService(session)


MemoryServiceDependency = Annotated[MemoryService, Depends(get_memory_service)]


@router.post("", response_model=SuccessResponse[MemoryData], status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: CreateMemoryRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    service: MemoryServiceDependency,
) -> SuccessResponse[MemoryData]:
    data = await service.create(
        context,
        content=payload.content,
        company_id=payload.company_id,
        requested_scope=payload.scope,
        source_chunk_ids=tuple(payload.source_chunk_ids),
        expires_in_days=payload.expires_in_days,
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.get("", response_model=SuccessResponse[MemoryListData])
async def inspect_memories(
    request: Request,
    context: CurrentAuthorizationContext,
    service: MemoryServiceDependency,
    memory_type: Literal["SEMANTIC", "EPISODIC", "CONVERSATION_SUMMARY"] | None = None,
    memory_status: Literal["PENDING_CONFIRMATION", "ACTIVE", "SUPERSEDED"] | None = None,
) -> SuccessResponse[MemoryListData]:
    return SuccessResponse(
        data=await service.inspect(context, memory_type=memory_type, status=memory_status),
        request_id=request.state.request_id,
    )


@router.post("/search", response_model=SuccessResponse[MemoryListData])
async def search_memories(
    payload: SearchMemoryRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    service: MemoryServiceDependency,
) -> SuccessResponse[MemoryListData]:
    return SuccessResponse(
        data=await service.search(context, query=payload.query, top_k=payload.top_k),
        request_id=request.state.request_id,
    )


@router.delete("/{memory_id}", response_model=SuccessResponse[DeletedMemoryData])
async def delete_memory(
    memory_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: MemoryServiceDependency,
) -> SuccessResponse[DeletedMemoryData]:
    return SuccessResponse(
        data=await service.delete(context, memory_id=memory_id),
        request_id=request.state.request_id,
    )


@router.post("/{memory_id}/confirm", response_model=SuccessResponse[MemoryData])
async def confirm_memory(
    memory_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: MemoryServiceDependency,
) -> SuccessResponse[MemoryData]:
    return SuccessResponse(
        data=await service.confirm(context, memory_id=memory_id),
        request_id=request.state.request_id,
    )


@router.post("/{memory_id}/dismiss", response_model=SuccessResponse[DeletedMemoryData])
async def dismiss_memory(
    memory_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: MemoryServiceDependency,
) -> SuccessResponse[DeletedMemoryData]:
    return SuccessResponse(
        data=await service.dismiss(context, memory_id=memory_id),
        request_id=request.state.request_id,
    )
