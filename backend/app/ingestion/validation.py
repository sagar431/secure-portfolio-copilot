import csv
import hashlib
import io
import re
import stat
import unicodedata
import zipfile
from pathlib import PurePosixPath
from typing import Never

from defusedxml.ElementTree import ParseError, fromstring

from app.ingestion.contracts import FileKind, ValidatedFile, ValidationInput
from app.ingestion.errors import FileValidationError, IngestionErrorCode
from app.ingestion.limits import DEFAULT_LIMITS, IngestionLimits

PDF_MIME = "application/pdf"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIMES = frozenset({"text/csv", "application/csv"})
OOXML_WORKBOOK_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
)
OLE_COMPOUND_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
ALLOWED_ZIP_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
REQUIRED_XLSX_MEMBERS = frozenset({"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml"})
FORBIDDEN_XLSX_NAME_MARKERS = (
    "vbaproject",
    "macrosheet",
    "activex",
    "embeddings/",
    "externallinks/",
    "connections.xml",
)
FORBIDDEN_XLSX_CONTENT_MARKERS = (
    b"macroenabled",
    b"vbaproject",
    b"activex",
    b"oleobject",
)
_SAFE_FILENAME_CHARACTER = re.compile(r"[^A-Za-z0-9._ -]+")


def _fail(code: IngestionErrorCode, message: str = "File validation failed.") -> Never:
    raise FileValidationError(code, message)


def sanitize_filename(filename: str, *, max_length: int = 128) -> str:
    normalized = unicodedata.normalize("NFKC", filename)
    if not normalized or "\x00" in normalized:
        _fail(IngestionErrorCode.UNSUPPORTED_FILE_TYPE)
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in normalized):
        _fail(IngestionErrorCode.UNSUPPORTED_FILE_TYPE)
    basename = normalized.replace("\\", "/").rsplit("/", 1)[-1].strip(" .")
    basename = _SAFE_FILENAME_CHARACTER.sub("_", basename)
    basename = re.sub(r"[ _.-]{2,}", lambda match: match.group(0)[0], basename)
    if not basename or basename in {".", ".."}:
        _fail(IngestionErrorCode.UNSUPPORTED_FILE_TYPE)
    if len(basename) > max_length:
        suffix = PurePosixPath(basename).suffix[:16]
        basename = f"{basename[: max_length - len(suffix)]}{suffix}"
    return basename


def _classify(filename: str, declared_content_type: str) -> tuple[FileKind, str]:
    suffix = PurePosixPath(filename.lower()).suffix
    content_type = declared_content_type.split(";", 1)[0].strip().lower()
    if suffix == ".pdf":
        if content_type != PDF_MIME:
            _fail(IngestionErrorCode.CONTENT_TYPE_MISMATCH)
        return FileKind.PDF, PDF_MIME
    if suffix == ".xlsx":
        if content_type != XLSX_MIME:
            _fail(IngestionErrorCode.CONTENT_TYPE_MISMATCH)
        return FileKind.XLSX, XLSX_MIME
    if suffix == ".csv":
        if content_type not in CSV_MIMES:
            _fail(IngestionErrorCode.CONTENT_TYPE_MISMATCH)
        return FileKind.CSV, "text/csv"
    _fail(IngestionErrorCode.UNSUPPORTED_FILE_TYPE)


def _validate_pdf_signature(data: bytes) -> None:
    if not data.startswith(b"%PDF-") or not re.match(rb"%PDF-[12]\.[0-9]", data[:8]):
        _fail(IngestionErrorCode.INVALID_FILE_SIGNATURE)
    if b"%%EOF" not in data[-2048:]:
        _fail(IngestionErrorCode.MALFORMED_FILE)


def _safe_zip_name(name: str) -> bool:
    if not name or "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK


