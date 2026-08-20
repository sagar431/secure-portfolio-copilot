import pytest

from app.ingestion.contracts import FileKind, ValidationInput
from app.ingestion.errors import FileParsingError, IngestionErrorCode
from app.ingestion.parsers import parse_validated_file
from app.ingestion.validation import PDF_MIME, validate_file
from app.ingestion.worker import parse_in_worker
from tests.fixture_builders import active_pdf_bytes, encrypted_pdf_bytes, fixture_bytes


@pytest.mark.parametrize(
    ("relative_path", "filename", "expected_text"),
    [
        (
            "orion/finance/Orion_FY2025_Board_Pack.pdf",
            "Orion_FY2025_Board_Pack.pdf",
            "Drivers of Margin Compression",
        ),
        (
            "atlas/finance/Atlas_FY2025_Board_Pack.pdf",
            "Atlas_FY2025_Board_Pack.pdf",
            "Drivers of Margin Expansion",
        ),
    ],
)
def test_board_pack_preserves_page_provenance(
    relative_path: str, filename: str, expected_text: str
) -> None:
    validated = validate_file(
        ValidationInput(
            filename=filename,
            declared_content_type=PDF_MIME,
            data=fixture_bytes(relative_path),
        )
    )

    result = parse_validated_file(validated)

    assert result.kind == FileKind.PDF
    assert result.page_count == 4
    assert [page.page_number for page in result.pages] == [1, 2, 3, 4]
    assert any(expected_text in page.text for page in result.pages)
    assert result.sheet_count == 0


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (encrypted_pdf_bytes(), IngestionErrorCode.PDF_ENCRYPTED),
        (active_pdf_bytes(), IngestionErrorCode.PDF_ACTIVE_CONTENT),
    ],
)
def test_encrypted_and_active_pdfs_are_rejected(data: bytes, code: IngestionErrorCode) -> None:
    validated = validate_file(
        ValidationInput(filename="unsafe.pdf", declared_content_type=PDF_MIME, data=data)
    )

    with pytest.raises(FileParsingError) as captured:
        parse_validated_file(validated)

    assert captured.value.code == code
    assert str(captured.value) == "File parsing failed."


def test_fixed_worker_process_parses_with_resource_boundary() -> None:
    validated = validate_file(
        ValidationInput(
            filename="Orion_FY2025_Board_Pack.pdf",
            declared_content_type=PDF_MIME,
            data=fixture_bytes("orion/finance/Orion_FY2025_Board_Pack.pdf"),
        )
    )

    result = parse_in_worker(validated)

    assert result.page_count == 4
