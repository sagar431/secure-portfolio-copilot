from uuid import uuid4

import pytest

from app.chat.contracts import GroundedAnswerDraft, GroundedClaimDraft, GroundedEvidence
from app.chat.service import GroundingValidationError, validate_grounded_answer


def _evidence() -> GroundedEvidence:
    return GroundedEvidence(
        evidence_id="ev_1",
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        version_number=2,
        document_title="synthetic.xlsx",
        excerpt="Revenue was 10.",
        page_number=None,
        sheet_name="Summary",
        row_start=2,
        row_end=2,
        cell_start="A2",
        cell_end="B2",
    )


def test_validator_reconstructs_exact_provenance_from_host_evidence() -> None:
    evidence = _evidence()
    answer = validate_grounded_answer(
        GroundedAnswerDraft(
            status="supported",
            claims=(GroundedClaimDraft("Revenue was 10.", ("ev_1",)),),
        ),
        (evidence,),
    )

    assert answer.claims[0].citation_ids == ("ev_1",)
    assert answer.citations[0].document_id == evidence.document_id
    assert answer.citations[0].document_version_id == evidence.document_version_id
    assert answer.citations[0].chunk_id == evidence.chunk_id
    assert answer.citations[0].sheet_name == "Summary"
    assert answer.citations[0].cell_start == "A2"


@pytest.mark.parametrize(
    "draft",
    [
        GroundedAnswerDraft("supported", (GroundedClaimDraft("Unsupported.", ()),)),
        GroundedAnswerDraft("supported", (GroundedClaimDraft("Fabricated.", ("ev_9",)),)),
        GroundedAnswerDraft("supported", ()),
        GroundedAnswerDraft(
            "insufficient_evidence", (GroundedClaimDraft("Contradiction.", ("ev_1",)),)
        ),
    ],
)
def test_validator_fails_closed_for_incomplete_or_fabricated_citations(
    draft: GroundedAnswerDraft,
) -> None:
    with pytest.raises(GroundingValidationError):
        validate_grounded_answer(draft, (_evidence(),))
