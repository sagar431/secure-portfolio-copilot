import io

import pytest

from app.ingestion.contracts import ValidationInput
from app.ingestion.errors import FileValidationError, IngestionErrorCode, ObjectStorageError
from app.ingestion.limits import IngestionLimits
from app.ingestion.parsers import parse_validated_file
from app.ingestion.storage import LocalObjectStorage
from app.ingestion.validation import PDF_MIME, XLSX_MIME, validate_file
from tests.fixture_builders import fixture_bytes, xlsx_with_extra_member


def test_parser_errors_do_not_disclose_input_content_or_host_paths() -> None:
    sensitive = b"secret-cell-value,/home/private/document.pdf"

    with pytest.raises(FileValidationError) as captured:
        validate_file(
            ValidationInput(
                filename="private.pdf",
                declared_content_type=PDF_MIME,
                data=sensitive,
            )
        )

    rendered = str(captured.value)
    assert rendered == "File validation failed."
    assert "secret-cell-value" not in rendered
    assert "/home/private" not in rendered
    assert "private.pdf" not in rendered


def test_macro_and_external_link_members_fail_closed() -> None:
    source = fixture_bytes("orion/finance/Orion_FY2024_FY2025_Financials.xlsx")
    cases = (
        ("xl/vbaProject.bin", IngestionErrorCode.XLSX_MACRO_FORBIDDEN),
        (
            "xl/externalLinks/externalLink1.xml",
            IngestionErrorCode.XLSX_EXTERNAL_LINK_FORBIDDEN,
        ),
    )
    for member, expected in cases:
        with pytest.raises(FileValidationError) as captured:
            validate_file(
                ValidationInput(
                    filename="unsafe.xlsx",
                    declared_content_type=XLSX_MIME,
                    data=xlsx_with_extra_member(source, member),
                )
            )
        assert captured.value.code == expected


def test_formula_like_csv_is_never_interpreted_or_rewritten() -> None:
    source = fixture_bytes("invalid_inputs/unsafe_spreadsheet_cells.csv")
    validated = validate_file(
        ValidationInput(
            filename="unsafe_spreadsheet_cells.csv",
            declared_content_type="text/csv",
            data=source,
        )
    )

    parsed = parse_validated_file(validated)

    values = [cell.value_text for row in parsed.sheets[0].rows for cell in row.cells]
    assert '\'=HYPERLINK("https://example.invalid","click")' in values
    assert "'+cmd|'/C calc'!A0" in values
    assert source == fixture_bytes("invalid_inputs/unsafe_spreadsheet_cells.csv")


def test_storage_limit_error_contains_no_key_or_root(tmp_path: object) -> None:
    storage = LocalObjectStorage(
        tmp_path,  # type: ignore[arg-type]
        IngestionLimits(upload_bytes=4, stream_chunk_bytes=2),
    )
    from uuid import uuid4

    from app.ingestion.contracts import StorageKey

    key = StorageKey.generate(uuid4(), uuid4(), uuid4())
    with pytest.raises(ObjectStorageError) as captured:
        storage.put_stream(key, io.BytesIO(b"oversized"))

    rendered = str(captured.value)
    assert rendered == "Document storage operation failed."
    assert key.value not in rendered
    assert str(tmp_path) not in rendered
