from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal
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
    calculate_cagr,
    derived_profit_metric_result,
    direct_metric_result,
    previous_period,
)
from app.mcp_gateway.contracts import FinancialMetricName
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
    sheet_name: str
    content: str
    row_start: int
    row_end: int


@dataclass(frozen=True, slots=True)
class _InputSpec:
    sheet_name: str
    name: str
    period: str
    unit: Literal["INR crore", "INR crore/month"] = "INR crore"


_DIRECT_METRICS: dict[FinancialMetricName, tuple[str, str]] = {
    FinancialMetricName.REVENUE: ("P&L", "Revenue"),
    FinancialMetricName.EBITDA: ("P&L", "EBITDA"),
    FinancialMetricName.NET_PROFIT: ("P&L", "Net Profit"),
    FinancialMetricName.CLOSING_CASH: ("Balance Sheet", "Cash and Cash Equivalents"),
    FinancialMetricName.BANK_DEBT: ("Balance Sheet", "Bank Debt"),
}


def _authorized_finance_company_id(scope: AuthorizationScope, selector: str) -> UUID:
    direct: list[UUID] = []
    aliases: list[UUID] = []
    for grant in scope.grants:
        if Capability.QUERY_DOCUMENTS not in grant.capabilities or "finance" not in {
            item.key for item in grant.departments
        }:
            continue
        direct.extend(
            company_id
            for company_id, slug in zip(grant.company_ids, grant.company_slugs, strict=True)
            if slug == selector
        )
        if selector in {grant.home_tenant_slug, grant.workspace_slug}:
            ids = tuple(dict.fromkeys(grant.company_ids))
            if len(ids) == 1:
                aliases.extend(ids)
    matches = tuple(dict.fromkeys(direct or aliases))
    if len(matches) != 1:
        raise CalculationAuthorizationError
    return matches[0]


def _specs(metric: CalculationMetric, period: str) -> tuple[_InputSpec, ...]:
    names: tuple[str, ...]
    if metric is CalculationMetric.EBITDA_MARGIN:
        names = (
            "Revenue",
            "Cost of Goods Sold",
            "Operating Expenses (excl. D&A)",
        )
        return tuple(_InputSpec("P&L", name, period) for name in names)
    if metric in {CalculationMetric.REVENUE_GROWTH, CalculationMetric.CAGR}:
        return (
            _InputSpec("P&L", "Revenue", previous_period(period)),
            _InputSpec("P&L", "Revenue", period),
        )
    if metric is CalculationMetric.NET_PROFIT_MARGIN:
        names = (
            "Revenue",
            "Cost of Goods Sold",
            "Operating Expenses (excl. D&A)",
            "Depreciation & Amortization",
            "Interest Expense",
            "Tax Expense",
        )
        return tuple(_InputSpec("P&L", name, period) for name in names)
    if metric is CalculationMetric.DEBT_TO_EQUITY:
        names = (
            "Cash and Cash Equivalents",
            "Accounts Receivable",
            "Inventory / Prepaid Assets",
            "Property, Plant & Equipment",
            "Bank Debt",
            "Accounts Payable",
            "Other Liabilities",
        )
        return tuple(_InputSpec("Balance Sheet", name, period) for name in names)
    if metric is CalculationMetric.CASH_RUNWAY:
        names = (
            "Opening Cash",
            "Operating Cash Flow",
            "Capital Expenditure",
            "Financing Cash Flow",
            "Stress-case Monthly Burn",
        )
        return tuple(
            _InputSpec(
                "Cash Flow",
                name,
                period,
                "INR crore/month" if name == "Stress-case Monthly Burn" else "INR crore",
            )
            for name in names
        )
    raise CalculationError(CalculationErrorCode.INPUTS_INVALID)


async def _load_inputs(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    company_slug: str,
    specs: tuple[_InputSpec, ...],
) -> tuple[str, UUID, tuple[TrustedCalculationInput, ...]]:
    company_id = _authorized_finance_company_id(scope, company_slug)
    companies = tuple(
        (
            await session.execute(
                select(Company.id, Company.slug).where(
                    Company.id == company_id, Company.status == CompanyStatus.ACTIVE
                )
            )
        ).all()
    )
    if len(companies) != 1:
        raise CalculationAuthorizationError
    canonical_company_id, canonical_slug = companies[0]
    sheets = tuple(dict.fromkeys(spec.sheet_name for spec in specs))
    authorized_chunks = (
        authorized_chunks_statement(scope)
        .where(
            DocumentChunk.company_id == canonical_company_id,
            DocumentChunk.department == "finance",
            DocumentChunk.source_type == "xlsx",
            DocumentChunk.sheet_name.in_(sheets),
        )
        .with_only_columns(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id,
            DocumentChunk.document_version_id,
            DocumentChunk.version_number,
            DocumentVersion.safe_filename.label("document_title"),
            DocumentChunk.sheet_name,
            DocumentChunk.content,
            DocumentChunk.row_start,
            DocumentChunk.row_end,
        )
        .cte("authorized_calculation_chunks")
        .prefix_with("MATERIALIZED")
    )
    chunks: dict[UUID, list[_Chunk]] = defaultdict(list)
    for row in (await session.execute(select(authorized_chunks))).all():
        if row.row_start is None or row.row_end is None or row.sheet_name is None:
            raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
        chunks[row.document_version_id].append(
            _Chunk(
                row.chunk_id,
                row.document_id,
                row.document_version_id,
                row.version_number,
                row.document_title,
                row.sheet_name,
                row.content,
                row.row_start,
                row.row_end,
            )
        )
    if not chunks:
        raise CalculationError(CalculationErrorCode.INPUTS_MISSING)
    rows = (
        await session.execute(
            select(
                ParsedSheet.document_version_id,
                ParsedSheet.name,
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
                ParsedSheet.document_version_id.in_(tuple(chunks)),
                ParsedSheet.name.in_(sheets),
            )
        )
    ).all()
    cells: dict[UUID, dict[str, dict[int, dict[int, _Cell]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict))
    )
    for row in rows:
        cells[row.document_version_id][row.name][row.row_number][row.column_number] = _Cell(
            row.coordinate, row.value_text, row.value_kind, row.formula_like
        )
    successes: list[tuple[UUID, tuple[TrustedCalculationInput, ...]]] = []
    invalid = False
    for version_id, version_chunks in chunks.items():
        try:
            trusted = tuple(
                _trusted_input(spec, cells[version_id], version_chunks) for spec in specs
            )
            successes.append((version_id, trusted))
        except CalculationError as exc:
            invalid = invalid or exc.code is CalculationErrorCode.INPUTS_INVALID
    if len(successes) == 1:
        version_id, trusted = successes[0]
        return canonical_slug, version_id, trusted
    if len(successes) > 1 or invalid:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    raise CalculationError(CalculationErrorCode.INPUTS_MISSING)


