"""Shared safe error contract for middleware and route exception handlers."""

from collections.abc import Mapping

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from mastery_backend.infrastructure.observability.logging import request_id_context


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
