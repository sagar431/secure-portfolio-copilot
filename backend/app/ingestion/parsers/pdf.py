import io
from collections.abc import Mapping, Sequence
from typing import Any, Never

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import DictionaryObject, IndirectObject

from app.ingestion.contracts import FileKind, ParsedDocument, ParsedPage, ValidatedFile
from app.ingestion.errors import FileParsingError, IngestionErrorCode
from app.ingestion.limits import IngestionLimits
from app.ingestion.parsers.base import normalize_text

ACTIVE_KEYS = frozenset(
    {
        "/AA",
        "/EmbeddedFile",
        "/EmbeddedFiles",
        "/ImportData",
        "/JavaScript",
        "/JS",
        "/Launch",
        "/OpenAction",
        "/RichMedia",
        "/SubmitForm",
    }
)
MAX_ACTIVE_SCAN_OBJECTS = 10_000


def _raise(code: IngestionErrorCode) -> Never:
    raise FileParsingError(code, "File parsing failed.")


def _contains_active_content(value: Any) -> bool:
    pending = [value]
    visited: set[tuple[int, int] | int] = set()
    scanned = 0
    while pending:
        current = pending.pop()
        if isinstance(current, IndirectObject):
            identity: tuple[int, int] | int = (current.idnum, current.generation)
            if identity in visited:
                continue
            visited.add(identity)
            try:
                current = current.get_object()
            except (PdfReadError, RecursionError, ValueError):
                _raise(IngestionErrorCode.MALFORMED_FILE)
        else:
            identity = id(current)
            if identity in visited:
                continue
            visited.add(identity)
        scanned += 1
        if scanned > MAX_ACTIVE_SCAN_OBJECTS:
            _raise(IngestionErrorCode.MALFORMED_FILE)
        if isinstance(current, Mapping):
            if any(str(key) in ACTIVE_KEYS for key in current):
                return True
            pending.extend(current.values())
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            pending.extend(current)
    return False


def parse_pdf(upload: ValidatedFile, limits: IngestionLimits) -> ParsedDocument:
    try:
        reader = PdfReader(
            io.BytesIO(upload.data),
            strict=True,
            root_object_recovery_limit=limits.pdf_root_recovery_objects,
        )
        if reader.is_encrypted:
            _raise(IngestionErrorCode.PDF_ENCRYPTED)
        if len(reader.pages) > limits.pdf_pages:
            _raise(IngestionErrorCode.PAGE_LIMIT_EXCEEDED)
        if _contains_active_content(reader.trailer.get("/Root", DictionaryObject())):
            _raise(IngestionErrorCode.PDF_ACTIVE_CONTENT)

        pages: list[ParsedPage] = []
        warnings: list[str] = []
        total_text = 0
        total_decoded = 0
        for page_number, page in enumerate(reader.pages, start=1):
            contents = page.get_contents()
            decoded_length = 0 if contents is None else len(contents.get_data())
            if decoded_length > limits.pdf_page_decoded_bytes:
                _raise(IngestionErrorCode.PAGE_LIMIT_EXCEEDED)
            total_decoded += decoded_length
            if total_decoded > limits.pdf_total_decoded_bytes:
                _raise(IngestionErrorCode.PAGE_LIMIT_EXCEEDED)
            text = normalize_text(page.extract_text() or "")
            if len(text) > limits.pdf_page_text_characters:
                _raise(IngestionErrorCode.TEXT_LIMIT_EXCEEDED)
            if not text:
                warnings.append("PDF_PAGE_EMPTY")
            total_text += len(text)
            if total_text > limits.total_text_characters:
                _raise(IngestionErrorCode.TEXT_LIMIT_EXCEEDED)
            pages.append(ParsedPage(page_number=page_number, text=text))
        if not pages or not any(page.text for page in pages):
            _raise(IngestionErrorCode.PDF_TEXT_REQUIRED)
        return ParsedDocument(
            kind=FileKind.PDF,
            pages=tuple(pages),
            warnings=tuple(sorted(set(warnings))),
            page_count=len(pages),
            sheet_count=0,
            row_count=0,
            cell_count=0,
            text_length=total_text,
        )
    except FileParsingError:
        raise
    except (PdfReadError, RecursionError, UnicodeError, ValueError, TypeError, KeyError, OSError):
        _raise(IngestionErrorCode.MALFORMED_FILE)
