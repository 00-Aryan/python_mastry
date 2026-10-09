"""Only released foundation endpoints; no simulated learning capabilities."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from mastery_backend import __version__
from mastery_backend.api.errors import error_response
from mastery_backend.infrastructure.database.session import check_database_connection
from mastery_backend.infrastructure.observability.logging import logger


class HealthResponse(BaseModel):
    status: Literal["alive", "ready"]
    release_stage: Literal["B4-progressive-assistance"] = "B4-progressive-assistance"
    database: Literal["not_checked", "connected"] = "not_checked"
    evaluation: Literal["not_integrated"] = "not_integrated"


class PublicConfigResponse(BaseModel):
    api_version: Literal["v1"] = "v1"
    application_version: str = __version__
    release_stage: Literal["B4-progressive-assistance"] = "B4-progressive-assistance"
    capabilities: list[str] = ["attempt_lifecycle", "server_timers", "progressive_assistance"]
    attempt_modes: list[str] = ["practice", "assessment"]
    learning_policy: None = None


health_router = APIRouter(prefix="/health", tags=["health"])
config_router = APIRouter(prefix="/api/v1", tags=["configuration"])


@health_router.get("/live", response_model=HealthResponse, operation_id="read_liveness")
def read_liveness() -> HealthResponse:
    return HealthResponse(status="alive")


@health_router.get("/ready", response_model=HealthResponse, operation_id="read_readiness")
def read_readiness(request: Request) -> HealthResponse | JSONResponse:
    """Probe PostgreSQL in a worker thread; liveness remains independent."""
    try:
        check_database_connection(request.app.state.database_engine)
    except SQLAlchemyError:
        logger.exception("database_unavailable")
        return error_response(503, "DATABASE_UNAVAILABLE", "The database is unavailable.")
    return HealthResponse(status="ready", database="connected")


@config_router.get(
    "/config/public", response_model=PublicConfigResponse, operation_id="read_public_configuration"
)
def read_public_configuration() -> PublicConfigResponse:
    return PublicConfigResponse()
