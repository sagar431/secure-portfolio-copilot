from app.ingestion.contracts import FileKind, ParsedDocument, ValidatedFile
from app.ingestion.errors import FileParsingError, IngestionErrorCode
from app.ingestion.limits import DEFAULT_LIMITS, IngestionLimits
from app.ingestion.parsers.pdf import parse_pdf
from app.ingestion.parsers.spreadsheet import parse_csv, parse_xlsx


def parse_validated_file(
    upload: ValidatedFile, limits: IngestionLimits = DEFAULT_LIMITS
) -> ParsedDocument:
    if upload.kind == FileKind.PDF:
        return parse_pdf(upload, limits)
    if upload.kind == FileKind.XLSX:
        return parse_xlsx(upload, limits)
    if upload.kind == FileKind.CSV:
        return parse_csv(upload, limits)
    raise FileParsingError(IngestionErrorCode.UNSUPPORTED_FILE_TYPE, "File parsing failed.")


__all__ = ["parse_csv", "parse_pdf", "parse_validated_file", "parse_xlsx"]
