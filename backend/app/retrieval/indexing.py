from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking import ChunkMetadata, GeneratedChunk, chunk_document
from app.ingestion.contracts import (
    FileKind,
    ParsedDocument,
    ValueKind,
)
from app.ingestion.contracts import (
    ParsedCell as ParsedCellData,
)
from app.ingestion.contracts import (
    ParsedPage as ParsedPageData,
)
from app.ingestion.contracts import (
    ParsedRow as ParsedRowData,
)
from app.ingestion.contracts import (
    ParsedSheet as ParsedSheetData,
)
from app.models.documents import Document, DocumentChunk, DocumentVersion, IngestionStatus


def _source_kind(version: DocumentVersion) -> FileKind:
    media_types = {
        "application/pdf": FileKind.PDF,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": FileKind.XLSX,
        "text/csv": FileKind.CSV,
        "application/csv": FileKind.CSV,
    }
    try:
        return media_types[version.detected_media_type]
    except KeyError as exc:
        raise ValueError("Approved document has an unsupported source type.") from exc


def parsed_document_from_version(version: DocumentVersion) -> ParsedDocument:
    pages = tuple(
        ParsedPageData(page_number=page.page_number, text=page.text) for page in version.pages
    )
    sheets = tuple(
        ParsedSheetData(
            sheet_index=sheet.sheet_index,
            name=sheet.name,
            rows=tuple(
                ParsedRowData(
                    row_number=row.row_number,
                    cells=tuple(
                        ParsedCellData(
                            row_number=row.row_number,
                            column_number=cell.column_number,
                            coordinate=cell.coordinate,
                            value_text=cell.value_text,
                            value_kind=ValueKind(cell.value_kind),
                            formula_like=cell.formula_like,
                        )
                        for cell in row.cells
                    ),
                )
                for row in sheet.rows
            ),
        )
        for sheet in version.sheets
    )
    return ParsedDocument(
        kind=_source_kind(version),
        pages=pages,
        sheets=sheets,
        warnings=tuple(
            str(item.get("message", "Document contains a parsing warning."))
            for item in version.warnings
        ),
        page_count=version.page_count,
        sheet_count=version.sheet_count,
        row_count=version.row_count,
        cell_count=version.cell_count,
        text_length=sum(len(page.text) for page in version.pages)
        + sum(
            len(cell.value_text)
            for sheet in version.sheets
            for row in sheet.rows
            for cell in row.cells
        ),
    )


def generate_approved_chunks(
    document: Document, version: DocumentVersion
) -> tuple[GeneratedChunk, ...]:
    if (
        version.status != IngestionStatus.APPROVED.value
        or document.current_approved_version_id != version.id
        or document.deleted_at is not None
        or version.deleted_at is not None
    ):
        raise ValueError("Document version is not the current approved version.")
    return chunk_document(
        parsed_document_from_version(version),
        ChunkMetadata(
            tenant_id=document.tenant_id,
            company_id=document.company_id,
            department=document.department.key,
            visibility=document.visibility,
            classification=document.classification,
            document_id=document.id,
            document_version_id=version.id,
            document_version=version.version_number,
            version_status=version.status,
            active=True,
            document_deleted=document.deleted_at is not None,
            version_deleted=version.deleted_at is not None,
        ),
    )


async def replace_active_chunks(
    session: AsyncSession,
    document: Document,
    version: DocumentVersion,
    generated: tuple[GeneratedChunk, ...],
) -> int:
    """Deactivate old versions and install selected-version chunks in one transaction."""
    expected_metadata = (
        document.id,
        version.id,
        document.tenant_id,
        document.company_id,
        document.department.key,
        document.visibility,
        document.classification,
        version.version_number,
    )
    if (
        version.status != IngestionStatus.APPROVED.value
        or document.current_approved_version_id != version.id
        or document.deleted_at is not None
        or version.deleted_at is not None
        or any(
            (
                item.document_id,
                item.document_version_id,
                item.tenant_id,
                item.company_id,
                item.department,
                item.visibility,
                item.classification,
                item.document_version,
            )
            != expected_metadata
            or item.version_status != IngestionStatus.APPROVED.value
            or not item.active
            for item in generated
        )
    ):
        raise ValueError("Chunks do not match the current approved document version.")
    result = await session.execute(
        update(DocumentChunk).where(DocumentChunk.document_id == document.id).values(active=False)
    )
    session.add_all(
        DocumentChunk(
            document_id=item.document_id,
            document_version_id=item.document_version_id,
            tenant_id=item.tenant_id,
            company_id=item.company_id,
            department_id=document.department_id,
            department=item.department,
            visibility=item.visibility,
            classification=item.classification,
            version_number=item.document_version,
            version_status=item.version_status,
            active=item.active,
            document_deleted=False,
            version_deleted=False,
            ordinal=item.ordinal,
            source_type=item.source_type.value,
            page_number=item.page_number,
            sheet_name=item.sheet_name,
            row_start=item.row_start,
            row_end=item.row_end,
            cell_start=item.cell_start,
            cell_end=item.cell_end,
            content=item.content,
            content_hash=item.content_hash,
        )
        for item in generated
    )
    return int(cast(CursorResult[Any], result).rowcount or 0)


async def deactivate_version_chunks(
    session: AsyncSession,
    version_id: UUID,
    *,
    version_status: IngestionStatus,
) -> int:
    result = await session.execute(
        update(DocumentChunk)
        .where(DocumentChunk.document_version_id == version_id)
        .values(
            active=False,
            version_status=version_status.value,
            version_deleted=version_status == IngestionStatus.DELETED,
        )
    )
    return int(cast(CursorResult[Any], result).rowcount or 0)


async def deactivate_document_chunks(session: AsyncSession, document_id: UUID) -> int:
    result = await session.execute(
        update(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .values(
            active=False,
            version_status=IngestionStatus.DELETED.value,
            document_deleted=True,
            version_deleted=True,
        )
    )
    return int(cast(CursorResult[Any], result).rowcount or 0)
