from uuid import uuid4

import pytest

from app.calculations.contracts import (
    CalculationCitation,
    CalculationMetric,
    TrustedCalculationInput,
)
from app.calculations.engine import (
    CalculationError,
    CalculationErrorCode,
    calculate,
    required_inputs,
)


def _input(name: str, period: str, value: float) -> TrustedCalculationInput:
    row = {
        "Revenue": 4,
        "Cost of Goods Sold": 5,
        "Operating Expenses (excl. D&A)": 7,
        "Depreciation & Amortization": 9,
        "Interest Expense": 11,
        "Tax Expense": 13,
    }[name]
    return TrustedCalculationInput(
        name=name,
        period=period,
        value=value,
        citation=CalculationCitation(
            document_id=uuid4(),
            document_version_id=uuid4(),
            chunk_id=uuid4(),
            document_title="Financials.xlsx",
            version_number=1,
            excerpt="Authorized structured input",
            row_start=row,
            row_end=row,
            cell_start=f"A{row}",
            cell_end=f"D{row}",
        ),
    )


@pytest.mark.parametrize(
    ("metric", "values", "expected"),
    [
        (
            CalculationMetric.EBITDA_MARGIN,
            {
                ("Revenue", "FY2025"): 150,
                ("Cost of Goods Sold", "FY2025"): 96,
                ("Operating Expenses (excl. D&A)", "FY2025"): 39,
            },
            10.0,
        ),
        (
            CalculationMetric.REVENUE_GROWTH,
            {("Revenue", "FY2024"): 120, ("Revenue", "FY2025"): 150},
            25.0,
        ),
        (
            CalculationMetric.NET_PROFIT_MARGIN,
            {
                ("Revenue", "FY2025"): 150,
                ("Cost of Goods Sold", "FY2025"): 96,
                ("Operating Expenses (excl. D&A)", "FY2025"): 39,
                ("Depreciation & Amortization", "FY2025"): 5,
                ("Interest Expense", "FY2025"): 4,
                ("Tax Expense", "FY2025"): 1.5,
            },
            3.0,
        ),
    ],
)
def test_formulas_use_only_ordered_trusted_inputs(
    metric: CalculationMetric,
    values: dict[tuple[str, str], float],
    expected: float,
) -> None:
    inputs = tuple(
        _input(name, period, values[(name, period)])
        for name, period in required_inputs(metric, "FY2025")
    )

    result = calculate(
        metric,
        company_slug="orion-main",
        period="FY2025",
        document_version_id="version-1",
        inputs=inputs,
    )

    assert result.result == expected
    assert result.unit == "percent"
    assert result.formula
    assert result.trusted_inputs == inputs


def test_zero_denominator_and_reordered_inputs_fail_closed() -> None:
    growth = (
        _input("Revenue", "FY2024", 0),
        _input("Revenue", "FY2025", 150),
    )
    with pytest.raises(CalculationError) as zero:
        calculate(
            CalculationMetric.REVENUE_GROWTH,
            company_slug="orion-main",
            period="FY2025",
            document_version_id="version-1",
            inputs=growth,
        )
    assert zero.value.code is CalculationErrorCode.DIVISION_BY_ZERO

    with pytest.raises(CalculationError) as reordered:
        calculate(
            CalculationMetric.REVENUE_GROWTH,
            company_slug="orion-main",
            period="FY2025",
            document_version_id="version-1",
            inputs=tuple(reversed(growth)),
        )
    assert reordered.value.code is CalculationErrorCode.INPUTS_INVALID
