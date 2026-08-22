from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calculations.contracts import (
    CalculationCitation,
    CalculationMetric,
    CalculationResult,
    TrustedCalculationInput,
)
from app.calculations.engine import (
    CalculationError,
    CalculationErrorCode,
    calculate,
    required_inputs,
)
from app.models.documents import (
    DocumentChunk,
    DocumentVersion,
    ParsedCell,
    ParsedRow,
    ParsedSheet,
)
from app.models.identity import Capability, Company, CompanyStatus
from app.policies.models import AuthorizationScope
from app.retrieval.repository import authorized_chunks_statement


class CalculationAuthorizationError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class _Cell:
    row_number: int
    column_number: int
    coordinate: str
    value_text: str
    value_kind: str
    formula_like: bool


@dataclass(frozen=True, slots=True)
class _Chunk:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    version_number: int
    document_title: str
    content: str
    row_start: int
    row_end: int


def _authorized_finance_company_id(scope: AuthorizationScope, company_selector: str) -> UUID:
    direct_matches: list[UUID] = []
    workspace_alias_matches: list[UUID] = []
    for grant in scope.grants:
        departments = {item.key for item in grant.departments}
        if Capability.QUERY_DOCUMENTS not in grant.capabilities or "finance" not in departments:
            continue
        company_pairs = tuple(zip(grant.company_ids, grant.company_slugs, strict=True))
        direct_matches.extend(
            company_id
            for company_id, company_slug in company_pairs
            if company_slug == company_selector
        )
        if company_selector in {grant.home_tenant_slug, grant.workspace_slug}:
            grant_company_ids = tuple(dict.fromkeys(grant.company_ids))
            if len(grant_company_ids) == 1:
                workspace_alias_matches.extend(grant_company_ids)

    matches = tuple(dict.fromkeys(direct_matches or workspace_alias_matches))
    if len(matches) != 1:
        raise CalculationAuthorizationError
    return matches[0]


def _trusted_input(
    *,
    name: str,
    period: str,
    rows: dict[int, dict[int, _Cell]],
    metric_rows: dict[str, int],
    period_columns: dict[str, int],
    unit_column: int,
    chunk: _Chunk,
) -> TrustedCalculationInput:
    row_number = metric_rows.get(name)
    column_number = period_columns.get(period)
    if row_number is None or column_number is None:
        raise CalculationError(CalculationErrorCode.INPUTS_MISSING)
    row = rows[row_number]
    value_cell = row.get(column_number)
    name_cell = row.get(1)
    unit_cell = row.get(unit_column)
    if value_cell is None or name_cell is None or unit_cell is None:
        raise CalculationError(CalculationErrorCode.INPUTS_MISSING)
    if (
        value_cell.value_kind != "number"
        or value_cell.formula_like
        or unit_cell.value_text != "INR crore"
    ):
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    try:
        numeric = Decimal(value_cell.value_text)
    except InvalidOperation:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID) from None
    if not numeric.is_finite() or abs(numeric) > Decimal("1000000000000"):
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    return TrustedCalculationInput(
        name=name,
        period=period,
        value=float(numeric),
        citation=CalculationCitation(
            document_id=chunk.document_id,
            document_version_id=chunk.document_version_id,
            chunk_id=chunk.chunk_id,
            document_title=chunk.document_title,
            version_number=chunk.version_number,
            excerpt=chunk.content[:500],
            row_start=row_number,
            row_end=row_number,
            cell_start=value_cell.coordinate,
            cell_end=value_cell.coordinate,
        ),
    )