def _trusted_input(
    spec: _InputSpec,
    version_cells: dict[str, dict[int, dict[int, _Cell]]],
    chunks: list[_Chunk],
) -> TrustedCalculationInput:
    rows = version_cells.get(spec.sheet_name, {})
    header_rows = [
        number
        for number, row in rows.items()
        if row.get(1) is not None and row[1].value_text == "Metric"
    ]
    if len(header_rows) != 1:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    header = rows[header_rows[0]]
    period_columns = {
        cell.value_text: column
        for column, cell in header.items()
        if cell.value_text.startswith("FY")
    }
    unit_columns = [column for column, cell in header.items() if cell.value_text == "Unit"]
    metric_rows = {
        row[1].value_text: number
        for number, row in rows.items()
        if number != header_rows[0] and row.get(1) is not None
    }
    row_number = metric_rows.get(spec.name)
    column_number = period_columns.get(spec.period)
    if row_number is None or column_number is None or len(unit_columns) != 1:
        raise CalculationError(CalculationErrorCode.INPUTS_MISSING)
    value_cell = rows[row_number].get(column_number)
    unit_cell = rows[row_number].get(unit_columns[0])
    if (
        value_cell is None
        or unit_cell is None
        or value_cell.value_kind != "number"
        or value_cell.formula_like
        or unit_cell.value_text != spec.unit
    ):
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    try:
        value = Decimal(value_cell.value_text)
    except InvalidOperation:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID) from None
    if not value.is_finite() or abs(value) > Decimal("1000000000000"):
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    matches = [
        chunk
        for chunk in chunks
        if chunk.sheet_name == spec.sheet_name and chunk.row_start <= row_number <= chunk.row_end
    ]
    if len(matches) != 1:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    chunk = matches[0]
    return TrustedCalculationInput(
        name=spec.name,
        period=spec.period,
        value=float(value),
        unit=spec.unit,
        citation=CalculationCitation(
            document_id=chunk.document_id,
            document_version_id=chunk.document_version_id,
            chunk_id=chunk.chunk_id,
            document_title=chunk.document_title,
            version_number=chunk.version_number,
            excerpt=chunk.content[:500],
            sheet_name=spec.sheet_name,
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
    slug, version_id, inputs = await _load_inputs(
        session, scope, company_slug=company_slug, specs=_specs(metric, period)
    )
    return calculate(
        metric,
        company_slug=slug,
        period=period,
        document_version_id=str(version_id),
        inputs=inputs,
    )


async def query_authorized_financial_metric(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    metric: FinancialMetricName,
    company_slug: str,
    period: str,
) -> CalculationResult:
    sheet, name = _DIRECT_METRICS[metric]
    if metric in {FinancialMetricName.EBITDA, FinancialMetricName.NET_PROFIT}:
        calculation_metric = (
            CalculationMetric.EBITDA_MARGIN
            if metric is FinancialMetricName.EBITDA
            else CalculationMetric.NET_PROFIT_MARGIN
        )
        slug, version_id, inputs = await _load_inputs(
            session,
            scope,
            company_slug=company_slug,
            specs=_specs(calculation_metric, period),
        )
        return derived_profit_metric_result(
            metric_name="EBITDA" if metric is FinancialMetricName.EBITDA else "Net Profit",
            company_slug=slug,
            period=period,
            document_version_id=str(version_id),
            inputs=inputs,
        )
    slug, version_id, inputs = await _load_inputs(
        session,
        scope,
        company_slug=company_slug,
        specs=(_InputSpec(sheet, name, period),),
    )
    return direct_metric_result(
        company_slug=slug,
        period=period,
        document_version_id=str(version_id),
        trusted_input=inputs[0],
    )


async def calculate_authorized_cagr(
    session: AsyncSession,
    scope: AuthorizationScope,
    *,
    company_slug: str,
    start_period: str,
    end_period: str,
) -> CalculationResult:
    slug, version_id, inputs = await _load_inputs(
        session,
        scope,
        company_slug=company_slug,
        specs=(
            _InputSpec("P&L", "Revenue", start_period),
            _InputSpec("P&L", "Revenue", end_period),
        ),
    )
    return calculate_cagr(
        company_slug=slug,
        start_period=start_period,
        end_period=end_period,
        document_version_id=str(version_id),
        inputs=inputs,
    )
