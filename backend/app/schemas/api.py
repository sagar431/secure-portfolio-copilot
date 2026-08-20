from typing import Literal

from pydantic import BaseModel


class SuccessResponse[T](BaseModel):
    data: T
    request_id: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


class HealthData(BaseModel):
    status: Literal["healthy"] = "healthy"


class ReadinessData(BaseModel):
    status: Literal["ready"] = "ready"
