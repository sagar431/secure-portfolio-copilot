from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from app.chunking.contracts import (
    DEFAULT_LIMITS,
    ChunkingError,
    ChunkingErrorCode,
    ChunkingLimits,
    ChunkMetadata,
    GeneratedChunk,
)
from app.ingestion.contracts import FileKind, ParsedCell, ParsedDocument, ParsedRow

_NUMBERED_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?|[A-Z][.)])\s+\S")
_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+\S")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


@dataclass(frozen=True, slots=True)
class _SpreadsheetUnit:
    row_number: int
    cell_start: str
    cell_end: str
    content: str


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    return "\n".join(line.rstrip() for line in value.split("\n")).strip()


def _is_heading(line: str) -> bool:
    candidate = line.strip()
    if not candidate or len(candidate) > 120 or "\t" in candidate:
        return False
    if _MARKDOWN_HEADING.match(candidate) or _NUMBERED_HEADING.match(candidate):
        return True
    words = _WORD.findall(candidate)
    if not words or len(words) > 14:
        return False
    letters = "".join(character for character in candidate if character.isalpha())
    if letters and letters.upper() == letters:
        return True
    if candidate.endswith((".", ";", ",", "?", "!")):
        return False
    significant = [word for word in words if len(word) > 3]
    return len(words) >= 2 and bool(significant) and all(word[0].isupper() for word in significant)


def _pdf_sections(text: str) -> tuple[str, ...]:
    sections: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        if _is_heading(line) and any(item.strip() for item in current):
            section = "\n".join(current).strip()
            if section:
                sections.append(section)
            current = [line]
        else:
            current.append(line)
    section = "\n".join(current).strip()
    if section:
        sections.append(section)
    return tuple(sections)


def _bounded_text(value: str, maximum: int) -> tuple[str, ...]:
    """Split normalized text without producing an oversized or empty result."""

    remaining = value.strip()
    parts: list[str] = []
    while remaining:
        if len(remaining) <= maximum:
            parts.append(remaining)
            break
        window = remaining[: maximum + 1]
        lower_bound = maximum // 2
        candidates = (
            window.rfind("\n\n", lower_bound, maximum + 1),
            window.rfind("\n", lower_bound, maximum + 1),
            window.rfind(" ", lower_bound, maximum + 1),
        )
        split_at = next((position for position in candidates if position > 0), maximum)
        part = remaining[:split_at].strip()
        if not part:
            split_at = maximum
            part = remaining[:split_at]
        parts.append(part)
        remaining = remaining[split_at:].strip()
    return tuple(parts)


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _append(chunks: list[GeneratedChunk], chunk: GeneratedChunk, limits: ChunkingLimits) -> None:
    if len(chunk.content) > limits.max_content_chars:
        raise ChunkingError(ChunkingErrorCode.RESULT_LIMIT_EXCEEDED)
    if len(chunks) >= limits.max_chunks:
        raise ChunkingError(ChunkingErrorCode.RESULT_LIMIT_EXCEEDED)
    chunks.append(chunk)


def _chunk_pdf(
    parsed: ParsedDocument, metadata: ChunkMetadata, limits: ChunkingLimits
) -> tuple[GeneratedChunk, ...]:
    if parsed.sheets or len(parsed.pages) > limits.max_pages:
        raise ChunkingError(ChunkingErrorCode.INVALID_SOURCE)
    chunks: list[GeneratedChunk] = []
    seen_pages: set[int] = set()
    for page in sorted(parsed.pages, key=lambda item: item.page_number):
        if page.page_number in seen_pages:
            raise ChunkingError(ChunkingErrorCode.INVALID_SOURCE)
        seen_pages.add(page.page_number)
        text = _normalize(page.text)
        for section in _pdf_sections(text):
            for content in _bounded_text(section, limits.max_content_chars):
                chunk = GeneratedChunk(
                    ordinal=len(chunks),
                    tenant_id=metadata.tenant_id,
                    company_id=metadata.company_id,
                    department=metadata.department,
                    visibility=metadata.visibility,
                    classification=metadata.classification,
                    document_id=metadata.document_id,
                    document_version_id=metadata.document_version_id,
                    document_version=metadata.document_version,
                    version_status=metadata.version_status,
                    active=metadata.active,
                    source_type=FileKind.PDF,
                    content=content,
                    content_hash=_hash_content(content),
                    page_number=page.page_number,
                )
                _append(chunks, chunk, limits)
    return tuple(chunks)


def _render_cell(cell: ParsedCell) -> str:
    value = json.dumps(cell.value_text, ensure_ascii=False, separators=(",", ":"))
    return f"{cell.coordinate}={value}"


def _row_units(row: ParsedRow, maximum: int) -> tuple[_SpreadsheetUnit, ...]:
    prefix = f"row {row.row_number}\t"
    cells = sorted(row.cells, key=lambda item: (item.column_number, item.coordinate))
    if len({cell.column_number for cell in cells}) != len(cells):
        raise ChunkingError(ChunkingErrorCode.INVALID_SOURCE)
    units: list[_SpreadsheetUnit] = []
    current: list[tuple[str, str]] = []

    def flush() -> None:
        if not current:
            return
        content = prefix + "\t".join(item[1] for item in current)
        units.append(
            _SpreadsheetUnit(
                row_number=row.row_number,
                cell_start=current[0][0],
                cell_end=current[-1][0],
                content=content,
            )
        )
        current.clear()

    for cell in cells:
        token = _render_cell(cell)
        proposed = prefix + "\t".join([*(item[1] for item in current), token])
        if len(proposed) <= maximum:
            current.append((cell.coordinate, token))
            continue
        flush()
        if len(prefix) + len(token) <= maximum:
            current.append((cell.coordinate, token))
            continue
        value_prefix = f"{prefix}{cell.coordinate}="
        available = maximum - len(value_prefix)
        if available < 1:
            raise ChunkingError(ChunkingErrorCode.RESULT_LIMIT_EXCEEDED)
        rendered_value = json.dumps(cell.value_text, ensure_ascii=False, separators=(",", ":"))
        for fragment in _bounded_text(rendered_value, available):
            units.append(
                _SpreadsheetUnit(
                    row_number=row.row_number,
                    cell_start=cell.coordinate,
                    cell_end=cell.coordinate,
                    content=f"{value_prefix}{fragment}",
                )
            )
    flush()
    return tuple(units)


