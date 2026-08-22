import logging
from uuid import UUID

logger = logging.getLogger("app.evaluations.audit")


def record_evaluation_event(
    *, event: str, outcome: str, reason_code: str, request_id: str, run_id: UUID | None = None
) -> None:
    """Emit identifiers and bounded codes only; evaluation content is never logged."""
    logger.info(
        "evaluation_event",
        extra={
            "evaluation_event": event,
            "outcome": outcome,
            "reason_code": reason_code,
            "request_id": request_id,
            "run_id": str(run_id) if run_id else None,
        },
    )
