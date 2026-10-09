"""Pure ASGI boundaries for request tracing and bounded request bodies."""

import re
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mastery_backend.api.errors import error_response
from mastery_backend.infrastructure.observability.logging import logger, request_id_context
from mastery_backend.settings import Settings

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied_id = Headers(scope=scope).get("x-request-id", "")
        request_id = supplied_id if REQUEST_ID_PATTERN.fullmatch(supplied_id) else uuid4().hex
        token = request_id_context.set(request_id)
        started_at = perf_counter()
        response_started = False
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["Cache-Control"] = "no-store"
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception:
            logger.exception("request_failed")
            if response_started:
                raise  # A second response would corrupt an already-started response.
            # This fallback is outside CORS. Preserve its exact-origin policy so
            # a permitted browser can still inspect the safe error/request ID.
            origin = Headers(scope=scope).get("origin")
            headers: dict[str, str] = {}
            if origin in self.settings.allowed_origins:
                headers["Access-Control-Allow-Origin"] = origin
                headers["Access-Control-Expose-Headers"] = "X-Request-ID"
                headers["Vary"] = "Origin"
                if self.settings.cors_allow_credentials:
                    headers["Access-Control-Allow-Credentials"] = "true"
            await error_response(
                500, "INTERNAL_ERROR", "An unexpected error occurred.", headers=headers
            )(scope, receive, send_with_context)
        finally:
            route = scope.get("route")
            logger.info(
                "request_completed",
                extra={
                    "operation": getattr(route, "path", "unmatched"),
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                },
            )
            request_id_context.reset(token)


class RequestGuardMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        declared_length = headers.get("content-length")
        if declared_length is not None:
            if not re.fullmatch(r"[0-9]{1,20}", declared_length):
                await error_response(400, "INVALID_CONTENT_LENGTH", "Invalid body length.")(
                    scope, receive, send
                )
                return
            if int(declared_length) > self.settings.max_request_body_bytes:
                await self.reject_size(scope, receive, send)
                return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.settings.max_request_body_bytes:
                await self.reject_size(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        if (
            body
            and headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            await error_response(415, "UNSUPPORTED_MEDIA_TYPE", "Use application/json.")(
                scope, receive, send
            )
            return
        delivered = False

        async def replay_body() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay_body, send)

    async def reject_size(self, scope: Scope, receive: Receive, send: Send) -> None:
        await error_response(413, "REQUEST_TOO_LARGE", "The request body is too large.")(
            scope, receive, send
        )


class HostGuardMiddleware:
    """Validate Host even for preflight requests answered by CORS middleware."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            try:
                authority = urlsplit("http://" + Headers(scope=scope).get("host", ""))
                valid = (
                    authority.hostname in self.settings.allowed_hosts
                    and not authority.username
                    and not authority.password
                    and not authority.path
                    and not authority.query
                    and not authority.fragment
                )
                _ = authority.port
            except ValueError:
                valid = False
            if not valid:
                await error_response(400, "INVALID_HOST", "The request host is not allowed.")(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


class ApiCORSMiddleware(CORSMiddleware):
    """Preserve framework CORS behavior while normalizing preflight errors."""

    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if response.status_code == 400:
            headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in {"content-length", "content-type"}
            }
            return error_response(
                400, "CORS_DENIED", "The browser origin or request is not allowed.", headers=headers
            )
        return response