def _validate_xlsx_package(data: bytes, limits: IngestionLimits) -> None:
    if data.startswith(OLE_COMPOUND_SIGNATURE):
        _fail(IngestionErrorCode.XLSX_ENCRYPTED)
    if not data.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(io.BytesIO(data)):
        _fail(IngestionErrorCode.INVALID_FILE_SIGNATURE)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if not members or len(members) > limits.xlsx_zip_members:
                _fail(IngestionErrorCode.ZIP_LIMIT_EXCEEDED)
            names = [item.filename for item in members]
            if len(names) != len(set(names)) or any(not _safe_zip_name(name) for name in names):
                _fail(IngestionErrorCode.MALFORMED_FILE)
            normalized_names = {name.lower() for name in names}
            if not REQUIRED_XLSX_MEMBERS.issubset(set(names)):
                _fail(IngestionErrorCode.MALFORMED_FILE)
            if any(
                marker in name
                for name in normalized_names
                for marker in FORBIDDEN_XLSX_NAME_MARKERS
            ):
                marker_code = (
                    IngestionErrorCode.XLSX_EXTERNAL_LINK_FORBIDDEN
                    if any("externallinks/" in name for name in normalized_names)
                    else IngestionErrorCode.XLSX_MACRO_FORBIDDEN
                )
                _fail(marker_code)

            expanded = 0
            compressed = 0
            for member in members:
                if (
                    member.flag_bits & 0x1
                    or _is_zip_symlink(member)
                    or member.compress_type not in ALLOWED_ZIP_COMPRESSION
                ):
                    _fail(IngestionErrorCode.MALFORMED_FILE)
                if member.file_size > limits.xlsx_largest_member_bytes:
                    _fail(IngestionErrorCode.ZIP_LIMIT_EXCEEDED)
                expanded += member.file_size
                compressed += member.compress_size
                if (
                    member.file_size > 0
                    and member.file_size
                    > max(member.compress_size, 1) * limits.xlsx_expansion_ratio
                ):
                    _fail(IngestionErrorCode.ZIP_LIMIT_EXCEEDED)
            if (
                expanded > limits.xlsx_total_expanded_bytes
                or expanded > max(compressed, 1) * limits.xlsx_expansion_ratio
            ):
                _fail(IngestionErrorCode.ZIP_LIMIT_EXCEEDED)

            content_types = archive.read("[Content_Types].xml")
            lowered_types = content_types.lower()
            if OOXML_WORKBOOK_CONTENT_TYPE.encode() not in content_types:
                _fail(IngestionErrorCode.MALFORMED_FILE)
            if any(marker in lowered_types for marker in FORBIDDEN_XLSX_CONTENT_MARKERS):
                _fail(IngestionErrorCode.XLSX_MACRO_FORBIDDEN)
            try:
                fromstring(
                    content_types, forbid_dtd=True, forbid_entities=True, forbid_external=True
                )
            except (ParseError, ValueError):
                _fail(IngestionErrorCode.MALFORMED_FILE)

            for name in names:
                if not name.lower().endswith(".rels"):
                    continue
                relationship_bytes = archive.read(name)
                try:
                    relationships = fromstring(
                        relationship_bytes,
                        forbid_dtd=True,
                        forbid_entities=True,
                        forbid_external=True,
                    )
                except (ParseError, ValueError):
                    _fail(IngestionErrorCode.MALFORMED_FILE)
                if any(
                    element.attrib.get("TargetMode", "").lower() == "external"
                    for element in relationships.iter()
                ):
                    _fail(IngestionErrorCode.XLSX_EXTERNAL_LINK_FORBIDDEN)
            if archive.testzip() is not None:
                _fail(IngestionErrorCode.MALFORMED_FILE)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, KeyError, OSError):
        _fail(IngestionErrorCode.MALFORMED_FILE)


def _validate_csv(data: bytes, limits: IngestionLimits) -> None:
    if b"\x00" in data:
        _fail(IngestionErrorCode.MALFORMED_FILE)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        _fail(IngestionErrorCode.MALFORMED_FILE)
    previous_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(limits.spreadsheet_cell_characters)
        reader = csv.reader(io.StringIO(text, newline=""), dialect="excel", strict=True)
        row_count = 0
        cell_count = 0
        expected_columns: int | None = None
        for row in reader:
            row_count += 1
            if row_count > limits.spreadsheet_rows_per_sheet:
                _fail(IngestionErrorCode.ROW_LIMIT_EXCEEDED)
            if len(row) > limits.spreadsheet_columns_per_row:
                _fail(IngestionErrorCode.COLUMN_LIMIT_EXCEEDED)
            if expected_columns is None:
                expected_columns = len(row)
            elif len(row) != expected_columns:
                _fail(IngestionErrorCode.MALFORMED_FILE)
            cell_count += len(row)
            if cell_count > limits.spreadsheet_total_cells:
                _fail(IngestionErrorCode.CELL_LIMIT_EXCEEDED)
        if row_count == 0 or expected_columns in {None, 0}:
            _fail(IngestionErrorCode.MALFORMED_FILE)
        if len(text) > limits.total_text_characters:
            _fail(IngestionErrorCode.TEXT_LIMIT_EXCEEDED)
    except (csv.Error, UnicodeError):
        _fail(IngestionErrorCode.MALFORMED_FILE)
    finally:
        csv.field_size_limit(previous_limit)


def validate_file(
    upload: ValidationInput, limits: IngestionLimits = DEFAULT_LIMITS
) -> ValidatedFile:
    if not upload.data:
        _fail(IngestionErrorCode.MALFORMED_FILE)
    if len(upload.data) > limits.upload_bytes:
        _fail(IngestionErrorCode.FILE_TOO_LARGE)
    filename = sanitize_filename(upload.filename)
    kind, detected_content_type = _classify(filename, upload.declared_content_type)
    if kind == FileKind.PDF:
        _validate_pdf_signature(upload.data)
    elif kind == FileKind.XLSX:
        _validate_xlsx_package(upload.data, limits)
    else:
        _validate_csv(upload.data, limits)
    return ValidatedFile(
        kind=kind,
        sanitized_filename=filename,
        declared_content_type=upload.declared_content_type.split(";", 1)[0].strip().lower(),
        detected_content_type=detected_content_type,
        size_bytes=len(upload.data),
        sha256=hashlib.sha256(upload.data).hexdigest(),
        data=upload.data,
    )
