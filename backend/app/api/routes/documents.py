import re
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentAuthorizationContext
from app.core.config import Settings, get_settings
from app.core.errors import APIError
from app.db.session import get_db_session
from app.embeddings.factory import create_embedding_provider
from app.ingestion.limits import DEFAULT_LIMITS
from app.ingestion.service import DocumentIngestionService
from app.ingestion.storage import LocalObjectStorage
from app.models.documents import DocumentType, IngestionStatus
from app.schemas.api import SuccessResponse
from app.schemas.documents import (
    DeleteDocumentData,
    DocumentListData,
    DocumentOptionsData,
    DocumentPreviewData,
    DocumentUploadMetadata,
    IngestionStatusData,
    UploadResultData,
    VersionActionData,
)

router = APIRouter(prefix="/api/admin", tags=["document ingestion"])
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


def get_document_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentIngestionService:
    return DocumentIngestionService(
        session,
        LocalObjectStorage(Path(settings.document_storage_path)),
        create_embedding_provider(settings),
        embedding_batch_size=settings.embedding_batch_size,
        embedding_max_chunks=settings.embedding_max_chunks,
        embedding_operation_timeout_seconds=settings.embedding_operation_timeout_seconds,
    )


DocumentService = Annotated[DocumentIngestionService, Depends(get_document_service)]


@router.get("/ingestion/options", response_model=SuccessResponse[DocumentOptionsData])
async def document_options(
    request: Request,
    context: CurrentAuthorizationContext,
    service: DocumentService,
) -> SuccessResponse[DocumentOptionsData]:
    data = await service.options(context, request_id=request.state.request_id)
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.post("/documents", response_model=SuccessResponse[UploadResultData])
async def upload_document(
    request: Request,
    response: Response,
    context: CurrentAuthorizationContext,
    service: DocumentService,
    metadata: Annotated[str, Form(min_length=2, max_length=4096)],
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> SuccessResponse[UploadResultData]:
    if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise APIError(422, "invalid_idempotency_key", "Idempotency key is invalid.")
    try:
        upload_metadata = DocumentUploadMetadata.model_validate_json(metadata)
    except ValidationError:
        raise APIError(422, "invalid_document_metadata", "Document metadata is invalid.") from None
    filename = file.filename or ""
    declared_content_type = file.content_type or "application/octet-stream"
    await service.authorize_upload_target(
        context, upload_metadata, request_id=request.state.request_id
    )
    data = await file.read(DEFAULT_LIMITS.upload_bytes + 1)
    await file.close()
    result, created = await service.upload(
        context,
        upload_metadata,
        filename=filename,
        declared_content_type=declared_content_type,
        data=data,
        idempotency_key=idempotency_key,
        request_id=request.state.request_id,
    )
    response.status_code = 201 if created else 200
    return SuccessResponse(data=result, request_id=request.state.request_id)


@router.post(
    "/documents/{document_id}/versions",
    response_model=SuccessResponse[UploadResultData],
)
async def upload_document_version(
    document_id: UUID,
    request: Request,
    response: Response,
    context: CurrentAuthorizationContext,
    service: DocumentService,
    metadata: Annotated[str, Form(min_length=2, max_length=4096)],
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> SuccessResponse[UploadResultData]:
    if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise APIError(422, "invalid_idempotency_key", "Idempotency key is invalid.")
    try:
        upload_metadata = DocumentUploadMetadata.model_validate_json(metadata)
    except ValidationError:
        raise APIError(422, "invalid_document_metadata", "Document metadata is invalid.") from None
    filename = file.filename or ""
    declared_content_type = file.content_type or "application/octet-stream"
    await service.authorize_upload_target(
        context,
        upload_metadata,
        request_id=request.state.request_id,
        document_id=document_id,
    )
    data = await file.read(DEFAULT_LIMITS.upload_bytes + 1)
    await file.close()
    result, created = await service.upload(
        context,
        upload_metadata,
        filename=filename,
        declared_content_type=declared_content_type,
        data=data,
        idempotency_key=idempotency_key,
        request_id=request.state.request_id,
        document_id=document_id,
    )
    response.status_code = 201 if created else 200
    return SuccessResponse(data=result, request_id=request.state.request_id)


@router.get("/documents", response_model=SuccessResponse[DocumentListData])
async def document_library(
    request: Request,
    context: CurrentAuthorizationContext,
    service: DocumentService,
    tenant_id: Annotated[UUID | None, Query()] = None,
    company_id: Annotated[UUID | None, Query()] = None,
    department: Annotated[str | None, Query(pattern=r"^(finance|legal|shared)$")] = None,
    document_type: Annotated[DocumentType | None, Query()] = None,
    status: Annotated[IngestionStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> SuccessResponse[DocumentListData]:
    data = await service.library(
        context,
        tenant_id=tenant_id,
        company_id=company_id,
        department=department,
        document_type=document_type.value if document_type else None,
        status=status.value if status else None,
        limit=limit,
        offset=offset,
        request_id=request.state.request_id,
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.get("/ingestion/{job_id}", response_model=SuccessResponse[IngestionStatusData])
async def ingestion_status(
    job_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: DocumentService,
) -> SuccessResponse[IngestionStatusData]:
    data = await service.status(context, job_id, request_id=request.state.request_id)
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.get(
    "/documents/{document_id}/versions/{version_id}/preview",
    response_model=SuccessResponse[DocumentPreviewData],
)
async def document_preview(
    document_id: UUID,
    version_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: DocumentService,
) -> SuccessResponse[DocumentPreviewData]:
    data = await service.preview(
        context, document_id, version_id, request_id=request.state.request_id
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.post(
    "/documents/{document_id}/versions/{version_id}/approve",
    response_model=SuccessResponse[VersionActionData],
)
async def approve_document(
    document_id: UUID,
    version_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: DocumentService,
) -> SuccessResponse[VersionActionData]:
    data = await service.approve(
        context, document_id, version_id, request_id=request.state.request_id
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.post(
    "/documents/{document_id}/versions/{version_id}/reject",
    response_model=SuccessResponse[VersionActionData],
)
async def reject_document(
    document_id: UUID,
    version_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: DocumentService,
) -> SuccessResponse[VersionActionData]:
    data = await service.reject(
        context, document_id, version_id, request_id=request.state.request_id
    )
    return SuccessResponse(data=data, request_id=request.state.request_id)


@router.delete("/documents/{document_id}", response_model=SuccessResponse[DeleteDocumentData])
async def delete_document(
    document_id: UUID,
    request: Request,
    context: CurrentAuthorizationContext,
    service: DocumentService,
) -> SuccessResponse[DeleteDocumentData]:
    data = await service.delete(context, document_id, request_id=request.state.request_id)
    return SuccessResponse(data=data, request_id=request.state.request_id)
