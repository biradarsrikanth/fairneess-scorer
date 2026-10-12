"""Every error response is RFC 9457 problem details (``application/problem+json``), the same contract as the
gateway's ApiError: the standard members plus a stable ``code`` to branch on, ``errors`` for individual
parameters, and the ``request_id``. Server errors never include exception messages or database details."""
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from http import HTTPStatus
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pandas.errors import DatabaseError as PandasDatabaseError
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.core.middleware import REQUEST_ID_HEADER

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


class ErrorCode(StrEnum):
    VALIDATION_FAILED = "VALIDATION_FAILED"
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class FieldError(BaseModel):
    field: str | None
    message: str


class Problem(BaseModel):
    """The error body, for the OpenAPI document."""
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str
    code: ErrorCode
    errors: list[FieldError] = []
    request_id: str | None = None
    timestamp: datetime


def problem(request: Request, status: int, code: ErrorCode, detail: str,
            errors: list[FieldError] | None = None, headers: Mapping[str, str] | None = None) -> JSONResponse:
    # request.state, not the logging context: the 500 handler runs after the middleware has reset that
    request_id = getattr(request.state, "request_id", None)
    body = Problem(title=HTTPStatus(status).phrase, status=status, detail=detail, instance=request.url.path,
                   code=code, errors=errors or [], request_id=request_id, timestamp=datetime.now(UTC))
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(body.model_dump(mode="json"), status_code=status, media_type=PROBLEM_JSON,
                        headers=response_headers)


def _code_for(status: int) -> ErrorCode:
    match status:
        case 400 | 422:
            return ErrorCode.VALIDATION_FAILED
        case 401:
            return ErrorCode.UNAUTHORIZED
        case 404:
            return ErrorCode.NOT_FOUND
        case 405:
            return ErrorCode.METHOD_NOT_ALLOWED
        case _:
            return ErrorCode.BAD_REQUEST if status < 500 else ErrorCode.INTERNAL_ERROR


# Handlers take Exception (Starlette's handler type); each is registered for one exception class only
async def http_error(request: Request, exc: Exception) -> JSONResponse:
    http_exc = cast(StarletteHTTPException, exc)
    status = http_exc.status_code
    detail = http_exc.detail if isinstance(http_exc.detail, str) else HTTPStatus(status).phrase
    return problem(request, status, _code_for(status), detail, headers=http_exc.headers)


async def validation_error(request: Request, exc: Exception) -> JSONResponse:
    errors = [FieldError(field=_field(error["loc"]), message=error["msg"])
              for error in cast(RequestValidationError, exc).errors()]
    errors.sort(key=lambda e: (e.field or "", e.message))
    detail = "; ".join(f"{e.field}: {e.message}" if e.field else e.message for e in errors)
    return problem(request, 422, ErrorCode.VALIDATION_FAILED, detail, errors)


def _field(loc: tuple[int | str, ...]) -> str | None:
    """("query", "days") → "days"; ("body", "items", 0, "name") → "items[0].name"."""
    parts = list(loc[1:] if loc and loc[0] in ("query", "path", "body", "header", "cookie") else loc)
    if not parts:
        return None
    field = ""
    for part in parts:
        field += f"[{part}]" if isinstance(part, int) else (f".{part}" if field else str(part))
    return field


# pandas.read_sql wraps SQLAlchemy errors in its own DatabaseError
async def database_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Database error on %s %s", request.method, request.url.path)
    return problem(request, 503, ErrorCode.UPSTREAM_UNAVAILABLE, "Database unavailable")


async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return problem(request, 500, ErrorCode.INTERNAL_ERROR, "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(SQLAlchemyError, database_error)
    app.add_exception_handler(PandasDatabaseError, database_error)
    app.add_exception_handler(Exception, unexpected_error)
