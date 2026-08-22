import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.api import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


class APIError(Exception):
    """An expected, client-safe API failure."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message),
        request_id=_request_id(request),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, APIError)
    return _error_response(request, exc.status_code, exc.code, exc.message)


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    status = HTTPStatus(exc.status_code)
    code = status.name.lower()
    return _error_response(request, exc.status_code, code, status.phrase)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return _error_response(request, 422, "validation_error", "Request validation failed.")


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_request_error",
        extra={"request_id": _request_id(request), "error_type": type(exc).__name__},
    )
    return _error_response(request, 500, "internal_error", "Internal server error.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
