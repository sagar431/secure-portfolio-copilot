from enum import StrEnum


class IngestionErrorCode(StrEnum):
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    CONTENT_TYPE_MISMATCH = "CONTENT_TYPE_MISMATCH"
    INVALID_FILE_SIGNATURE = "INVALID_FILE_SIGNATURE"
    MALFORMED_FILE = "MALFORMED_FILE"
    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    PDF_ACTIVE_CONTENT = "PDF_ACTIVE_CONTENT"
    PDF_TEXT_REQUIRED = "PDF_TEXT_REQUIRED"
    XLSX_MACRO_FORBIDDEN = "XLSX_MACRO_FORBIDDEN"
    XLSX_EXTERNAL_LINK_FORBIDDEN = "XLSX_EXTERNAL_LINK_FORBIDDEN"
    XLSX_ENCRYPTED = "XLSX_ENCRYPTED"
    ZIP_LIMIT_EXCEEDED = "ZIP_LIMIT_EXCEEDED"
    PAGE_LIMIT_EXCEEDED = "PAGE_LIMIT_EXCEEDED"
    SHEET_LIMIT_EXCEEDED = "SHEET_LIMIT_EXCEEDED"
    ROW_LIMIT_EXCEEDED = "ROW_LIMIT_EXCEEDED"
    COLUMN_LIMIT_EXCEEDED = "COLUMN_LIMIT_EXCEEDED"
    CELL_LIMIT_EXCEEDED = "CELL_LIMIT_EXCEEDED"
    TEXT_LIMIT_EXCEEDED = "TEXT_LIMIT_EXCEEDED"
    PARSER_TIMEOUT = "PARSER_TIMEOUT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    STORAGE_KEY_INVALID = "STORAGE_KEY_INVALID"
    STORAGE_CONFLICT = "STORAGE_CONFLICT"


class IngestionError(Exception):
    """Expected ingestion failure containing only a stable code and safe message."""

    def __init__(self, code: IngestionErrorCode, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class FileValidationError(IngestionError):
    pass


class FileParsingError(IngestionError):
    pass


class ObjectStorageError(IngestionError):
    pass
