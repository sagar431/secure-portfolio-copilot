from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from app.calculations.contracts import (
    CalculationMetric,
    CalculationResult,
    TrustedCalculationInput,
)


class CalculationErrorCode(StrEnum):
    INPUTS_MISSING = "CALCULATION_INPUTS_MISSING"
    INPUTS_INVALID = "CALCULATION_INPUTS_INVALID"
    DIVISION_BY_ZERO = "CALCULATION_DIVISION_BY_ZERO"


class CalculationError(ValueError):
    def __init__(self, code: CalculationErrorCode) -> None:
        super().__init__("Deterministic calculation failed safely.")
        self.code = code


def previous_period(period: str) -> str:
    try:
        year = int(period.removeprefix("FY"))
    except ValueError:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID) from None
    return f"FY{year - 1:04d}"


def required_inputs(metric: CalculationMetric, period: str) -> tuple[tuple[str, str], ...]:
    if metric is CalculationMetric.FINANCIAL_METRIC:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    if metric is CalculationMetric.EBITDA_MARGIN:
        return (
            ("Revenue", period),
            ("Cost of Goods Sold", period),
            ("Operating Expenses (excl. D&A)", period),
        )
    if metric is CalculationMetric.REVENUE_GROWTH:
        return (("Revenue", previous_period(period)), ("Revenue", period))
    if metric is CalculationMetric.DEBT_TO_EQUITY:
        return (
            ("Cash and Cash Equivalents", period),
            ("Accounts Receivable", period),
            ("Inventory / Prepaid Assets", period),
            ("Property, Plant & Equipment", period),
            ("Bank Debt", period),
            ("Accounts Payable", period),
            ("Other Liabilities", period),
        )
    if metric is CalculationMetric.CASH_RUNWAY:
        return (
            ("Opening Cash", period),
            ("Operating Cash Flow", period),
            ("Capital Expenditure", period),
            ("Financing Cash Flow", period),
            ("Stress-case Monthly Burn", period),
        )
    if metric is CalculationMetric.CAGR:
        return (("Revenue", previous_period(period)), ("Revenue", period))
    return (
        ("Revenue", period),
        ("Cost of Goods Sold", period),
        ("Operating Expenses (excl. D&A)", period),
        ("Depreciation & Amortization", period),
        ("Interest Expense", period),
        ("Tax Expense", period),
    )


def _decimal(item: TrustedCalculationInput) -> Decimal:
    try:
        return Decimal(str(item.value))
    except InvalidOperation:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID) from None


def calculate(
    metric: CalculationMetric,
    *,
    company_slug: str,
    period: str,
    document_version_id: str,
    inputs: tuple[TrustedCalculationInput, ...],
) -> CalculationResult:
    expected = required_inputs(metric, period)
    values = {(item.name, item.period): _decimal(item) for item in inputs}
    if len(values) != len(inputs) or tuple(values) != expected:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)

    unit: Literal["percent", "x", "months", "INR crore"] = "percent"
    if metric is CalculationMetric.REVENUE_GROWTH:
        prior_period = previous_period(period)
        prior = values[("Revenue", prior_period)]
        current = values[("Revenue", period)]
        denominator = prior
        numerator = current - prior
        formula = f"((Revenue[{period}] - Revenue[{prior_period}]) / Revenue[{prior_period}]) × 100"
    elif metric is CalculationMetric.CAGR:
        prior_period = previous_period(period)
        prior = values[("Revenue", prior_period)]
        current = values[("Revenue", period)]
        if prior <= 0:
            raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
        denominator = Decimal("1")
        numerator = (current / prior) ** (Decimal("1") / Decimal("1")) - Decimal("1")
        formula = f"((Revenue[{period}] / Revenue[{prior_period}]) ^ (1 / 1) - 1) × 100"
    elif metric is CalculationMetric.DEBT_TO_EQUITY:
        assets = sum(
            (
                values[(name, period)]
                for name in (
                    "Cash and Cash Equivalents",
                    "Accounts Receivable",
                    "Inventory / Prepaid Assets",
                    "Property, Plant & Equipment",
                )
            ),
            Decimal("0"),
        )
        liabilities = sum(
            (
                values[(name, period)]
                for name in ("Bank Debt", "Accounts Payable", "Other Liabilities")
            ),
            Decimal("0"),
        )
        denominator = assets - liabilities
        numerator = values[("Bank Debt", period)]
        formula = "Bank Debt / (Total Assets - Total Liabilities)"
        unit = "x"
    elif metric is CalculationMetric.CASH_RUNWAY:
        closing_cash = sum(
            (
                values[(name, period)]
                for name in (
                    "Opening Cash",
                    "Operating Cash Flow",
                    "Capital Expenditure",
                    "Financing Cash Flow",
                )
            ),
            Decimal("0"),
        )
        denominator = values[("Stress-case Monthly Burn", period)]
        numerator = closing_cash
        formula = (
            "(Opening Cash + Operating Cash Flow + Capital Expenditure + Financing Cash Flow) "
            "/ Stress-case Monthly Burn"
        )
        unit = "months"
    else:
        revenue = values[("Revenue", period)]
        denominator = revenue
        ebitda = (
            revenue
            - values[("Cost of Goods Sold", period)]
            - values[("Operating Expenses (excl. D&A)", period)]
        )
        if metric is CalculationMetric.EBITDA_MARGIN:
            numerator = ebitda
            formula = (
                "((Revenue - Cost of Goods Sold - Operating Expenses (excl. D&A)) / Revenue) × 100"
            )
        else:
            numerator = (
                ebitda
                - values[("Depreciation & Amortization", period)]
                - values[("Interest Expense", period)]
                - values[("Tax Expense", period)]
            )
            formula = (
                "((Revenue - Cost of Goods Sold - Operating Expenses (excl. D&A) - "
                "Depreciation & Amortization - Interest Expense - Tax Expense) "
                "/ Revenue) × 100"
            )
    if denominator == 0:
        raise CalculationError(CalculationErrorCode.DIVISION_BY_ZERO)
    multiplier = Decimal("100") if unit == "percent" else Decimal("1")
    result = (numerator / denominator * multiplier).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    return CalculationResult(
        calculation_id=uuid5(
            NAMESPACE_URL,
            f"secure-portfolio:{metric.value}:{company_slug}:{period}:{document_version_id}",
        ),
        metric=metric,
        company_slug=company_slug,
        period=period,
        formula=formula,
        trusted_inputs=inputs,
        result=float(result),
        unit=unit,
    )


