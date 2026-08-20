from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Literal, NoReturn
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking import ChunkingError, GeneratedChunk
from app.core.errors import APIError
from app.ingestion.audit import record_document_event
from app.ingestion.contracts import (
    ParsedDocument,
    StorageKey,
    ValidatedFile,
    ValidationInput,
)
from app.ingestion.errors import (
    FileParsingError,
    FileValidationError,
    IngestionError,
    IngestionErrorCode,
    ObjectStorageError,
)
from app.ingestion.repository import (
    find_initial_duplicate,
    get_active_company,
    get_department_by_key,
    get_document_for_management,
    get_idempotent_version,
    get_job_for_management,
    get_version_for_management,
    list_manageable_documents,
    list_manageable_options,
    manageable_pairs,
)
from app.ingestion.state_machine import InvalidIngestionTransition, validate_transition
from app.ingestion.storage import LocalObjectStorage
from app.ingestion.validation import sanitize_filename, validate_file
from app.ingestion.worker import parse_in_worker
from app.models.documents import (
    Document,
    DocumentClassification,
    DocumentType,
    DocumentVersion,
    DocumentVisibility,
    IngestionJob,
    IngestionStatus,
    ParsedCell,
    ParsedPage,
    ParsedRow,
    ParsedSheet,
)
from app.models.identity import Capability, Company, Department, Tenant
from app.policies.engine import authorize
from app.policies.models import AuthorizationContext, PolicyRequest
from app.retrieval.indexing import (
    deactivate_document_chunks,
    deactivate_version_chunks,
    generate_approved_chunks,
    replace_active_chunks,
)
from app.schemas.documents import (
    ClassificationPairData,
    CompanyOptionData,
    DeleteDocumentData,
    DocumentData,
    DocumentListData,
    DocumentOptionsData,
    DocumentPreviewData,
    DocumentScopeData,
    DocumentTypeOptionData,
    DocumentUploadMetadata,
    DocumentVersionData,
    IngestionStatusData,
    ParsedCellData,
    ParsedPageData,
    ParsedRowData,
    ParsedSheetData,
    TenantOptionData,
    UploadLimitsData,
    UploadResultData,
    VersionActionData,
    WarningData,
)

Parser = Callable[[ValidatedFile], ParsedDocument]


def _now() -> datetime:
    return datetime.now(UTC)


def _warnings(items: Sequence[object]) -> tuple[WarningData, ...]:
    warnings: list[WarningData] = []
    for item in items:
        if isinstance(item, dict):
            warnings.append(
                WarningData(
                    code=str(item.get("code", "PARSER_WARNING")),
                    message=str(item.get("message", "Document contains a parsing warning.")),
                )
            )
        else:
            warnings.append(WarningData(code="PARSER_WARNING", message=str(item)))
    return tuple(warnings)


def _warning_records(items: Sequence[str]) -> list[dict[str, str]]:
    return [{"code": "PARSER_WARNING", "message": item} for item in items]


def _latest_version(document: Document) -> DocumentVersion:
    if not document.versions:
        raise RuntimeError("Document has no versions")
    return max(document.versions, key=lambda item: item.version_number)


def _version_data(version: DocumentVersion) -> DocumentVersionData:
    source_types: dict[str, Literal["PDF", "XLSX", "CSV", "UNKNOWN"]] = {
        "application/pdf": "PDF",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
        "text/csv": "CSV",
        "application/csv": "CSV",
    }
    return DocumentVersionData(
        id=version.id,
        version_number=version.version_number,
        original_filename=version.original_filename,
        media_type=version.detected_media_type,
        source_type=source_types.get(version.detected_media_type, "UNKNOWN"),
        checksum_sha256=version.checksum_sha256,
        size_bytes=version.size_bytes,
        status=IngestionStatus(version.status),
        page_count=version.page_count,
        sheet_count=version.sheet_count,
        row_count=version.row_count,
        cell_count=version.cell_count,
        warnings=_warnings(version.warnings),
        uploaded_by_user_id=version.uploaded_by_user_id,
        approved_by_user_id=version.approved_by_user_id,
        created_at=version.created_at,
    )


def _document_data(
    document: Document,
    version: DocumentVersion | None = None,
    job: IngestionJob | None = None,
) -> DocumentData:
    selected = version or _latest_version(document)
    selected_job = job if job is not None else selected.ingestion_job
    if selected_job is None:
        raise RuntimeError("Document version has no ingestion job")
    return DocumentData(
        id=document.id,
        scope=DocumentScopeData(
            tenant_id=document.tenant_id,
            tenant_slug=document.tenant.slug,
            tenant_name=document.tenant.name,
            company_id=document.company_id,
            company_slug=document.company.slug,
            company_name=document.company.name,
            department=document.department.key,
            visibility=DocumentVisibility(document.visibility),
            classification=DocumentClassification(document.classification),
        ),
        document_type=DocumentType(document.document_type),
        reporting_period=document.reporting_period,
        current_approved_version_id=document.current_approved_version_id,
        version=_version_data(selected),
        ingestion_job_id=selected_job.id,
    )


