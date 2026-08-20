import pytest

from app.ingestion.contracts import FileKind, ValidationInput, ValueKind
from app.ingestion.parsers import parse_validated_file
from app.ingestion.validation import XLSX_MIME, validate_file
from tests.fixture_builders import fixture_bytes

EXPECTED_SHEETS = [
    "Cover",
    "P&L",
    "Balance Sheet",
    "Cash Flow",
    "Metrics",
    "Sources",
    "Checks",
]


@pytest.mark.parametrize(
    ("relative_path", "filename"),
    [
        (
            "orion/finance/Orion_FY2024_FY2025_Financials.xlsx",
            "Orion_FY2024_FY2025_Financials.xlsx",
        ),
        (
            "atlas/finance/Atlas_FY2024_FY2025_Financials.xlsx",
            "Atlas_FY2024_FY2025_Financials.xlsx",
        ),
    ],
)
def test_workbook_preserves_sheet_row_and_cell_provenance(
    relative_path: str, filename: str
) -> None:
    validated = validate_file(
        ValidationInput(
            filename=filename,
            declared_content_type=XLSX_MIME,
            data=fixture_bytes(relative_path),
        )
    )

    result = parse_validated_file(validated)

    assert result.kind == FileKind.XLSX
    assert result.sheet_count == 7
    assert [sheet.name for sheet in result.sheets] == EXPECTED_SHEETS
    metrics = next(sheet for sheet in result.sheets if sheet.name == "Metrics")
    cells = {cell.coordinate: cell for row in metrics.rows for cell in row.cells}
    assert cells["C4"].row_number == 4
    assert cells["C4"].column_number == 3
    assert cells["C4"].value_kind == ValueKind.FORMULA
    assert cells["C4"].value_text.startswith("=")
    assert cells["C4"].formula_like
    assert "FORMULA_LIKE_CELLS" in result.warnings


def test_unsafe_csv_values_remain_exact_inert_text() -> None:
    data = fixture_bytes("invalid_inputs/unsafe_spreadsheet_cells.csv")
    validated = validate_file(
        ValidationInput(
            filename="unsafe_spreadsheet_cells.csv",
            declared_content_type="text/csv",
            data=data,
        )
    )

    result = parse_validated_file(validated)

    assert result.sheet_count == 1
    assert result.row_count == 4
    assert result.cell_count == 16
    cells = {cell.coordinate: cell for row in result.sheets[0].rows for cell in row.cells}
    assert cells["C2"].value_text == '\'=HYPERLINK("https://example.invalid","click")'
    assert cells["C3"].value_text == "'+cmd|'/C calc'!A0"
    assert cells["C2"].formula_like and cells["C3"].formula_like
    assert cells["C2"].value_kind == ValueKind.TEXT
    assert result.warnings == ("FORMULA_LIKE_CELLS",)
