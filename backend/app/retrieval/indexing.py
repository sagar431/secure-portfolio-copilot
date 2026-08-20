import asyncio
import math
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking import ChunkMetadata, GeneratedChunk, chunk_document
from app.embeddings.contracts import EmbeddingModel, EmbeddingProvider, EmbeddingProviderError
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


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    chunk: GeneratedChunk
    embedding: tuple[float, ...]


async def embed_generated_chunks(
    provider: EmbeddingProvider,
    generated: tuple[GeneratedChunk, ...],
    *,
    batch_size: int,
    max_chunks: int,
    timeout_seconds: float,
) -> tuple[EmbeddedChunk, ...]:
    if not 1 <= batch_size <= 64:
        raise ValueError("Embedding batch size is invalid.")
    if len(generated) > max_chunks:
        raise EmbeddingProviderError("CHUNK_LIMIT_EXCEEDED")
    try:
        async with asyncio.timeout(timeout_seconds):
            await provider.ensure_ready()
            model = provider.model
            if model.dimensions != 768:
                raise EmbeddingProviderError("DIMENSION_MISMATCH")
            embedded: list[EmbeddedChunk] = []
            for start in range(0, len(generated), batch_size):
                batch = generated[start : start + batch_size]
                vectors = await provider.embed(tuple(item.content for item in batch))
                if len(vectors) != len(batch):
                    raise EmbeddingProviderError("INVALID_PROVIDER_RESPONSE")
                for chunk, vector in zip(batch, vectors, strict=True):
                    if len(vector) != model.dimensions:
                        raise EmbeddingProviderError("DIMENSION_MISMATCH")
                    if (
                        not all(math.isfinite(value) for value in vector)
                        or math.sqrt(sum(value * value for value in vector)) == 0
                    ):
                        raise EmbeddingProviderError("INVALID_VECTOR")
                    embedded.append(EmbeddedChunk(chunk=chunk, embedding=vector))
            return tuple(embedded)
    except TimeoutError:
        raise EmbeddingProviderError("OPERATION_TIMEOUT", transient=True) from None


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
    generated: tuple[EmbeddedChunk, ...],
    model: EmbeddingModel,
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
                item.chunk.document_id,
                item.chunk.document_version_id,
                item.chunk.tenant_id,
                item.chunk.company_id,
                item.chunk.department,
                item.chunk.visibility,
                item.chunk.classification,
                item.chunk.document_version,
            )
            != expected_metadata
            or item.chunk.version_status != IngestionStatus.APPROVED.value
            or not item.chunk.active
            for item in generated
        )
    ):
        raise ValueError("Chunks do not match the current approved document version.")
    result = await session.execute(
        update(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .values(
            active=False,
            embedding=None,
            embedding_model_name=None,
            embedding_model_version=None,
            embedding_dimensions=None,
            embedding_chunk_hash=None,
            embedding_status="STALE",
        )
    )
    session.add_all(
        DocumentChunk(
            document_id=item.chunk.document_id,
            document_version_id=item.chunk.document_version_id,
            tenant_id=item.chunk.tenant_id,
            company_id=item.chunk.company_id,
            department_id=document.department_id,
            department=item.chunk.department,
            visibility=item.chunk.visibility,
            classification=item.chunk.classification,
            version_number=item.chunk.document_version,
            version_status=item.chunk.version_status,
            active=item.chunk.active,
            document_deleted=False,
            version_deleted=False,
            ordinal=item.chunk.ordinal,
            source_type=item.chunk.source_type.value,
            page_number=item.chunk.page_number,
            sheet_name=item.chunk.sheet_name,
            row_start=item.chunk.row_start,
            row_end=item.chunk.row_end,
            cell_start=item.chunk.cell_start,
            cell_end=item.chunk.cell_end,
            content=item.chunk.content,
            content_hash=item.chunk.content_hash,
            embedding=list(item.embedding),
            embedding_model_name=model.name,
            embedding_model_version=model.version,
            embedding_dimensions=model.dimensions,
            embedding_chunk_hash=item.chunk.content_hash,
            embedding_status="READY",
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
            embedding=None,
            embedding_model_name=None,
            embedding_model_version=None,
            embedding_dimensions=None,
            embedding_chunk_hash=None,
            embedding_status="STALE",
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
            embedding=None,
            embedding_model_name=None,
            embedding_model_version=None,
            embedding_dimensions=None,
            embedding_chunk_hash=None,
            embedding_status="STALE",
        )
    )
    return int(cast(CursorResult[Any], result).rowcount or 0)
