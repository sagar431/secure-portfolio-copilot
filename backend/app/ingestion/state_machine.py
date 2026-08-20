from app.models.documents import IngestionStatus


class InvalidIngestionTransition(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[IngestionStatus, frozenset[IngestionStatus]] = {
    IngestionStatus.UPLOADED: frozenset({IngestionStatus.VALIDATING, IngestionStatus.DELETED}),
    IngestionStatus.VALIDATING: frozenset(
        {
            IngestionStatus.PARSING,
            IngestionStatus.VALIDATION_FAILED,
            IngestionStatus.DELETED,
        }
    ),
    IngestionStatus.PARSING: frozenset(
        {
            IngestionStatus.PREVIEW_READY,
            IngestionStatus.PARSING_FAILED,
            IngestionStatus.DELETED,
        }
    ),
    IngestionStatus.PREVIEW_READY: frozenset(
        {IngestionStatus.APPROVED, IngestionStatus.REJECTED, IngestionStatus.DELETED}
    ),
    IngestionStatus.APPROVED: frozenset({IngestionStatus.DELETED}),
    IngestionStatus.REJECTED: frozenset({IngestionStatus.DELETED}),
    IngestionStatus.VALIDATION_FAILED: frozenset({IngestionStatus.DELETED}),
    IngestionStatus.PARSING_FAILED: frozenset({IngestionStatus.DELETED}),
    IngestionStatus.DELETED: frozenset(),
}


def validate_transition(current: IngestionStatus | str, target: IngestionStatus | str) -> None:
    current_status = IngestionStatus(current)
    target_status = IngestionStatus(target)
    if target_status not in _ALLOWED_TRANSITIONS[current_status]:
        raise InvalidIngestionTransition(
            f"Transition from {current_status.value} to {target_status.value} is not allowed."
        )


def transition_allowed(current: IngestionStatus | str, target: IngestionStatus | str) -> bool:
    try:
        validate_transition(current, target)
    except (InvalidIngestionTransition, ValueError):
        return False
    return True
