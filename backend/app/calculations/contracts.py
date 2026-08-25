import math
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictCalculationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CalculationMetric(StrEnum):
    FINANCIAL_METRIC = "financial_metric"
    EBITDA_MARGIN = "ebitda_margin"
    REVENUE_GROWTH = "revenue_growth"
    NET_PROFIT_MARGIN = "net_profit_margin"
    DEBT_TO_EQUITY = "debt_to_equity"
    CASH_RUNWAY = "cash_runway"
    CAGR = "cagr"


class CalculationCitation(StrictCalculationModel):
    document_id: UUID
    document_version_id: UUID
    chunk_id: UUID
    document_title: str = Field(min_length=1, max_length=255)
    version_number: int = Field(ge=1)
    excerpt: str = Field(min_length=1, max_length=500)
    sheet_name: str = Field(default="P&L", min_length=1, max_length=128)
    row_start: int = Field(ge=1)
    row_end: int = Field(ge=1)
    cell_start: str = Field(pattern=r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")
    cell_end: str = Field(pattern=r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")

    @model_validator(mode="after")
    def ordered_location(self) -> "CalculationCitation":
        if self.row_end < self.row_start:
            raise ValueError("Calculation citation rows are inverted")
        return self


class TrustedCalculationInput(StrictCalculationModel):
    name: str = Field(min_length=1, max_length=80)
    period: str = Field(pattern=r"^FY[0-9]{4}$")
    value: float
    unit: Literal["INR crore", "INR crore/month"] = "INR crore"
    citation: CalculationCitation

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not math.isfinite(value) or abs(value) > 1_000_000_000_000:
            raise ValueError("Calculation input must be finite and bounded")
        return value


class CalculationResult(StrictCalculationModel):
    calculation_id: UUID
    metric: CalculationMetric
    company_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64)
    period: str = Field(pattern=r"^FY[0-9]{4}$")
    formula: str = Field(min_length=1, max_length=400)
    trusted_inputs: Annotated[
        tuple[TrustedCalculationInput, ...], Field(min_length=1, max_length=10)
    ]
    result: float
    unit: Literal["percent", "x", "months", "INR crore"] = "percent"
    warnings: tuple[str, ...] = Field(default=(), max_length=4)

    @field_validator("result")
    @classmethod
    def finite_result(cls, value: float) -> float:
        if not math.isfinite(value) or abs(value) > 1_000_000:
            raise ValueError("Calculation result must be finite and bounded")
        return value
