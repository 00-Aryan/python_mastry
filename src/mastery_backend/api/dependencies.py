"""HTTP adapters for local principal resolution and independently scoped services."""

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.assistance_service import AssistanceService
from mastery_backend.application.attempt_service import AttemptService
from mastery_backend.application.catalog_service import CatalogService
from mastery_backend.application.clock import Clock, SystemClock
from mastery_backend.application.content_service import ContentService
from mastery_backend.application.evaluation_service import EvaluationService
from mastery_backend.application.identity_service import read_development_principal
from mastery_backend.application.publication_report_verifier import StoredReferenceVerifier
from mastery_backend.application.publication_verification import (
    ReferenceVerifier,
    UnavailableReferenceVerifier,
)
from mastery_backend.application.skill_service import SkillService
from mastery_backend.application.submission_service import SubmissionService
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal, require_content_admin, require_learner
from mastery_backend.infrastructure.runner.runner_protocol import RunnerAdapter


def session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


def current_principal(
    request: Request, factory: Annotated[sessionmaker[Session], Depends(session_factory)]
) -> Principal:
    settings = request.app.state.settings
    if settings.development_user_id is None:
        raise ContentError("UNAUTHENTICATED", "Configure a seeded local development identity.")
    peer = request.client.host if request.client else ""
    local_peers = {"127.0.0.1", "::1"}
    if settings.app_env == "test":
        local_peers.add("testclient")
    if peer not in local_peers:
        raise ContentError("FORBIDDEN", "Development identity requires a local connection.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        permitted = set(settings.allowed_origins) | {
            f"http://localhost:{settings.api_port}",
            f"http://127.0.0.1:{settings.api_port}",
        }
        if request.headers.get("sec-fetch-site") == "cross-site" or (
            origin and origin not in permitted
        ):
            raise ContentError("FORBIDDEN", "The request origin is not permitted.")
    return read_development_principal(factory, settings.development_user_id)


def content_administrator(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    require_content_admin(principal)
    return principal


def server_clock() -> Clock:
    return SystemClock()


def reference_verifier(
    request: Request,
    factory: Annotated[sessionmaker[Session], Depends(session_factory)],
    clock: Annotated[Clock, Depends(server_clock)],
) -> ReferenceVerifier:
    policy_id = request.app.state.settings.publication_evaluator_policy_version_id
    if policy_id is None:
        return UnavailableReferenceVerifier()
    return StoredReferenceVerifier(factory, clock, policy_id)


def content_service(
    factory: Annotated[sessionmaker[Session], Depends(session_factory)],
    verifier: Annotated[ReferenceVerifier, Depends(reference_verifier)],
) -> ContentService:
    return ContentService(factory, verifier)


def catalog_service(
    factory: Annotated[sessionmaker[Session], Depends(session_factory)],
) -> CatalogService:
    return CatalogService(factory)


def idempotency_key(
    value: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> str:
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        raise ContentError("INVALID_IDEMPOTENCY_KEY", "Use 1–128 printable ASCII characters.")
    return value


def skill_service(
    factory: Annotated[sessionmaker[Session], Depends(session_factory)],
) -> SkillService:
    return SkillService(factory)


def learner(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    require_learner(principal)
    return principal


def attempt_service(
    factory: Annotated[sessionmaker[Session], Depends(session_factory)],
    clock: Annotated[Clock, Depends(server_clock)],
) -> AttemptService:
    return AttemptService(factory, clock)


def assistance_service(
    factory: Annotated[sessionmaker[Session], Depends(session_factory)],
    clock: Annotated[Clock, Depends(server_clock)],
) -> AssistanceService:
    return AssistanceService(factory, clock)


def submission_service(
    request: Request,
    factory: Annotated[sessionmaker[Session], Depends(session_factory)],
    clock: Annotated[Clock, Depends(server_clock)],
) -> SubmissionService:
    return SubmissionService(factory, clock, request.app.state.settings.max_code_bytes)


def runner_adapter(
    request: Request,
    factory: Annotated[sessionmaker[Session], Depends(session_factory)],
    clock: Annotated[Clock, Depends(server_clock)],
) -> RunnerAdapter | None:
    if not request.app.state.settings.local_runner_enabled:
        return None
    from mastery_backend.application.worker_authority import LocalRunnerAdmission

    return LocalRunnerAdmission(factory, clock)


def evaluation_service(
    request: Request,
    factory: Annotated[sessionmaker[Session], Depends(session_factory)],
    clock: Annotated[Clock, Depends(server_clock)],
    adapter: Annotated[RunnerAdapter | None, Depends(runner_adapter)],
) -> EvaluationService:
    return EvaluationService(factory, clock, adapter, request.app.state.settings.app_env)
