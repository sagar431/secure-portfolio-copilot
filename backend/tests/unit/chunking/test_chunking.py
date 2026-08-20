import hashlib
from uuid import UUID

import pytest

from app.chunking import (
    ChunkingError,
    ChunkingErrorCode,
    ChunkingLimits,
    ChunkMetadata,
    chunk_document,
)
from app.ingestion.contracts import (
    FileKind,
    ParsedCell,
    ParsedDocument,
    ParsedPage,
    ParsedRow,
    ParsedSheet,
    ValidationInput,
    ValueKind,
)
from app.ingestion.parsers import parse_validated_file
from app.ingestion.validation import PDF_MIME, XLSX_MIME, validate_file
from tests.fixture_builders import fixture_bytes


def _metadata(**changes: object) -> ChunkMetadata:
    values: dict[str, object] = {
        "tenant_id": UUID("10000000-0000-0000-0000-000000000001"),
        "company_id": UUID("20000000-0000-0000-0000-000000000001"),
        "department": "finance",
        "visibility": "DEPARTMENT_PRIVATE",
        "classification": "FINANCE_ONLY",
        "document_id": UUID("30000000-0000-0000-0000-000000000001"),
        "document_version_id": UUID("40000000-0000-0000-0000-000000000001"),
        "document_version": 2,
        "version_status": "APPROVED",
        "active": True,
        "document_deleted": False,
        "version_deleted": False,
    }
    values.update(changes)
    return ChunkMetadata(**values)  # type: ignore[arg-type]


def _cell(row: int, column: int, coordinate: str, value: str) -> ParsedCell:
    return ParsedCell(
        row_number=row,
        column_number=column,
        coordinate=coordinate,
        value_text=value,
        value_kind=ValueKind.TEXT,
    )


def test_pdf_chunks_never_cross_page_or_heading_boundaries_and_are_deterministic() -> None:
    parsed = ParsedDocument(
        kind=FileKind.PDF,
        pages=(
            ParsedPage(
                page_number=2,
                text="RISK FACTORS\nSecond-page risk detail.",
            ),
            ParsedPage(
                page_number=1,
                text=(
                    "Executive Summary\nRevenue increased in 2025.\n\n"
                    "Drivers of Margin Compression\nFreight and hiring reduced margin."
                ),
            ),
        ),
        page_count=2,
        sheet_count=0,
        row_count=0,
        cell_count=0,
        text_length=140,
    )

    first = chunk_document(parsed, _metadata())
    second = chunk_document(parsed, _metadata())

    assert first == second
    assert [chunk.ordinal for chunk in first] == list(range(len(first)))
    assert [chunk.page_number for chunk in first] == [1, 1, 2]
    assert first[0].content.startswith("Executive Summary")
    assert first[1].content.startswith("Drivers of Margin Compression")
    assert first[2].content.startswith("RISK FACTORS")
    assert all(chunk.sheet_name is None for chunk in first)
    assert all(
        chunk.content_hash == hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        for chunk in first
    )


def test_pdf_long_sections_are_bounded_without_losing_page_provenance() -> None:
    text = "LONG SECTION\n" + " ".join(f"word{index}" for index in range(100))
    parsed = ParsedDocument(
        kind=FileKind.PDF,
        pages=(ParsedPage(page_number=7, text=text),),
        page_count=1,
        sheet_count=0,
        row_count=0,
        cell_count=0,
        text_length=len(text),
    )
    limits = ChunkingLimits(max_content_chars=80)

    chunks = chunk_document(parsed, _metadata(), limits)

    assert len(chunks) > 1
    assert all(chunk.page_number == 7 for chunk in chunks)
    assert all(0 < len(chunk.content) <= 80 for chunk in chunks)


def test_real_pdf_chunks_retain_source_pages() -> None:
    parsed = parse_validated_file(
        validate_file(
            ValidationInput(
                filename="Orion_FY2025_Board_Pack.pdf",
                declared_content_type=PDF_MIME,
                data=fixture_bytes("orion/finance/Orion_FY2025_Board_Pack.pdf"),
            )
        )
    )

    chunks = chunk_document(parsed, _metadata())

    margin = next(chunk for chunk in chunks if "Drivers of Margin Compression" in chunk.content)
    liquidity = next(chunk for chunk in chunks if "Liquidity, Risks" in chunk.content)
    assert margin.page_number == 3
    assert liquidity.page_number == 4
    assert {chunk.page_number for chunk in chunks} == {1, 2, 3, 4}
    assert all(len(chunk.content) <= 2_000 for chunk in chunks)


@pytest.mark.parametrize("kind", [FileKind.XLSX, FileKind.CSV])
def test_spreadsheet_chunks_preserve_sheet_row_and_cell_ranges(kind: FileKind) -> None:
    parsed = ParsedDocument(
        kind=kind,
        sheets=(
            ParsedSheet(
                sheet_index=2,
                name="Metrics",
                rows=(
                    ParsedRow(
                        row_number=3,
                        cells=(_cell(3, 1, "A3", "EBITDA"), _cell(3, 3, "C3", "25")),
                    ),
                ),
            ),
            ParsedSheet(
                sheet_index=1,
                name="P&L",
                rows=(
                    ParsedRow(
                        row_number=2,
                        cells=(_cell(2, 1, "A2", "Revenue"), _cell(2, 2, "B2", "100")),
                    ),
                    ParsedRow(
                        row_number=1,
                        cells=(_cell(1, 1, "A1", "Metric"), _cell(1, 2, "B1", "FY25")),
                    ),
                ),
            ),
        ),
        page_count=0,
        sheet_count=2,
        row_count=3,
        cell_count=6,
        text_length=36,
    )
    limits = ChunkingLimits(max_content_chars=500, spreadsheet_rows_per_chunk=2)

    chunks = chunk_document(parsed, _metadata(), limits)

    assert [(chunk.sheet_name, chunk.row_start, chunk.row_end) for chunk in chunks] == [
        ("P&L", 1, 2),
        ("Metrics", 3, 3),
    ]
    assert [(chunk.cell_start, chunk.cell_end) for chunk in chunks] == [
        ("A1", "B2"),
        ("A3", "C3"),
    ]
    assert all(chunk.page_number is None for chunk in chunks)
    assert chunks[0].content == ('row 1\tA1="Metric"\tB1="FY25"\nrow 2\tA2="Revenue"\tB2="100"')


