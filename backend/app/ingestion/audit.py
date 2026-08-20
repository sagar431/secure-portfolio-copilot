import logging
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.documents import DocumentAuditEvent

logger = logging.getLogger("app.ingestion.audit")


async def record_document_event(
    session: AsyncSession,
    *,
    event_type: str,
    outcome: str,
    reason_code: str,
    request_id: str,
    actor_user_id: UUID | None,
    tenant_id: UUID | None = None,
    company_id: UUID | None = None,
    document_id: UUID | None = None,
    document_version_id: UUID | None = None,
    ingestion_job_id: UUID | None = None,
    metadata: Mapping[str, str | int | bool | None] | None = None,
) -> DocumentAuditEvent:
    """Persist and log a metadata-only document decision."""
    safe_metadata = dict(metadata or {})
    event = DocumentAuditEvent(
        tenant_id=tenant_id,
        company_id=company_id,
        actor_user_id=actor_user_id,
        document_id=document_id,
        document_version_id=document_version_id,
        ingestion_job_id=ingestion_job_id,
        event_type=event_type,
        outcome=outcome,
        reason_code=reason_code,
        request_id=request_id,
        event_metadata=safe_metadata,
    )
    session.add(event)

    log_metadata: dict[str, str | int | bool | None] = {
        "event": event_type,
        "outcome": outcome,
        "reason_code": reason_code,
        "request_id": request_id,
    }
    if actor_user_id is not None:
        log_metadata["actor_user_id"] = str(actor_user_id)
    if document_id is not None:
        log_metadata["document_id"] = str(document_id)
    if document_version_id is not None:
        log_metadata["document_version_id"] = str(document_version_id)
    if ingestion_job_id is not None:
        log_metadata["ingestion_job_id"] = str(ingestion_job_id)
    logger.info("document_event", extra=log_metadata)
    return event
