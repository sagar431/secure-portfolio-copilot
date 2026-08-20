import hashlib

import pytest

from app.ingestion.contracts import FileKind, ValidationInput
from app.ingestion.errors import FileValidationError, IngestionErrorCode
from app.ingestion.limits import IngestionLimits
from app.ingestion.validation import PDF_MIME, XLSX_MIME, sanitize_filename, validate_file
from tests.fixture_builders import fixture_bytes, xlsx_with_extra_member


@pytest.mark.parametrize(
    ("relative_path", "filename", "content_type", "kind", "expected_hash"),
    [
        (
            "orion/finance/Orion_FY2025_Board_Pack.pdf",
            "Orion_FY2025_Board_Pack.pdf",
            PDF_MIME,
            FileKind.PDF,
            "a7ff74b627185989b311713a9b44be2bfdb028cb9abcbde6a0240cd343e534be",
        ),
        (
            "atlas/finance/Atlas_FY2024_FY2025_Financials.xlsx",
            "Atlas_FY2024_FY2025_Financials.xlsx",
            XLSX_MIME,
            FileKind.XLSX,
            "012e7838032adcc8d4ccacc45554329fcb7150b8f00cfda0e575f7f4707bc89a",
        ),
        (
            "invalid_inputs/unsafe_spreadsheet_cells.csv",
            "unsafe_spreadsheet_cells.csv",
            "text/csv; charset=utf-8",
            FileKind.CSV,
            "ddba071a512dc2d5c6b75033a00b9cabaf25964d62015956988b7c1c9444feab",
        ),
    ],
)
def test_valid_files_are_classified_and_hashed(
    relative_path: str,
    filename: str,
    content_type: str,
    kind: FileKind,
    expected_hash: str,
) -> None:
    data = fixture_bytes(relative_path)

    result = validate_file(
        ValidationInput(filename=filename, declared_content_type=content_type, data=data)
    )

    assert result.kind == kind
    assert result.sha256 == expected_hash == hashlib.sha256(data).hexdigest()
    assert result.size_bytes == len(data)


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "code"),
    [
        (
            "file.exe",
            "application/octet-stream",
            b"not supported",
            IngestionErrorCode.UNSUPPORTED_FILE_TYPE,
        ),
        ("file.pdf", "text/csv", b"%PDF-1.4\n%%EOF", IngestionErrorCode.CONTENT_TYPE_MISMATCH),
        ("file.csv", "application/pdf", b"a,b\n1,2\n", IngestionErrorCode.CONTENT_TYPE_MISMATCH),
        ("file.pdf", PDF_MIME, b"plain text", IngestionErrorCode.INVALID_FILE_SIGNATURE),
        ("file.pdf", PDF_MIME, b"%PDF-1.4\nmissing eof", IngestionErrorCode.MALFORMED_FILE),
        ("file.xlsx", XLSX_MIME, b"not a zip", IngestionErrorCode.INVALID_FILE_SIGNATURE),
        ("file.csv", "text/csv", b"a,b\n1\n", IngestionErrorCode.MALFORMED_FILE),
        ("file.csv", "text/csv", b"a,\x00b\n", IngestionErrorCode.MALFORMED_FILE),
    ],
)
def test_invalid_type_mime_signature_and_structure_fail_safely(
    filename: str,
    content_type: str,
    data: bytes,
    code: IngestionErrorCode,
) -> None:
    with pytest.raises(FileValidationError) as captured:
        validate_file(
            ValidationInput(
                filename=filename,
                declared_content_type=content_type,
                data=data,
            )
        )

    assert captured.value.code == code
    assert str(captured.value) == "File validation failed."


def test_simulated_fake_pdf_is_rejected_by_signature() -> None:
    with pytest.raises(FileValidationError) as captured:
        validate_file(
            ValidationInput(
                filename="not_a_real_pdf.pdf",
                declared_content_type=PDF_MIME,
                data=fixture_bytes("invalid_inputs/not_a_real_pdf.pdf"),
            )
        )

    assert captured.value.code == IngestionErrorCode.INVALID_FILE_SIGNATURE


def test_upload_size_is_bounded() -> None:
    limits = IngestionLimits(upload_bytes=8)
    with pytest.raises(FileValidationError) as captured:
        validate_file(
            ValidationInput(
                filename="oversized.csv",
                declared_content_type="text/csv",
                data=b"a,b\n123,456\n",
            ),
            limits,
        )

    assert captured.value.code == IngestionErrorCode.FILE_TOO_LARGE


def test_encrypted_office_container_is_rejected() -> None:
    compound_file = bytes.fromhex("D0CF11E0A1B11AE1") + b"synthetic encrypted package"

    with pytest.raises(FileValidationError) as captured:
        validate_file(
            ValidationInput(
                filename="encrypted.xlsx",
                declared_content_type=XLSX_MIME,
                data=compound_file,
            )
        )

    assert captured.value.code == IngestionErrorCode.XLSX_ENCRYPTED


@pytest.mark.parametrize(
    ("member", "code"),
    [
        ("xl/vbaProject.bin", IngestionErrorCode.XLSX_MACRO_FORBIDDEN),
        ("xl/externalLinks/externalLink1.xml", IngestionErrorCode.XLSX_EXTERNAL_LINK_FORBIDDEN),
        ("../escaped.xml", IngestionErrorCode.MALFORMED_FILE),
    ],
)
def test_unsafe_ooxml_members_are_rejected(member: str, code: IngestionErrorCode) -> None:
    source = fixture_bytes("orion/finance/Orion_FY2024_FY2025_Financials.xlsx")
    malicious = xlsx_with_extra_member(source, member)

    with pytest.raises(FileValidationError) as captured:
        validate_file(
            ValidationInput(
                filename="unsafe.xlsx",
                declared_content_type=XLSX_MIME,
                data=malicious,
            )
        )

    assert captured.value.code == code


def test_ooxml_expansion_ratio_is_bounded() -> None:
    source = fixture_bytes("orion/finance/Orion_FY2024_FY2025_Financials.xlsx")
    compressed_bomb = xlsx_with_extra_member(source, "xl/media/bomb.bin", b"0" * 2_000_000)

    with pytest.raises(FileValidationError) as captured:
        validate_file(
            ValidationInput(
                filename="bomb.xlsx",
                declared_content_type=XLSX_MIME,
                data=compressed_bomb,
            )
        )

    assert captured.value.code == IngestionErrorCode.ZIP_LIMIT_EXCEEDED


def test_filename_is_display_only_and_sanitized() -> None:
    assert sanitize_filename("../../Orion Board Pack.pdf") == "Orion Board Pack.pdf"
    assert sanitize_filename(r"C:\fake\Atlas.xlsx") == "Atlas.xlsx"
    with pytest.raises(FileValidationError):
        sanitize_filename("unsafe\u202e.pdf")
