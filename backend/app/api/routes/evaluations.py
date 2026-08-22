from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuthorizationContext
from app.chat.factory import create_llm_provider
from app.core.config import Settings, get_settings
from app.core.errors import APIError
from app.db.session import get_db_session
from app.embeddings.factory import create_embedding_provider
from app.evaluations.contracts import (
    EvaluationRunDetail,
    EvaluationRunList,
    EvaluationRunRequest,
)
from app.evaluations.service import EvaluationService
from app.models.identity import Capability
from app.policies.models import AuthorizationContext
from app.schemas.api import SuccessResponse

router = APIRouter(prefix="/api/admin/evaluations", tags=["admin-evaluations"])


def require_platform_administrator(context: CurrentAuthorizationContext) -> AuthorizationContext:
    if not any(
        Capability.ADMINISTER_PLATFORM in grant.capabilities and grant.role == "admin"
        for grant in context.scope.grants
    ):
        raise APIError(403, "forbidden", "Platform administration is not permitted.")
    return context


PlatformAdministrator = Annotated[AuthorizationContext, Depends(require_platform_administrator)]


def get_evaluation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EvaluationService:
    return EvaluationService(
        session,
        settings=settings,
        embedding_provider=create_embedding_provider(settings),
        llm_provider=create_llm_provider(settings),
    )


EvaluationServiceDependency = Annotated[EvaluationService, Depends(get_evaluation_service)]


@router.post("/run", response_model=SuccessResponse[EvaluationRunDetail])
async def run_evaluation(
    payload: EvaluationRunRequest,
    request: Request,
    context: PlatformAdministrator,
    service: EvaluationServiceDependency,
) -> SuccessResponse[EvaluationRunDetail]:
    data = await service.execute(context, payload, request_id=request.state.request_id)
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.get("", response_model=SuccessResponse[EvaluationRunList])
async def list_evaluations(
    request: Request,
    _: PlatformAdministrator,
    service: EvaluationServiceDependency,
) -> SuccessResponse[EvaluationRunList]:
    return SuccessResponse(data=await service.list(), request_id=request.state.request_id)


@router.get("/{run_id}", response_model=SuccessResponse[EvaluationRunDetail])
async def get_evaluation(
    run_id: UUID,
    request: Request,
    _: PlatformAdministrator,
    service: EvaluationServiceDependency,
) -> SuccessResponse[EvaluationRunDetail]:
    return SuccessResponse(data=await service.get(run_id), request_id=request.state.request_id)


@router.get("/{run_id}/report")
async def download_evaluation_report(
    run_id: UUID,
    _: PlatformAdministrator,
    service: EvaluationServiceDependency,
) -> JSONResponse:
    data = await service.get(run_id)
    return JSONResponse(
        content=data.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="evaluation-{run_id}.json"'},
    )