def test_spreadsheet_oversized_cell_is_split_with_exact_cell_provenance() -> None:
    value = "x" * 200
    parsed = ParsedDocument(
        kind=FileKind.CSV,
        sheets=(
            ParsedSheet(
                sheet_index=1,
                name="CSV",
                rows=(ParsedRow(row_number=1, cells=(_cell(1, 1, "A1", value),)),),
            ),
        ),
        page_count=0,
        sheet_count=1,
        row_count=1,
        cell_count=1,
        text_length=len(value),
    )

    chunks = chunk_document(parsed, _metadata(), ChunkingLimits(max_content_chars=64))

    assert len(chunks) > 1
    assert all(chunk.row_start == chunk.row_end == 1 for chunk in chunks)
    assert all(chunk.cell_start == chunk.cell_end == "A1" for chunk in chunks)
    assert all(len(chunk.content) <= 64 for chunk in chunks)


def test_real_xlsx_chunks_retain_sheet_row_and_cell_provenance() -> None:
    parsed = parse_validated_file(
        validate_file(
            ValidationInput(
                filename="Orion_FY2024_FY2025_Financials.xlsx",
                declared_content_type=XLSX_MIME,
                data=fixture_bytes("orion/finance/Orion_FY2024_FY2025_Financials.xlsx"),
            )
        )
    )

    chunks = chunk_document(parsed, _metadata())

    metric = next(
        chunk for chunk in chunks if "C5" in chunk.content and "EBITDA Margin" in chunk.content
    )
    assert metric.sheet_name == "Metrics"
    assert metric.row_start is not None and metric.row_start <= 5
    assert metric.row_end is not None and metric.row_end >= 5
    assert metric.cell_start is not None
    assert metric.cell_end is not None
    assert metric.page_number is None


def test_real_csv_chunks_retain_inert_values_and_coordinates() -> None:
    parsed = parse_validated_file(
        validate_file(
            ValidationInput(
                filename="unsafe_spreadsheet_cells.csv",
                declared_content_type="text/csv",
                data=fixture_bytes("invalid_inputs/unsafe_spreadsheet_cells.csv"),
            )
        )
    )

    chunks = chunk_document(parsed, _metadata())

    unsafe = next(chunk for chunk in chunks if "HYPERLINK" in chunk.content)
    assert unsafe.source_type is FileKind.CSV
    assert unsafe.sheet_name == "CSV"
    assert unsafe.row_start is not None and unsafe.row_start <= 2 <= unsafe.row_end
    assert unsafe.cell_start == "A1"
    assert unsafe.cell_end == "D4"
    assert "C2=" in unsafe.content


@pytest.mark.parametrize(
    "changes",
    [
        {"version_status": "PREVIEW_READY"},
        {"version_status": "REJECTED"},
        {"active": False},
        {"document_deleted": True},
        {"version_deleted": True},
    ],
)
def test_only_approved_non_deleted_versions_can_be_chunked(changes: dict[str, object]) -> None:
    parsed = ParsedDocument(
        kind=FileKind.PDF,
        pages=(ParsedPage(page_number=1, text="Approved content"),),
        page_count=1,
        sheet_count=0,
        row_count=0,
        cell_count=0,
        text_length=16,
    )

    with pytest.raises(ChunkingError) as captured:
        chunk_document(parsed, _metadata(**changes))

    assert captured.value.code is ChunkingErrorCode.INVALID_LIFECYCLE
    assert str(captured.value) == "Document chunking failed."


def test_chunk_count_limit_fails_closed_without_content_in_error() -> None:
    parsed = ParsedDocument(
        kind=FileKind.PDF,
        pages=(
            ParsedPage(page_number=1, text="FIRST HEADING\nsecret one\nSECOND HEADING\nsecret two"),
        ),
        page_count=1,
        sheet_count=0,
        row_count=0,
        cell_count=0,
        text_length=52,
    )

    with pytest.raises(ChunkingError) as captured:
        chunk_document(parsed, _metadata(), ChunkingLimits(max_chunks=1))

    assert captured.value.code is ChunkingErrorCode.RESULT_LIMIT_EXCEEDED
    assert "secret" not in str(captured.value)


@pytest.mark.parametrize("kind", [FileKind.PDF, FileKind.XLSX, FileKind.CSV])
def test_approved_blank_source_fails_before_replacing_an_index(kind: FileKind) -> None:
    parsed = ParsedDocument(
        kind=kind,
        pages=(ParsedPage(page_number=1, text=""),) if kind is FileKind.PDF else (),
        sheets=(ParsedSheet(sheet_index=1, name="CSV", rows=()),)
        if kind is not FileKind.PDF
        else (),
        page_count=1 if kind is FileKind.PDF else 0,
        sheet_count=0 if kind is FileKind.PDF else 1,
        row_count=0,
        cell_count=0,
        text_length=0,
    )

    with pytest.raises(ChunkingError) as captured:
        chunk_document(parsed, _metadata())

    assert captured.value.code is ChunkingErrorCode.INVALID_SOURCE
