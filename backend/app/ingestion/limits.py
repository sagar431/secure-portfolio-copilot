from dataclasses import dataclass

MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class IngestionLimits:
    upload_bytes: int = 10 * MIB
    stream_chunk_bytes: int = 64 * 1024
    parser_timeout_seconds: float = 15.0
    total_text_characters: int = 2_000_000
    pdf_pages: int = 200
    pdf_page_text_characters: int = 100_000
    pdf_page_decoded_bytes: int = 5 * MIB
    pdf_total_decoded_bytes: int = 50 * MIB
    pdf_root_recovery_objects: int = 1_000
    xlsx_zip_members: int = 2_048
    xlsx_largest_member_bytes: int = 10 * MIB
    xlsx_total_expanded_bytes: int = 100 * MIB
    xlsx_expansion_ratio: int = 100
    spreadsheet_sheets: int = 50
    spreadsheet_rows_per_sheet: int = 10_000
    spreadsheet_columns_per_row: int = 200
    spreadsheet_total_cells: int = 200_000
    spreadsheet_cell_characters: int = 32_767


DEFAULT_LIMITS = IngestionLimits()