async def calculate_authorized_metric(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    metric: CalculationMetric,
    company_slug: str,
    period: str,
) -> CalculationResult:
    authorized_company_id = _authorized_finance_company_id(scope, company_slug)
    company_rows = tuple(
        (
            await session.execute(
                select(Company.id, Company.slug).where(
                    Company.id == authorized_company_id,
                    Company.status == CompanyStatus.ACTIVE,
                )
            )
        ).all()
    )
    if len(company_rows) != 1:
        raise CalculationAuthorizationError
    canonical_company_id, canonical_company_slug = company_rows[0]
    authorized_chunks = (
        authorized_chunks_statement(scope)
        .where(
            DocumentChunk.company_id == canonical_company_id,
            DocumentChunk.department == "finance",
            DocumentChunk.source_type == "xlsx",
            DocumentChunk.sheet_name == "P&L",
        )
        .with_only_columns(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id,
            DocumentChunk.document_version_id,
            DocumentChunk.version_number,
            DocumentVersion.safe_filename.label("document_title"),
            DocumentChunk.content,
            DocumentChunk.row_start,
            DocumentChunk.row_end,
        )
        .cte("authorized_calculation_chunks")
        .prefix_with("MATERIALIZED")
    )
    chunk_rows = (await session.execute(select(authorized_chunks))).all()
    if not chunk_rows:
        raise CalculationError(CalculationErrorCode.INPUTS_MISSING)
    chunks_by_version: dict[UUID, list[_Chunk]] = defaultdict(list)
    for row in chunk_rows:
        if row.row_start is None or row.row_end is None:
            raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
        chunks_by_version[row.document_version_id].append(
            _Chunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                document_version_id=row.document_version_id,
                version_number=row.version_number,
                document_title=row.document_title,
                content=row.content,
                row_start=row.row_start,
                row_end=row.row_end,
            )
        )
    version_ids = tuple(chunks_by_version)
    cell_rows = (
        await session.execute(
            select(
                ParsedSheet.document_version_id,
                ParsedRow.row_number,
                ParsedCell.column_number,
                ParsedCell.coordinate,
                ParsedCell.value_text,
                ParsedCell.value_kind,
                ParsedCell.formula_like,
            )
            .join(ParsedRow, ParsedRow.sheet_id == ParsedSheet.id)
            .join(ParsedCell, ParsedCell.row_id == ParsedRow.id)
            .where(
                ParsedSheet.document_version_id.in_(version_ids),
                ParsedSheet.name == "P&L",
            )
            .order_by(
                ParsedSheet.document_version_id,
                ParsedRow.row_number,
                ParsedCell.column_number,
            )
        )
    ).all()
    cells_by_version: dict[UUID, dict[int, dict[int, _Cell]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for row in cell_rows:
        cells_by_version[row.document_version_id][row.row_number][row.column_number] = _Cell(
            row_number=row.row_number,
            column_number=row.column_number,
            coordinate=row.coordinate,
            value_text=row.value_text,
            value_kind=row.value_kind,
            formula_like=row.formula_like,
        )

    results: list[CalculationResult] = []
    failures: list[CalculationErrorCode] = []
    for version_id, rows in cells_by_version.items():
        try:
            header_candidates = [
                row_number
                for row_number, cells in rows.items()
                if cells.get(1) is not None and cells[1].value_text == "Metric"
            ]
            if len(header_candidates) != 1:
                raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
            header = rows[header_candidates[0]]
            period_columns = {
                cell.value_text: cell.column_number
                for cell in header.values()
                if cell.value_text.startswith("FY")
            }
            unit_columns = [
                cell.column_number for cell in header.values() if cell.value_text == "Unit"
            ]
            if len(unit_columns) != 1:
                raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
            metric_rows: dict[str, int] = {}
            for row_number, cells in rows.items():
                label = cells.get(1)
                if label is None or row_number == header_candidates[0]:
                    continue
                if label.value_text in metric_rows:
                    raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
                metric_rows[label.value_text] = row_number
            trusted: list[TrustedCalculationInput] = []
            for name, input_period in required_inputs(metric, period):
                input_row_number = metric_rows.get(name)
                if input_row_number is None:
                    raise CalculationError(CalculationErrorCode.INPUTS_MISSING)
                matching_chunks = [
                    item
                    for item in chunks_by_version[version_id]
                    if item.row_start <= input_row_number <= item.row_end
                ]
                if len(matching_chunks) != 1:
                    raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
                trusted.append(
                    _trusted_input(
                        name=name,
                        period=input_period,
                        rows=rows,
                        metric_rows=metric_rows,
                        period_columns=period_columns,
                        unit_column=unit_columns[0],
                        chunk=matching_chunks[0],
                    )
                )
            results.append(
                calculate(
                    metric,
                    company_slug=canonical_company_slug,
                    period=period,
                    document_version_id=str(version_id),
                    inputs=tuple(trusted),
                )
            )
        except CalculationError as exc:
            failures.append(exc.code)
    if len(results) == 1:
        return results[0]
    if len(results) > 1:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    if CalculationErrorCode.DIVISION_BY_ZERO in failures:
        raise CalculationError(CalculationErrorCode.DIVISION_BY_ZERO)
    if CalculationErrorCode.INPUTS_INVALID in failures:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    raise CalculationError(CalculationErrorCode.INPUTS_MISSING)
