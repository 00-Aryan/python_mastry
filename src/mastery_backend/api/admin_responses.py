"""Shared HTTP error documentation and durable admin command response headers."""

from typing import Any

from starlette.responses import JSONResponse

from mastery_backend.api.errors import ErrorEnvelope
from mastery_backend.application.admin_commands import CommandResult

content_errors: dict[int | str, dict[str, Any]] = {
    400: {
        "model": ErrorEnvelope,
        "description": "Malformed JSON or invalid/expired catalog cursor",
    },
    404: {"model": ErrorEnvelope, "description": "Resource missing or unavailable to this reader"},
    422: {"model": ErrorEnvelope, "description": "Invalid input or content reference"},
    503: {"model": ErrorEnvelope, "description": "Database unavailable"},
    500: {"model": ErrorEnvelope, "description": "Unexpected fault; safe details only"},
}


def command_response(result: CommandResult) -> JSONResponse:
    headers = {}
    if result.location:
        headers["Location"] = result.location
    if result.replayed:
        headers["Idempotency-Replayed"] = "true"
    return JSONResponse(result.body, status_code=result.status_code, headers=headers)
