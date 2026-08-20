from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuthorizationContext
from app.db.session import get_db_session
from app.retrieval.service import AuthorizedSearchService
from app.schemas.api import SuccessResponse
from app.schemas.retrieval import AuthorizedSearchData, AuthorizedSearchRequest

router = APIRouter(prefix="/api/development", tags=["development"])


@router.post(
    "/authorized-search",
    response_model=SuccessResponse[AuthorizedSearchData],
)
async def authorized_search(
    payload: AuthorizedSearchRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SuccessResponse[AuthorizedSearchData]:
    data = await AuthorizedSearchService(session).search(
        context,
        query=payload.query,
        top_k=payload.top_k,
        request_id=request.state.request_id,
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)