def direct_metric_result(
    *,
    company_slug: str,
    period: str,
    document_version_id: str,
    trusted_input: TrustedCalculationInput,
) -> CalculationResult:
    return CalculationResult(
        calculation_id=uuid5(
            NAMESPACE_URL,
            f"secure-portfolio:financial_metric:{trusted_input.name}:{company_slug}:"
            f"{period}:{document_version_id}",
        ),
        metric=CalculationMetric.FINANCIAL_METRIC,
        company_slug=company_slug,
        period=period,
        formula="Direct authorized structured metric lookup",
        trusted_inputs=(trusted_input,),
        result=trusted_input.value,
        unit="INR crore",
    )


def derived_profit_metric_result(
    *,
    metric_name: Literal["EBITDA", "Net Profit"],
    company_slug: str,
    period: str,
    document_version_id: str,
    inputs: tuple[TrustedCalculationInput, ...],
) -> CalculationResult:
    metric = (
        CalculationMetric.EBITDA_MARGIN
        if metric_name == "EBITDA"
        else CalculationMetric.NET_PROFIT_MARGIN
    )
    # Reuse the exact input/order validation of the fixed margin calculator, then return the
    # underlying absolute value without trusting formula cells from the workbook.
    calculate(
        metric,
        company_slug=company_slug,
        period=period,
        document_version_id=document_version_id,
        inputs=inputs,
    )
    values = {(item.name, item.period): _decimal(item) for item in inputs}
    value = (
        values[("Revenue", period)]
        - values[("Cost of Goods Sold", period)]
        - values[("Operating Expenses (excl. D&A)", period)]
    )
    formula = "Revenue - Cost of Goods Sold - Operating Expenses (excl. D&A)"
    if metric_name == "Net Profit":
        value -= (
            values[("Depreciation & Amortization", period)]
            + values[("Interest Expense", period)]
            + values[("Tax Expense", period)]
        )
        formula += " - Depreciation & Amortization - Interest Expense - Tax Expense"
    value = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return CalculationResult(
        calculation_id=uuid5(
            NAMESPACE_URL,
            f"secure-portfolio:financial_metric:{metric_name}:{company_slug}:"
            f"{period}:{document_version_id}",
        ),
        metric=CalculationMetric.FINANCIAL_METRIC,
        company_slug=company_slug,
        period=period,
        formula=formula,
        trusted_inputs=inputs,
        result=float(value),
        unit="INR crore",
        warnings=("Derived from authorized raw rows; workbook formula cells were not trusted.",),
    )


def calculate_cagr(
    *,
    company_slug: str,
    start_period: str,
    end_period: str,
    document_version_id: str,
    inputs: tuple[TrustedCalculationInput, ...],
) -> CalculationResult:
    years = int(end_period[2:]) - int(start_period[2:])
    expected = (("Revenue", start_period), ("Revenue", end_period))
    values = {(item.name, item.period): _decimal(item) for item in inputs}
    if years <= 0 or tuple(values) != expected or len(values) != 2:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    start = values[("Revenue", start_period)]
    end = values[("Revenue", end_period)]
    if start <= 0:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID)
    try:
        result = ((end / start) ** (Decimal("1") / Decimal(years)) - Decimal("1")) * Decimal("100")
    except InvalidOperation:
        raise CalculationError(CalculationErrorCode.INPUTS_INVALID) from None
    result = result.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return CalculationResult(
        calculation_id=uuid5(
            NAMESPACE_URL,
            f"secure-portfolio:cagr:{company_slug}:{start_period}:{end_period}:"
            f"{document_version_id}",
        ),
        metric=CalculationMetric.CAGR,
        company_slug=company_slug,
        period=end_period,
        formula=(f"((Revenue[{end_period}] / Revenue[{start_period}]) ^ (1 / {years}) - 1) × 100"),
        trusted_inputs=inputs,
        result=float(result),
        unit="percent",
    )