def _request_fingerprint(
    metadata: DocumentUploadMetadata,
    data: bytes,
    filename: str,
    declared_content_type: str,
    document_id: UUID | None,
) -> str:
    serialized = json.dumps(
        {
            "metadata": metadata.model_dump(mode="json", exclude_none=False),
            "sha256": hashlib.sha256(data).hexdigest(),
            "filename": filename,
            "declared_content_type": declared_content_type,
            "document_id": str(document_id) if document_id is not None else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _raise_for_ingestion_error(error: IngestionError) -> NoReturn:
    if error.code == IngestionErrorCode.FILE_TOO_LARGE:
        raise APIError(413, "file_too_large", "Uploaded file exceeds the allowed size.")
    if error.code in {
        IngestionErrorCode.UNSUPPORTED_FILE_TYPE,
        IngestionErrorCode.CONTENT_TYPE_MISMATCH,
        IngestionErrorCode.INVALID_FILE_SIGNATURE,
    }:
        raise APIError(415, "unsupported_document", "Uploaded file type is not accepted.")
    if isinstance(error, ObjectStorageError):
        raise APIError(503, "storage_unavailable", "Document storage is unavailable.")
    raise APIError(422, "unsafe_document", error.safe_message)


def _raise_for_replayed_failure(version: DocumentVersion) -> NoReturn:
    """Reproduce the safe HTTP outcome of a previously persisted failed attempt."""
    raw_code = version.ingestion_job.safe_error_code
    try:
        code = IngestionErrorCode(raw_code) if raw_code is not None else None
    except ValueError:
        code = None
    if code == IngestionErrorCode.FILE_TOO_LARGE:
        raise APIError(413, "file_too_large", "Uploaded file exceeds the allowed size.")
    if code in {
        IngestionErrorCode.UNSUPPORTED_FILE_TYPE,
        IngestionErrorCode.CONTENT_TYPE_MISMATCH,
        IngestionErrorCode.INVALID_FILE_SIGNATURE,
    }:
        raise APIError(415, "unsupported_document", "Uploaded file type is not accepted.")
    if code in {
        IngestionErrorCode.STORAGE_UNAVAILABLE,
        IngestionErrorCode.STORAGE_KEY_INVALID,
        IngestionErrorCode.STORAGE_CONFLICT,
    }:
        raise APIError(503, "storage_unavailable", "Document storage is unavailable.")
    raise APIError(422, "unsafe_document", "Document processing failed safely.")


class DocumentIngestionService:
    def __init__(
        self,
        session: AsyncSession,
        storage: LocalObjectStorage,
        *,
        parser: Parser = parse_in_worker,
    ) -> None:
        self.session = session
        self.storage = storage
        self.parser = parser

    async def _authorize_target(
        self,
        context: AuthorizationContext,
        *,
        tenant_id: UUID,
        company_id: UUID,
        request_id: str,
        event_type: str,
        resource_denial: bool,
        document_id: UUID | None = None,
    ) -> None:
        decision = authorize(
            context.scope,
            PolicyRequest(
                capability=Capability.MANAGE_UPLOADS,
                workspace_id=tenant_id,
                company_id=company_id,
            ),
        )
        if decision.allowed:
            return
        await record_document_event(
            self.session,
            event_type=event_type,
            outcome="deny",
            reason_code=decision.reason_code.value,
            request_id=request_id,
            actor_user_id=context.identity.user_id,
            document_id=document_id,
        )
        await self.session.commit()
        if resource_denial:
            raise APIError(404, "not_found", "Document was not found.")
        raise APIError(403, "forbidden", "Document management is not permitted.")

    async def _require_any_manage_permission(
        self,
        context: AuthorizationContext,
        *,
        request_id: str,
        event_type: str,
    ) -> None:
        if manageable_pairs(context.scope):
            return
        await record_document_event(
            self.session,
            event_type=event_type,
            outcome="deny",
            reason_code="DENY_CAPABILITY",
            request_id=request_id,
            actor_user_id=context.identity.user_id,
        )
        await self.session.commit()
        raise APIError(403, "forbidden", "Document management is not permitted.")

    async def _raise_not_found(
        self,
        context: AuthorizationContext,
        *,
        request_id: str,
        event_type: str,
        message: str = "Document was not found.",
    ) -> NoReturn:
        await record_document_event(
            self.session,
            event_type=event_type,
            outcome="deny",
            reason_code="RESOURCE_NOT_MANAGEABLE",
            request_id=request_id,
            actor_user_id=context.identity.user_id,
        )
        await self.session.commit()
        raise APIError(404, "not_found", message)

    @staticmethod
    def _metadata_matches_document(document: Document, metadata: DocumentUploadMetadata) -> bool:
        return (
            document.tenant_id,
            document.company_id,
            document.department.key,
            document.visibility,
            document.classification,
            document.document_type,
            document.reporting_period,
        ) == (
            metadata.tenant_id,
            metadata.company_id,
            metadata.department,
            metadata.visibility.value,
            metadata.classification.value,
            metadata.document_type.value,
            metadata.reporting_period,
        )

    async def authorize_upload_target(
        self,
        context: AuthorizationContext,
        metadata: DocumentUploadMetadata,
        *,
        request_id: str,
        document_id: UUID | None = None,
    ) -> tuple[Company, Department, Document | None]:
        await self._authorize_target(
            context,
            tenant_id=metadata.tenant_id,
            company_id=metadata.company_id,
            request_id=request_id,
            event_type="document_upload",
            resource_denial=False,
        )
        company = await get_active_company(self.session, metadata.tenant_id, metadata.company_id)
        department = await get_department_by_key(self.session, metadata.department)
        if company is None or department is None:
            await record_document_event(
                self.session,
                event_type="document_upload",
                outcome="deny",
                reason_code="INVALID_DOCUMENT_METADATA",
                request_id=request_id,
                actor_user_id=context.identity.user_id,
            )
            await self.session.commit()
            raise APIError(422, "invalid_document_metadata", "Document metadata is invalid.")
        if document_id is None:
            return company, department, None
        document = await get_document_for_management(
            self.session, context.scope, document_id, for_update=True
        )
        if document is None:
            await self._raise_not_found(
                context,
                request_id=request_id,
                event_type="document_version_upload",
            )
        await self._authorize_target(
            context,
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            request_id=request_id,
            event_type="document_version_upload",
            resource_denial=True,
            document_id=document.id,
        )
        if not self._metadata_matches_document(document, metadata):
            await record_document_event(
                self.session,
                event_type="document_version_upload",
                outcome="deny",
                reason_code="DOCUMENT_METADATA_CONFLICT",
                request_id=request_id,
                actor_user_id=context.identity.user_id,
                document_id=document.id,
            )
            await self.session.commit()
            raise APIError(409, "document_metadata_conflict", "Document metadata cannot change.")
        return company, department, document

    def _transition(
        self,
        version: DocumentVersion,
        job: IngestionJob,
        target: IngestionStatus,
        *,
        safe_error_code: str | None = None,
    ) -> None:
        validate_transition(version.status, target)
        validate_transition(job.status, target)
        version.status = target.value
        job.status = target.value
        job.safe_error_code = safe_error_code
        if job.started_at is None and target == IngestionStatus.VALIDATING:
            job.started_at = _now()
        if target in {
            IngestionStatus.PREVIEW_READY,
            IngestionStatus.APPROVED,
            IngestionStatus.REJECTED,
            IngestionStatus.VALIDATION_FAILED,
            IngestionStatus.PARSING_FAILED,
            IngestionStatus.DELETED,
        }:
            job.completed_at = _now()

    async def _persist_validation_failure(
        self,
        context: AuthorizationContext,
        metadata: DocumentUploadMetadata,
        *,
        company: Company,
        department: Department,
        document: Document | None,
        filename: str,
        declared_content_type: str,
        data: bytes,
        idempotency_key: str,
        request_fingerprint: str,
        request_id: str,
        error: FileValidationError,
    ) -> None:
        try:
            safe_filename = sanitize_filename(filename)
        except FileValidationError:
            safe_filename = "rejected-upload"
        if document is None:
            document = Document(
                id=uuid4(),
                tenant_id=metadata.tenant_id,
                company_id=metadata.company_id,
                department_id=department.id,
                visibility=metadata.visibility.value,
                classification=metadata.classification.value,
                document_type=metadata.document_type.value,
                reporting_period=metadata.reporting_period,
                created_by_user_id=context.identity.user_id,
                tenant=company.tenant,
                company=company,
                department=department,
            )
            self.session.add(document)
            version_number = 1
        else:
            version_number = max(item.version_number for item in document.versions) + 1
        suffix = PurePosixPath(safe_filename.lower()).suffix
        if suffix not in {".pdf", ".xlsx", ".csv"}:
            suffix = ""
        version = DocumentVersion(
            id=uuid4(),
            document=document,
            version_number=version_number,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            original_filename=safe_filename,
            safe_filename=safe_filename,
            extension=suffix,
            declared_media_type=declared_content_type[:160],
            detected_media_type="application/octet-stream",
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            status=IngestionStatus.UPLOADED.value,
            warnings=[],
            uploaded_by_user_id=context.identity.user_id,
            pages=[],
            sheets=[],
        )
        job = IngestionJob(
            id=uuid4(), document_version=version, status=IngestionStatus.UPLOADED.value
        )
        self.session.add_all([version, job])
        await self.session.flush()
        self._transition(version, job, IngestionStatus.VALIDATING)
        self._transition(
            version,
            job,
            IngestionStatus.VALIDATION_FAILED,
            safe_error_code=error.code.value,
        )
        await record_document_event(
            self.session,
            event_type="document_validate",
            outcome="error",
            reason_code=error.code.value,
            request_id=request_id,
            actor_user_id=context.identity.user_id,
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            document_id=document.id,
            document_version_id=version.id,
            ingestion_job_id=job.id,
            metadata={
                "size_bytes": len(data),
                "department": metadata.department,
                "visibility": metadata.visibility.value,
                "classification": metadata.classification.value,
                "document_type": metadata.document_type.value,
            },
        )
        await self.session.commit()

    async def upload(
        self,
        context: AuthorizationContext,
        metadata: DocumentUploadMetadata,
        *,
        filename: str,
        declared_content_type: str,
        data: bytes,
        idempotency_key: str,
        request_id: str,
        document_id: UUID | None = None,
    ) -> tuple[UploadResultData, bool]:
        company, department, target_document = await self.authorize_upload_target(
            context,
            request_id=request_id,
            metadata=metadata,
            document_id=document_id,
        )

        fingerprint = _request_fingerprint(
            metadata, data, filename, declared_content_type, document_id
        )
        idempotent = await get_idempotent_version(
            self.session, context.identity.user_id, idempotency_key
        )
        if idempotent is not None:
            if idempotent.request_fingerprint != fingerprint:
                await record_document_event(
                    self.session,
                    event_type="document_upload",
                    outcome="deny",
                    reason_code="IDEMPOTENCY_CONFLICT",
                    request_id=request_id,
                    actor_user_id=context.identity.user_id,
                    document_id=idempotent.document_id,
                    document_version_id=idempotent.id,
                )
                await self.session.commit()
                raise APIError(
                    409,
                    "idempotency_conflict",
                    "Idempotency key was already used for a different upload.",
                )
            managed = await get_document_for_management(
                self.session, context.scope, idempotent.document_id
            )
            if managed is None:
                await self._raise_not_found(
                    context,
                    request_id=request_id,
                    event_type="document_upload",
                )
            replayed_failure = IngestionStatus(idempotent.status) in {
                IngestionStatus.VALIDATION_FAILED,
                IngestionStatus.PARSING_FAILED,
            }
            await record_document_event(
                self.session,
                event_type="document_upload",
                outcome="error" if replayed_failure else "allow",
                reason_code=(
                    "IDEMPOTENT_FAILURE_REPLAY" if replayed_failure else "IDEMPOTENT_REPLAY"
                ),
                request_id=request_id,
                actor_user_id=context.identity.user_id,
                tenant_id=managed.tenant_id,
                company_id=managed.company_id,
                document_id=managed.id,
                document_version_id=idempotent.id,
                ingestion_job_id=idempotent.ingestion_job.id,
            )
            await self.session.commit()
            if replayed_failure:
                _raise_for_replayed_failure(idempotent)
            return UploadResultData(
                document=_document_data(managed, idempotent), deduplicated=True
            ), False

        try:
            validated = validate_file(
                ValidationInput(
                    filename=filename,
                    declared_content_type=declared_content_type,
                    data=data,
                )
            )
        except FileValidationError as error:
            await self._persist_validation_failure(
                context,
                metadata,
                company=company,
                department=department,
                document=target_document,
                filename=filename,
                declared_content_type=declared_content_type,
                data=data,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                request_id=request_id,
                error=error,
            )
            _raise_for_ingestion_error(error)

        document: Document
        if document_id is None:
            duplicate = await find_initial_duplicate(
                self.session,
                tenant_id=metadata.tenant_id,
                company_id=metadata.company_id,
                department_id=department.id,
                visibility=metadata.visibility.value,
                classification=metadata.classification.value,
                document_type=metadata.document_type.value,
                reporting_period=metadata.reporting_period,
                checksum_sha256=validated.sha256,
            )
            if duplicate is not None:
                await record_document_event(
                    self.session,
                    event_type="document_upload",
                    outcome="allow",
                    reason_code="INITIAL_CHECKSUM_DEDUPLICATED",
                    request_id=request_id,
                    actor_user_id=context.identity.user_id,
                    tenant_id=duplicate.document.tenant_id,
                    company_id=duplicate.document.company_id,
                    document_id=duplicate.document_id,
                    document_version_id=duplicate.id,
                    ingestion_job_id=duplicate.ingestion_job.id,
                )
                await self.session.commit()
                return (
                    UploadResultData(
                        document=_document_data(duplicate.document, duplicate), deduplicated=True
                    ),
                    False,
                )
            document = Document(
                id=uuid4(),
                tenant_id=metadata.tenant_id,
                company_id=metadata.company_id,
                department_id=department.id,
                visibility=metadata.visibility.value,
                classification=metadata.classification.value,
                document_type=metadata.document_type.value,
                reporting_period=metadata.reporting_period,
                created_by_user_id=context.identity.user_id,
                tenant=company.tenant,
                company=company,
                department=department,
            )
            self.session.add(document)
            version_number = 1
        else:
            if target_document is None:
                raise RuntimeError("Explicit version upload has no document")
            document = target_document
            version_number = max(item.version_number for item in document.versions) + 1

        version_id = uuid4()
        version = DocumentVersion(
            id=version_id,
            document=document,
            version_number=version_number,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            original_filename=validated.sanitized_filename,
            safe_filename=validated.sanitized_filename,
            extension=f".{validated.kind.value}",
            declared_media_type=validated.declared_content_type,
            detected_media_type=validated.detected_content_type,
            checksum_sha256=validated.sha256,
            size_bytes=validated.size_bytes,
            status=IngestionStatus.UPLOADED.value,
            warnings=[],
            uploaded_by_user_id=context.identity.user_id,
            pages=[],
            sheets=[],
        )
        job = IngestionJob(
            id=uuid4(),
            document_version=version,
            status=IngestionStatus.UPLOADED.value,
        )
        self.session.add_all([version, job])
        await self.session.flush()
        key = StorageKey.generate(metadata.tenant_id, document.id, version.id)

        self._transition(version, job, IngestionStatus.VALIDATING)
        try:
            stored = self.storage.put_bytes(key, validated.data)
        except ObjectStorageError as error:
            self._transition(
                version,
                job,
                IngestionStatus.VALIDATION_FAILED,
                safe_error_code=error.code.value,
            )
            await record_document_event(
                self.session,
                event_type="document_upload",
                outcome="error",
                reason_code=error.code.value,
                request_id=request_id,
                actor_user_id=context.identity.user_id,
                tenant_id=document.tenant_id,
                company_id=document.company_id,
                document_id=document.id,
                document_version_id=version.id,
                ingestion_job_id=job.id,
            )
            await self.session.commit()
            _raise_for_ingestion_error(error)
        if stored.sha256 != validated.sha256 or stored.size_bytes != validated.size_bytes:
            cleanup_error: ObjectStorageError | None = None
            try:
                self.storage.delete(key)
            except ObjectStorageError as error:
                cleanup_error = error
            storage_conflict = ObjectStorageError(
                IngestionErrorCode.STORAGE_CONFLICT, "Document storage operation failed."
            )
            self._transition(
                version,
                job,
                IngestionStatus.VALIDATION_FAILED,
                safe_error_code=storage_conflict.code.value,
            )
            await record_document_event(
                self.session,
                event_type="document_upload",
                outcome="error",
                reason_code=storage_conflict.code.value,
                request_id=request_id,
                actor_user_id=context.identity.user_id,
                tenant_id=document.tenant_id,
                company_id=document.company_id,
                document_id=document.id,
                document_version_id=version.id,
                ingestion_job_id=job.id,
            )
            if cleanup_error is not None:
                await record_document_event(
                    self.session,
                    event_type="document_storage_cleanup",
                    outcome="error",
                    reason_code=cleanup_error.code.value,
                    request_id=request_id,
                    actor_user_id=context.identity.user_id,
                    tenant_id=document.tenant_id,
                    company_id=document.company_id,
                    document_id=document.id,
                    document_version_id=version.id,
                    ingestion_job_id=job.id,
                )
            await self.session.commit()
            _raise_for_ingestion_error(storage_conflict)
        version.storage_key = key.value

        self._transition(version, job, IngestionStatus.PARSING)
        try:
            parsed = self.parser(validated)
        except (FileParsingError, IngestionError) as error:
            try:
                self.storage.delete(key)
            except ObjectStorageError as cleanup_error:
                await record_document_event(
                    self.session,
                    event_type="document_storage_cleanup",
                    outcome="error",
                    reason_code=cleanup_error.code.value,
                    request_id=request_id,
                    actor_user_id=context.identity.user_id,
                    tenant_id=document.tenant_id,
                    company_id=document.company_id,
                    document_id=document.id,
                    document_version_id=version.id,
                    ingestion_job_id=job.id,
                )
            else:
                version.storage_key = None
            self._transition(
                version,
                job,
                IngestionStatus.PARSING_FAILED,
                safe_error_code=error.code.value,
            )
            await record_document_event(
                self.session,
                event_type="document_parse",
                outcome="error",
                reason_code=error.code.value,
                request_id=request_id,
                actor_user_id=context.identity.user_id,
                tenant_id=document.tenant_id,
                company_id=document.company_id,
                document_id=document.id,
                document_version_id=version.id,
                ingestion_job_id=job.id,
            )
            await self.session.commit()
            _raise_for_ingestion_error(error)

        version.warnings = _warning_records(parsed.warnings)
        version.page_count = parsed.page_count
        version.sheet_count = parsed.sheet_count
        version.row_count = parsed.row_count
        version.cell_count = parsed.cell_count
        for page in parsed.pages:
            version.pages.append(
                ParsedPage(
                    page_number=page.page_number,
                    text=page.text,
                    character_count=len(page.text),
                )
            )
        for sheet_data in parsed.sheets:
            column_count = max(
                (cell.column_number for row in sheet_data.rows for cell in row.cells), default=0
            )
            sheet = ParsedSheet(
                sheet_index=sheet_data.sheet_index,
                name=sheet_data.name,
                row_count=len(sheet_data.rows),
                column_count=column_count,
                rows=[],
            )
            for row_data in sheet_data.rows:
                row = ParsedRow(row_number=row_data.row_number, cells=[])
                row.cells.extend(
                    ParsedCell(
                        column_number=cell.column_number,
                        coordinate=cell.coordinate,
                        value_text=cell.value_text,
                        value_kind=cell.value_kind.value,
                        formula_like=cell.formula_like,
                    )
                    for cell in row_data.cells
                )
                sheet.rows.append(row)
            version.sheets.append(sheet)
        self._transition(version, job, IngestionStatus.PREVIEW_READY)
        await record_document_event(
            self.session,
            event_type="document_upload",
            outcome="allow",
            reason_code="UPLOAD_ACCEPTED",
            request_id=request_id,
            actor_user_id=context.identity.user_id,
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            document_id=document.id,
            document_version_id=version.id,
            ingestion_job_id=job.id,
            metadata={
                "version_number": version.version_number,
                "size_bytes": version.size_bytes,
                "department": metadata.department,
                "visibility": metadata.visibility.value,
                "classification": metadata.classification.value,
                "document_type": metadata.document_type.value,
            },
        )
        await record_document_event(
            self.session,
            event_type="document_parse",
            outcome="allow",
            reason_code="PREVIEW_READY",
            request_id=request_id,
            actor_user_id=context.identity.user_id,
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            document_id=document.id,
            document_version_id=version.id,
            ingestion_job_id=job.id,
            metadata={
                "page_count": version.page_count,
                "sheet_count": version.sheet_count,
                "row_count": version.row_count,
                "cell_count": version.cell_count,
            },
        )
        await self.session.commit()
        return UploadResultData(
            document=_document_data(document, version, job), deduplicated=False
        ), True

    async def status(
        self, context: AuthorizationContext, job_id: UUID, *, request_id: str
    ) -> IngestionStatusData:
        found = await get_job_for_management(self.session, context.scope, job_id)
        if found is None:
            await self._raise_not_found(
                context,
                request_id=request_id,
                event_type="ingestion_status_read",
                message="Ingestion job was not found.",
            )
        document, version, job = found
        await self._authorize_target(
            context,
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            request_id=request_id,
            event_type="ingestion_status_read",
            resource_denial=True,
            document_id=document.id,
        )
        return IngestionStatusData(
            ingestion_job_id=job.id,
            document_id=document.id,
            document_version_id=version.id,
            version_number=version.version_number,
            status=IngestionStatus(job.status),
            safe_error_code=job.safe_error_code,
            warnings=_warnings(version.warnings),
            page_count=version.page_count,
            sheet_count=version.sheet_count,
            row_count=version.row_count,
            cell_count=version.cell_count,
            started_at=job.started_at,
            completed_at=job.completed_at,
            updated_at=job.updated_at,
        )

    async def preview(
        self,
        context: AuthorizationContext,
        document_id: UUID,
        version_id: UUID,
        *,
        request_id: str,
    ) -> DocumentPreviewData:
        found = await get_version_for_management(
            self.session,
            context.scope,
            document_id,
            version_id,
        )
        if found is None:
            await self._raise_not_found(
                context,
                request_id=request_id,
                event_type="document_preview",
            )
        document, version = found
        await self._authorize_target(
            context,
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            request_id=request_id,
            event_type="document_preview",
            resource_denial=True,
            document_id=document.id,
        )
        if IngestionStatus(version.status) not in {
            IngestionStatus.PREVIEW_READY,
            IngestionStatus.APPROVED,
            IngestionStatus.REJECTED,
        }:
            await record_document_event(
                self.session,
                event_type="document_preview",
                outcome="deny",
                reason_code="PREVIEW_UNAVAILABLE",
                request_id=request_id,
                actor_user_id=context.identity.user_id,
                tenant_id=document.tenant_id,
                company_id=document.company_id,
                document_id=document.id,
                document_version_id=version.id,
                ingestion_job_id=version.ingestion_job.id,
            )
            await self.session.commit()
            raise APIError(409, "preview_unavailable", "Document preview is not available.")
        pages = tuple(
            ParsedPageData(page_number=page.page_number, text=page.text) for page in version.pages
        )
        sheets = tuple(
            ParsedSheetData(
                sheet_index=sheet.sheet_index,
                name=sheet.name,
                row_count=sheet.row_count,
                column_count=sheet.column_count,
                rows=tuple(
                    ParsedRowData(
                        row_number=row.row_number,
                        cells=tuple(
                            ParsedCellData(
                                row_number=row.row_number,
                                column_number=cell.column_number,
                                coordinate=cell.coordinate,
                                value=cell.value_text,
                                value_kind=cell.value_kind,
                                formula_like=cell.formula_like,
                            )
                            for cell in row.cells
                        ),
                    )
                    for row in sheet.rows
                ),
            )
            for sheet in version.sheets
        )
        return DocumentPreviewData(
            document=_document_data(document, version), pages=pages, sheets=sheets
        )

    async def approve(
        self,
        context: AuthorizationContext,
        document_id: UUID,
        version_id: UUID,
        *,
        request_id: str,
    ) -> VersionActionData:
        return await self._review(
            context,
            document_id,
            version_id,
            target=IngestionStatus.APPROVED,
            request_id=request_id,
        )

    async def reject(
        self,
        context: AuthorizationContext,
        document_id: UUID,
        version_id: UUID,
        *,
        request_id: str,
    ) -> VersionActionData:
        return await self._review(
            context,
            document_id,
            version_id,
            target=IngestionStatus.REJECTED,
            request_id=request_id,
        )

    async def _review(
        self,
        context: AuthorizationContext,
        document_id: UUID,
        version_id: UUID,
        *,
        target: IngestionStatus,
        request_id: str,
    ) -> VersionActionData:
        found = await get_version_for_management(
            self.session,
            context.scope,
            document_id,
            version_id,
            for_update=True,
        )
        if found is None:
            await self._raise_not_found(
                context,
                request_id=request_id,
                event_type=f"document_{target.value.lower()}",
            )
        document, version = found
        await self._authorize_target(
            context,
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            request_id=request_id,
            event_type=f"document_{target.value.lower()}",
            resource_denial=True,
            document_id=document.id,
        )
        try:
            self._transition(version, version.ingestion_job, target)
        except InvalidIngestionTransition:
            await record_document_event(
                self.session,
                event_type=f"document_{target.value.lower()}",
                outcome="deny",
                reason_code="INVALID_DOCUMENT_STATE",
                request_id=request_id,
                actor_user_id=context.identity.user_id,
                tenant_id=document.tenant_id,
                company_id=document.company_id,
                document_id=document.id,
                document_version_id=version.id,
                ingestion_job_id=version.ingestion_job.id,
            )
            await self.session.commit()
            raise APIError(
                409,
                "invalid_document_state",
                "Document is not in a state that permits this action.",
            ) from None
        actor_id = context.identity.user_id
        generated_chunks: tuple[GeneratedChunk, ...] = ()
        if target == IngestionStatus.APPROVED:
            version.approved_by_user_id = actor_id
            version.approved_at = _now()
            document.current_approved_version_id = version.id
            try:
                generated_chunks = generate_approved_chunks(document, version)
            except (ChunkingError, ValueError) as error:
                reason_code = (
                    error.code.value if isinstance(error, ChunkingError) else "INVALID_SOURCE"
                )
                tenant_id = document.tenant_id
                company_id = document.company_id
                failed_document_id = document.id
                failed_version_id = version.id
                failed_job_id = version.ingestion_job.id
                await self.session.rollback()
                await record_document_event(
                    self.session,
                    event_type="document_chunk_index",
                    outcome="error",
                    reason_code=reason_code,
                    request_id=request_id,
                    actor_user_id=actor_id,
                    tenant_id=tenant_id,
                    company_id=company_id,
                    document_id=failed_document_id,
                    document_version_id=failed_version_id,
                    ingestion_job_id=failed_job_id,
                )
                await self.session.commit()
                raise APIError(
                    422,
                    "indexing_failed",
                    "Document indexing failed safely.",
                ) from None
            deactivated = await replace_active_chunks(
                self.session,
                document,
                version,
                generated_chunks,
            )
        else:
            version.rejected_by_user_id = actor_id
            version.rejected_at = _now()
            deactivated = await deactivate_version_chunks(
                self.session,
                version.id,
                version_status=IngestionStatus.REJECTED,
            )
        if target == IngestionStatus.APPROVED:
            await record_document_event(
                self.session,
                event_type="document_chunk_index",
                outcome="allow",
                reason_code="APPROVED_VERSION_INDEXED",
                request_id=request_id,
                actor_user_id=actor_id,
                tenant_id=document.tenant_id,
                company_id=document.company_id,
                document_id=document.id,
                document_version_id=version.id,
                ingestion_job_id=version.ingestion_job.id,
                metadata={
                    "chunk_count": len(generated_chunks),
                    "deactivated_chunk_count": deactivated,
                },
            )
        else:
            await record_document_event(
                self.session,
                event_type="document_chunk_deactivate",
                outcome="allow",
                reason_code="REJECTED_VERSION_DEACTIVATED",
                request_id=request_id,
                actor_user_id=actor_id,
                tenant_id=document.tenant_id,
                company_id=document.company_id,
                document_id=document.id,
                document_version_id=version.id,
                ingestion_job_id=version.ingestion_job.id,
                metadata={"chunk_count": deactivated},
            )
        await record_document_event(
            self.session,
            event_type=f"document_{target.value.lower()}",
            outcome="allow",
            reason_code=target.value,
            request_id=request_id,
            actor_user_id=actor_id,
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            document_id=document.id,
            document_version_id=version.id,
            ingestion_job_id=version.ingestion_job.id,
        )
        await self.session.commit()
        return VersionActionData(
            document_id=document.id,
            document_version_id=version.id,
            status=target,
            current_approved_version_id=document.current_approved_version_id,
        )

    async def delete(
        self, context: AuthorizationContext, document_id: UUID, *, request_id: str
    ) -> DeleteDocumentData:
        document = await get_document_for_management(
            self.session, context.scope, document_id, for_update=True
        )
        if document is None:
            await self._raise_not_found(
                context,
                request_id=request_id,
                event_type="document_delete",
            )
        await self._authorize_target(
            context,
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            request_id=request_id,
            event_type="document_delete",
            resource_denial=True,
            document_id=document.id,
        )
        keys: list[StorageKey] = []
        deleted_at = _now()
        for version in document.versions:
            if version.storage_key is not None:
                keys.append(StorageKey(value=version.storage_key))
            if version.status != IngestionStatus.DELETED:
                self._transition(version, version.ingestion_job, IngestionStatus.DELETED)
            version.deleted_at = deleted_at
        document.deleted_at = deleted_at
        document.current_approved_version_id = None
        deactivated = await deactivate_document_chunks(self.session, document.id)
        await record_document_event(
            self.session,
            event_type="document_delete",
            outcome="allow",
            reason_code="DELETED",
            request_id=request_id,
            actor_user_id=context.identity.user_id,
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            document_id=document.id,
            metadata={
                "version_count": len(document.versions),
                "chunk_count": deactivated,
            },
        )
        await self.session.commit()
        for key in keys:
            try:
                self.storage.delete(key)
            except ObjectStorageError as error:
                await record_document_event(
                    self.session,
                    event_type="document_storage_cleanup",
                    outcome="error",
                    reason_code=error.code.value,
                    request_id=request_id,
                    actor_user_id=context.identity.user_id,
                    tenant_id=document.tenant_id,
                    company_id=document.company_id,
                    document_id=document.id,
                )
        await self.session.commit()
        return DeleteDocumentData(document_id=document.id)

    async def library(
        self,
        context: AuthorizationContext,
        *,
        tenant_id: UUID | None,
        company_id: UUID | None,
        department: str | None,
        document_type: str | None,
        status: str | None,
        limit: int,
        offset: int,
        request_id: str,
    ) -> DocumentListData:
        await self._require_any_manage_permission(
            context, request_id=request_id, event_type="document_library_read"
        )
        documents, total = await list_manageable_documents(
            self.session,
            context.scope,
            tenant_id=tenant_id,
            company_id=company_id,
            department=department,
            document_type=document_type,
            status=status,
            limit=limit,
            offset=offset,
        )
        for document in documents:
            await self._authorize_target(
                context,
                tenant_id=document.tenant_id,
                company_id=document.company_id,
                request_id=request_id,
                event_type="document_library_read",
                resource_denial=True,
                document_id=document.id,
            )
        return DocumentListData(
            items=tuple(_document_data(document) for document in documents),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def options(
        self, context: AuthorizationContext, *, request_id: str
    ) -> DocumentOptionsData:
        await self._require_any_manage_permission(
            context, request_id=request_id, event_type="document_options_read"
        )
        rows = await list_manageable_options(self.session, context.scope)
        grouped: dict[UUID, tuple[Tenant, list[Company]]] = {}
        for tenant, company in rows:
            await self._authorize_target(
                context,
                tenant_id=tenant.id,
                company_id=company.id,
                request_id=request_id,
                event_type="document_options_read",
                resource_denial=False,
            )
            grouped.setdefault(tenant.id, (tenant, []))[1].append(company)
        tenants = tuple(
            TenantOptionData(
                id=tenant.id,
                slug=tenant.slug,
                name=tenant.name,
                companies=tuple(
                    CompanyOptionData(id=company.id, slug=company.slug, name=company.name)
                    for company in companies
                ),
            )
            for tenant, companies in grouped.values()
        )
        classification_pairs = (
            ClassificationPairData(
                department="finance",
                visibility=DocumentVisibility.DEPARTMENT_PRIVATE,
                classification=DocumentClassification.FINANCE_ONLY,
                label="Finance only",
            ),
            ClassificationPairData(
                department="legal",
                visibility=DocumentVisibility.DEPARTMENT_PRIVATE,
                classification=DocumentClassification.LEGAL_ONLY_CONFIDENTIAL,
                label="Legal only — confidential",
            ),
            ClassificationPairData(
                department="shared",
                visibility=DocumentVisibility.TENANT_SHARED,
                classification=DocumentClassification.TENANT_SHARED,
                label="Tenant shared",
            ),
        )
        document_types = tuple(
            DocumentTypeOptionData(
                value=item,
                label=item.value.replace("_", " ").title(),
                reporting_period_required=item
                in {DocumentType.FINANCIAL_REPORT, DocumentType.SPREADSHEET},
            )
            for item in DocumentType
        )
        return DocumentOptionsData(
            tenants=tenants,
            classification_pairs=classification_pairs,
            document_types=document_types,
            limits=UploadLimitsData(
                max_upload_bytes=self.storage.limits.upload_bytes,
                extensions=(".pdf", ".xlsx", ".csv"),
                mime_types=(
                    "application/pdf",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "text/csv",
                    "application/csv",
                ),
            ),
        )
