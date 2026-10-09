"""Shared safe error contract for middleware and route exception handlers."""

from collections.abc import Mapping

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from mastery_backend.infrastructure.observability.logging import request_id_context


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None
    details: dict[str, object]


class ErrorEnvelope(BaseModel):
    error: ErrorBody


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id_context.get(),
                "details": details or {},
            }
        },
        headers=headers,
    )


async def http_error_handler(request: Request, exception: Exception) -> JSONResponse:
    assert isinstance(exception, HTTPException)
    codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHENTICATED"}
    return error_response(
        exception.status_code,
        codes.get(exception.status_code, "HTTP_ERROR"),
        "The request could not be completed.",
        headers=exception.headers,
    )


async def validation_error_handler(request: Request, exception: Exception) -> JSONResponse:
    assert isinstance(exception, RequestValidationError)
    errors = exception.errors()
    malformed = any(error["type"] == "json_invalid" for error in errors)
    return error_response(
        400 if malformed else 422,
        "MALFORMED_JSON" if malformed else "VALIDATION_ERROR",
        "The request input is invalid.",
        {"fields": [{"path": list(error["loc"]), "reason": error["type"]} for error in errors]},
    )


async def content_error_handler(request: Request, exception: Exception) -> JSONResponse:
    from mastery_backend.domain.content import ContentError

    assert isinstance(exception, ContentError)
    statuses = {
        "UNAUTHENTICATED": 401,
        "FORBIDDEN": 403,
        "NOT_FOUND": 404,
        "INVALID_SKILL": 422,
        "INVALID_BUDGET": 422,
        "INVALID_MODE": 422,
        "CLOCK_UNAVAILABLE": 503,
        "POLICY_UNAVAILABLE": 503,
        "ASSISTANCE_UNAVAILABLE": 503,
        "GRAPH_READ_LIMIT": 422,
        "INVALID_PATTERN": 422,
        "INVALID_FAMILY": 422,
        "INVALID_LINK": 422,
        "INVALID_DRAFT": 422,
        "INVALID_IDEMPOTENCY_KEY": 422,
        "VALIDATION_ERROR": 422,
        "INVALID_CURSOR": 400,
        "VERIFICATION_UNAVAILABLE": 503,
    }
    return error_response(statuses.get(exception.code, 409), exception.code, exception.message)


async def database_error_handler(request: Request, exception: Exception) -> JSONResponse:
    from mastery_backend.infrastructure.observability.logging import logger

    logger.error(
        "database_unavailable", exc_info=(type(exception), exception, exception.__traceback__)
    )
    return error_response(503, "DATABASE_UNAVAILABLE", "The database is unavailable.")
