import pytest

from app.ingestion.state_machine import InvalidIngestionTransition, transition_allowed
from app.models.documents import IngestionStatus


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (IngestionStatus.UPLOADED, IngestionStatus.VALIDATING),
        (IngestionStatus.VALIDATING, IngestionStatus.PARSING),
        (IngestionStatus.VALIDATING, IngestionStatus.VALIDATION_FAILED),
        (IngestionStatus.PARSING, IngestionStatus.PREVIEW_READY),
        (IngestionStatus.PARSING, IngestionStatus.PARSING_FAILED),
        (IngestionStatus.PREVIEW_READY, IngestionStatus.APPROVED),
        (IngestionStatus.PREVIEW_READY, IngestionStatus.REJECTED),
        (IngestionStatus.APPROVED, IngestionStatus.DELETED),
        (IngestionStatus.REJECTED, IngestionStatus.DELETED),
        (IngestionStatus.VALIDATION_FAILED, IngestionStatus.DELETED),
        (IngestionStatus.PARSING_FAILED, IngestionStatus.DELETED),
    ],
)
def test_allowed_ingestion_transitions(current: IngestionStatus, target: IngestionStatus) -> None:
    assert transition_allowed(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (IngestionStatus.UPLOADED, IngestionStatus.APPROVED),
        (IngestionStatus.PREVIEW_READY, IngestionStatus.PARSING),
        (IngestionStatus.REJECTED, IngestionStatus.APPROVED),
        (IngestionStatus.VALIDATION_FAILED, IngestionStatus.APPROVED),
        (IngestionStatus.PARSING_FAILED, IngestionStatus.APPROVED),
        (IngestionStatus.DELETED, IngestionStatus.PREVIEW_READY),
    ],
)
def test_invalid_ingestion_transitions_fail_closed(
    current: IngestionStatus, target: IngestionStatus
) -> None:
    assert not transition_allowed(current, target)


def test_deleted_is_terminal() -> None:
    with pytest.raises(InvalidIngestionTransition):
        from app.ingestion.state_machine import validate_transition

        validate_transition(IngestionStatus.DELETED, IngestionStatus.UPLOADED)
