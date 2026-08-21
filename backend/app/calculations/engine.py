from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
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
    if metric is CalculationMetric.EBITDA_MARGIN:
        return (
            ("Revenue", period),
            ("Cost of Goods Sold", period),
            ("Operating Expenses (excl. D&A)", period),
        )
    if metric is CalculationMetric.REVENUE_GROWTH:
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

    if metric is CalculationMetric.REVENUE_GROWTH:
        prior_period = previous_period(period)
        prior = values[("Revenue", prior_period)]
        current = values[("Revenue", period)]
        denominator = prior
        numerator = current - prior
        formula = f"((Revenue[{period}] - Revenue[{prior_period}]) / Revenue[{prior_period}]) × 100"
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
    result = (numerator / denominator * Decimal("100")).quantize(
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
    )
