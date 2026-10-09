"""Construct independent app instances with validated, injectable settings."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from mastery_backend.api.errors import http_error_handler, validation_error_handler
from mastery_backend.api.middleware import (
    ApiCORSMiddleware,
    HostGuardMiddleware,
    RequestContextMiddleware,
    RequestGuardMiddleware,
)
from mastery_backend.api.routes import config_router, health_router
from mastery_backend.infrastructure.database.session import (
    create_database_engine,
    create_session_factory,
)
from mastery_backend.infrastructure.observability.logging import configure_logging, logger
from mastery_backend.settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_database_engine(app.state.settings)
    app.state.database_engine = engine
    app.state.session_factory = create_session_factory(engine)
    logger.info("application_started")
    try:
        yield
    finally:
        engine.dispose()
        logger.info("application_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    configure_logging(configuration.log_level)
    app = FastAPI(
        title="Python Mastery Backend",
        version="0.1.0",
        docs_url="/docs" if configuration.docs_enabled else None,
        redoc_url="/redoc" if configuration.docs_enabled else None,
        openapi_url="/openapi.json" if configuration.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = configuration
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(health_router)
    app.include_router(config_router)
    # Last added is outermost: tracing covers CORS and guard failures too.
    app.add_middleware(RequestGuardMiddleware, settings=configuration)
    app.add_middleware(
        ApiCORSMiddleware,
        allow_origins=configuration.allowed_origins,
        allow_credentials=configuration.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "Idempotency-Key", "X-Request-ID", "X-CSRF-Token"],
        expose_headers=["X-Request-ID", "Location", "Retry-After", "Idempotency-Replayed"],
    )
    app.add_middleware(HostGuardMiddleware, settings=configuration)
    app.add_middleware(RequestContextMiddleware, settings=configuration)
    return app
