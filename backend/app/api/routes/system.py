from fastapi import APIRouter, Request

from app.core.errors import APIError
from app.db.readiness import check_database_ready
from app.schemas.api import HealthData, ReadinessData, SuccessResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=SuccessResponse[HealthData])
async def health(request: Request) -> SuccessResponse[HealthData]:
    return SuccessResponse(
        data=HealthData(),
        request_id=request.state.request_id,
    )


@router.get(
    "/ready",
    response_model=SuccessResponse[ReadinessData],
    responses={503: {"description": "Database is unavailable"}},
)
async def ready(request: Request) -> SuccessResponse[ReadinessData]:
    if not await check_database_ready():
        raise APIError(503, "service_unavailable", "Service is not ready.")
    return SuccessResponse(
        data=ReadinessData(),
        request_id=request.state.request_id,
    )
