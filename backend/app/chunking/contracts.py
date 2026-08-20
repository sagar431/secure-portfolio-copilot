from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.ingestion.contracts import FileKind


class ChunkingErrorCode(StrEnum):
    INVALID_LIFECYCLE = "INVALID_LIFECYCLE"
    INVALID_SOURCE = "INVALID_SOURCE"
    SOURCE_LIMIT_EXCEEDED = "SOURCE_LIMIT_EXCEEDED"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"


class ChunkingError(ValueError):
    """A content-free error safe to map to an ingestion failure code."""

    def __init__(self, code: ChunkingErrorCode) -> None:
        self.code = code
        super().__init__("Document chunking failed.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ChunkingLimits:
    max_content_chars: int = 2_000
    max_chunks: int = 5_000
    max_source_chars: int = 1_000_000
    max_pages: int = 1_000
    max_sheets: int = 100
    max_rows: int = 100_000
    max_cells: int = 500_000
    spreadsheet_rows_per_chunk: int = 25

    def __post_init__(self) -> None:
        values = (
            self.max_content_chars,
            self.max_chunks,
            self.max_source_chars,
            self.max_pages,
            self.max_sheets,
            self.max_rows,
            self.max_cells,
            self.spreadsheet_rows_per_chunk,
        )
        if any(value <= 0 for value in values):
            raise ValueError("Chunking limits must be positive.")
        if self.max_content_chars < 32:
            raise ValueError("Chunk content limit is too small for provenance-safe rendering.")


DEFAULT_LIMITS = ChunkingLimits()


@dataclass(frozen=True, slots=True, kw_only=True)
class ChunkMetadata:
    tenant_id: UUID
    company_id: UUID
    department: str
    visibility: str
    classification: str
    document_id: UUID
    document_version_id: UUID
    document_version: int
    version_status: str
    active: bool
    document_deleted: bool = False
    version_deleted: bool = False

    def __post_init__(self) -> None:
        if self.document_version < 1:
            raise ValueError("Document version must be positive.")
        if not self.department or not self.visibility or not self.classification:
            raise ValueError("Chunk security metadata must be non-empty.")


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneratedChunk:
    ordinal: int
    tenant_id: UUID
    company_id: UUID
    department: str
    visibility: str
    classification: str
    document_id: UUID
    document_version_id: UUID
    document_version: int
    version_status: str
    active: bool
    source_type: FileKind
    content: str
    content_hash: str
    page_number: int | None = None
    sheet_name: str | None = None
    row_start: int | None = None
    row_end: int | None = None
    cell_start: str | None = None
    cell_end: str | None = None

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("Chunk ordinal must be non-negative.")
        if not self.content:
            raise ValueError("Chunk content must be non-empty.")
        is_pdf = self.page_number is not None
        is_spreadsheet = all(
            value is not None
            for value in (
                self.sheet_name,
                self.row_start,
                self.row_end,
                self.cell_start,
                self.cell_end,
            )
        )
        if is_pdf == is_spreadsheet:
            raise ValueError("Chunk must have exactly one source-location family.")
        if is_pdf and any(
            value is not None
            for value in (
                self.sheet_name,
                self.row_start,
                self.row_end,
                self.cell_start,
                self.cell_end,
            )
        ):
            raise ValueError("PDF chunk cannot contain spreadsheet provenance.")
        if is_spreadsheet and self.page_number is not None:
            raise ValueError("Spreadsheet chunk cannot contain page provenance.")
        if (
            self.row_start is not None
            and self.row_end is not None
            and self.row_start > self.row_end
        ):
            raise ValueError("Spreadsheet row range is invalid.")