def _group_units(
    units: Iterable[_SpreadsheetUnit], limits: ChunkingLimits
) -> Iterable[tuple[str, int, int, str, str]]:
    current: list[_SpreadsheetUnit] = []
    distinct_rows: set[int] = set()
    for unit in units:
        proposed_rows = {*distinct_rows, unit.row_number}
        proposed_content = "\n".join([*(item.content for item in current), unit.content])
        if current and (
            len(proposed_content) > limits.max_content_chars
            or len(proposed_rows) > limits.spreadsheet_rows_per_chunk
        ):
            yield (
                "\n".join(item.content for item in current),
                current[0].row_number,
                current[-1].row_number,
                current[0].cell_start,
                current[-1].cell_end,
            )
            current = []
            distinct_rows = set()
        current.append(unit)
        distinct_rows.add(unit.row_number)
    if current:
        yield (
            "\n".join(item.content for item in current),
            current[0].row_number,
            current[-1].row_number,
            current[0].cell_start,
            current[-1].cell_end,
        )


def _chunk_spreadsheet(
    parsed: ParsedDocument, metadata: ChunkMetadata, limits: ChunkingLimits
) -> tuple[GeneratedChunk, ...]:
    if parsed.pages or len(parsed.sheets) > limits.max_sheets:
        raise ChunkingError(ChunkingErrorCode.INVALID_SOURCE)
    chunks: list[GeneratedChunk] = []
    seen_sheets: set[tuple[int, str]] = set()
    row_count = 0
    cell_count = 0
    for sheet in sorted(parsed.sheets, key=lambda item: (item.sheet_index, item.name)):
        sheet_identity = (sheet.sheet_index, sheet.name)
        if sheet_identity in seen_sheets:
            raise ChunkingError(ChunkingErrorCode.INVALID_SOURCE)
        seen_sheets.add(sheet_identity)
        seen_rows: set[int] = set()
        sheet_units: list[_SpreadsheetUnit] = []
        for row in sorted(sheet.rows, key=lambda item: item.row_number):
            if row.row_number in seen_rows:
                raise ChunkingError(ChunkingErrorCode.INVALID_SOURCE)
            seen_rows.add(row.row_number)
            row_count += 1
            cell_count += len(row.cells)
            if row_count > limits.max_rows or cell_count > limits.max_cells:
                raise ChunkingError(ChunkingErrorCode.SOURCE_LIMIT_EXCEEDED)
            sheet_units.extend(_row_units(row, limits.max_content_chars))
        for content, row_start, row_end, cell_start, cell_end in _group_units(sheet_units, limits):
            chunk = GeneratedChunk(
                ordinal=len(chunks),
                tenant_id=metadata.tenant_id,
                company_id=metadata.company_id,
                department=metadata.department,
                visibility=metadata.visibility,
                classification=metadata.classification,
                document_id=metadata.document_id,
                document_version_id=metadata.document_version_id,
                document_version=metadata.document_version,
                version_status=metadata.version_status,
                active=metadata.active,
                source_type=parsed.kind,
                content=content,
                content_hash=_hash_content(content),
                sheet_name=sheet.name,
                row_start=row_start,
                row_end=row_end,
                cell_start=cell_start,
                cell_end=cell_end,
            )
            _append(chunks, chunk, limits)
    return tuple(chunks)


def chunk_document(
    parsed: ParsedDocument,
    metadata: ChunkMetadata,
    limits: ChunkingLimits = DEFAULT_LIMITS,
) -> tuple[GeneratedChunk, ...]:
    """Generate bounded, immutable chunks from already-validated parsed content."""

    if (
        metadata.version_status != "APPROVED"
        or not metadata.active
        or metadata.document_deleted
        or metadata.version_deleted
    ):
        raise ChunkingError(ChunkingErrorCode.INVALID_LIFECYCLE)
    actual_source_chars = sum(len(page.text) for page in parsed.pages) + sum(
        len(cell.value_text) for sheet in parsed.sheets for row in sheet.rows for cell in row.cells
    )
    if (
        parsed.text_length > limits.max_source_chars
        or actual_source_chars > limits.max_source_chars
    ):
        raise ChunkingError(ChunkingErrorCode.SOURCE_LIMIT_EXCEEDED)
    if parsed.kind is FileKind.PDF:
        chunks = _chunk_pdf(parsed, metadata, limits)
    elif parsed.kind in {FileKind.XLSX, FileKind.CSV}:
        chunks = _chunk_spreadsheet(parsed, metadata, limits)
    else:
        raise ChunkingError(ChunkingErrorCode.INVALID_SOURCE)
    if not chunks:
        raise ChunkingError(ChunkingErrorCode.INVALID_SOURCE)
    return chunks
