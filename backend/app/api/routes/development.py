from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuthorizationContext
from app.core.config import Settings, get_settings
from app.core.errors import APIError
from app.db.session import get_db_session
from app.embeddings.contracts import EmbeddingProviderError
from app.embeddings.factory import create_embedding_provider
from app.ingestion.audit import record_document_event
from app.ingestion.repository import manageable_pairs
from app.retrieval.reindexing import reindex_authorized_pending_chunks
from app.retrieval.service import AuthorizedSearchService
from app.schemas.api import SuccessResponse
from app.schemas.retrieval import (
    AuthorizedSearchData,
    AuthorizedSearchRequest,
    EmbeddingReindexData,
)

router = APIRouter(prefix="/api/development", tags=["development"])


def get_search_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthorizedSearchService:
    return AuthorizedSearchService(session, create_embedding_provider(settings))


SearchService = Annotated[AuthorizedSearchService, Depends(get_search_service)]


@router.post(
    "/authorized-search",
    response_model=SuccessResponse[AuthorizedSearchData],
)
async def authorized_search(
    payload: AuthorizedSearchRequest,
    request: Request,
    context: CurrentAuthorizationContext,
    service: SearchService,
) -> SuccessResponse[AuthorizedSearchData]:
    data = await service.search(
        context,
        query=payload.query,
        top_k=payload.top_k,
        request_id=request.state.request_id,
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.post(
    "/reindex-embeddings",
    response_model=SuccessResponse[EmbeddingReindexData],
)
async def reindex_embeddings(
    request: Request,
    context: CurrentAuthorizationContext,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SuccessResponse[EmbeddingReindexData]:
    if not manageable_pairs(context.scope):
        raise APIError(403, "forbidden", "Embedding reindex is not permitted.")
    try:
        processed = await reindex_authorized_pending_chunks(
            session,
            context.scope,
            create_embedding_provider(settings),
            batch_size=settings.embedding_batch_size,
            max_chunks=settings.embedding_max_chunks,
            timeout_seconds=settings.embedding_operation_timeout_seconds,
        )
    except EmbeddingProviderError:
        await session.rollback()
        raise APIError(
            503, "embedding_unavailable", "Embedding reindex is temporarily unavailable."
        ) from None
    await record_document_event(
        session,
        event_type="document_embedding_reindex",
        outcome="allow",
        reason_code="AUTHORIZED_REINDEX_COMPLETED",
        request_id=request.state.request_id,
        actor_user_id=context.identity.user_id,
        metadata={"processed_chunk_count": processed},
    )
    await session.commit()
    return SuccessResponse(
        data=EmbeddingReindexData(processed_chunk_count=processed),
        request_id=request.state.request_id,
    )
