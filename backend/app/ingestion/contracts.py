from enum import StrEnum
from pathlib import PurePosixPath
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FrozenStrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class FileKind(StrEnum):
    PDF = "pdf"
    XLSX = "xlsx"
    CSV = "csv"


class ValueKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    FORMULA = "formula"
    ERROR = "error"


class ValidationInput(FrozenStrictModel):
    filename: str = Field(min_length=1, max_length=1024)
    declared_content_type: str = Field(min_length=1, max_length=255)
    data: bytes


class ValidatedFile(FrozenStrictModel):
    kind: FileKind
    sanitized_filename: str
    declared_content_type: str
    detected_content_type: str
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    data: bytes


class ParsedPage(FrozenStrictModel):
    page_number: int = Field(ge=1)
    text: str


class ParsedCell(FrozenStrictModel):
    row_number: int = Field(ge=1)
    column_number: int = Field(ge=1)
    coordinate: str
    value_text: str
    value_kind: ValueKind
    formula_like: bool = False


class ParsedRow(FrozenStrictModel):
    row_number: int = Field(ge=1)
    cells: tuple[ParsedCell, ...]


class ParsedSheet(FrozenStrictModel):
    sheet_index: int = Field(ge=1)
    name: str
    rows: tuple[ParsedRow, ...]


class ParsedDocument(FrozenStrictModel):
    kind: FileKind
    pages: tuple[ParsedPage, ...] = ()
    sheets: tuple[ParsedSheet, ...] = ()
    warnings: tuple[str, ...] = ()
    page_count: int = Field(ge=0)
    sheet_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    cell_count: int = Field(ge=0)
    text_length: int = Field(ge=0)


class StorageKey(FrozenStrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        path = PurePosixPath(value)
        parts = path.parts
        if len(parts) != 4 or parts[-1] != "source":
            raise ValueError("Storage key has an invalid shape")
        if path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("Storage key is not confined")
        for part in parts[:3]:
            try:
                UUID(part)
            except ValueError as exc:
                raise ValueError("Storage key contains an invalid identifier") from exc
        return value

    @classmethod
    def generate(cls, tenant_id: UUID, document_id: UUID, version_id: UUID) -> "StorageKey":
        return cls(value=f"{tenant_id}/{document_id}/{version_id}/source")


class StoredObject(FrozenStrictModel):
    key: StorageKey
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


# Compatibility names for service-layer terminology.
UploadDescriptor = ValidationInput
ValidatedUpload = ValidatedFile
