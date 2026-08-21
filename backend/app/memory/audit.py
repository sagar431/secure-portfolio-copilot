import logging
from uuid import UUID

from app.policies.models import AuthorizationContext

logger = logging.getLogger("app.memory.audit")


def record_memory_event(
    context: AuthorizationContext,
    *,
    action: str,
    outcome: str,
    memory_id: UUID | None = None,
    scope: str | None = None,
    result_count: int | None = None,
) -> None:
    """Emit metadata only; memory content and search text must never reach logs."""
    logger.info(
        "memory_event",
        extra={
            "action": action,
            "outcome": outcome,
            "user_id": str(context.identity.user_id),
            "workspace_ids": sorted(str(grant.workspace_id) for grant in context.scope.grants),
            "memory_id": str(memory_id) if memory_id is not None else None,
            "memory_scope": scope,
            "result_count": result_count,
        },
    )
