from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models.documents import Document, DocumentVersion, IngestionStatus
from app.retrieval.indexing import generate_approved_chunks


@pytest.mark.parametrize(
    ("status", "current_matches", "document_deleted", "version_deleted"),
    [
        (IngestionStatus.PREVIEW_READY.value, True, False, False),
        (IngestionStatus.REJECTED.value, True, False, False),
        (IngestionStatus.APPROVED.value, False, False, False),
        (IngestionStatus.APPROVED.value, True, True, False),
        (IngestionStatus.APPROVED.value, True, False, True),
    ],
)
def test_chunk_adapter_rejects_every_non_current_approved_lifecycle(
    status: str,
    current_matches: bool,
    document_deleted: bool,
    version_deleted: bool,
) -> None:
    document_id = uuid4()
    version_id = uuid4()
    version = DocumentVersion(id=version_id, document_id=document_id, status=status)
    document = Document(
        id=document_id,
        current_approved_version_id=version_id if current_matches else uuid4(),
        deleted_at=datetime.now(UTC) if document_deleted else None,
    )
    version.deleted_at = datetime.now(UTC) if version_deleted else None

    with pytest.raises(ValueError) as captured:
        generate_approved_chunks(document, version)

    assert str(captured.value) == "Document version is not the current approved version."
