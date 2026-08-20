import logging
from uuid import UUID

logger = logging.getLogger("app.auth.audit")


def record_auth_event(
    *,
    event: str,
    outcome: str,
    reason_code: str,
    request_id: str,
    user_id: UUID | None = None,
) -> None:
    """Record metadata-only authentication events without credentials or tokens."""
    metadata: dict[str, str] = {
        "event": event,
        "outcome": outcome,
        "reason_code": reason_code,
        "request_id": request_id,
    }
    if user_id is not None:
        metadata["user_id"] = str(user_id)
    logger.info("auth_event", extra=metadata)
