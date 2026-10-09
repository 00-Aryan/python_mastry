"""Learner HTTP commands translate to owned application transactions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse

from mastery_backend.api.admin_responses import command_response, content_errors
from mastery_backend.api.dependencies import attempt_service, idempotency_key, learner
from mastery_backend.api.errors import ErrorEnvelope
from mastery_backend.api.schemas.attempts import (
    AttemptRevision,
    EndAttempt,
    ExtendAttempt,
    StartAttempt,
)
from mastery_backend.application.attempt_service import AttemptService
from mastery_backend.domain.attempt_records import AttemptListQuery, AttemptPage, AttemptSnapshot
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.content_records import PublicQuestionVersion
from mastery_backend.domain.identity import Principal

Learner = Annotated[Principal, Depends(learner)]
Service = Annotated[AttemptService, Depends(attempt_service)]
Key = Annotated[str, Depends(idempotency_key)]
router = APIRouter(
    prefix="/api/v1/attempts",
    tags=["attempt lifecycle"],
    responses={
        **content_errors,
        401: {"model": ErrorEnvelope, "description": "Active local identity required"},
        403: {"model": ErrorEnvelope, "description": "Stored learner role required"},
        409: {
            "model": ErrorEnvelope,
            "description": "Stale revision, invalid state, expired phase or incompatible retry",
        },
    },
)


@router.post("", response_model=AttemptSnapshot, status_code=201, operation_id="start_attempt")
def start_attempt(
    body: StartAttempt, principal: Learner, service: Service, key: Key
) -> JSONResponse:
    return command_response(
        service.start(
            principal, key, body.question_version_id, body.mode, body.independent_budget_seconds
        )
    )


@router.get("", response_model=AttemptPage, operation_id="list_attempts")
def list_attempts(
    request: Request,
    query: Annotated[AttemptListQuery, Query()],
    principal: Learner,
    service: Service,
) -> AttemptPage:
    if query.limit > request.app.state.settings.max_page_size:
        raise ContentError("VALIDATION_ERROR", "The requested page exceeds MAX_PAGE_SIZE.")
    return service.list_attempts(principal, query)


@router.get("/{attempt_id}", response_model=AttemptSnapshot, operation_id="read_attempt")
def read_attempt(attempt_id: UUID, principal: Learner, service: Service) -> AttemptSnapshot:
    return service.read(principal, attempt_id)


@router.get(
    "/{attempt_id}/question",
    response_model=PublicQuestionVersion,
    operation_id="read_attempt_question",
)
def read_attempt_question(
    attempt_id: UUID, principal: Learner, service: Service
) -> PublicQuestionVersion:
    return service.public_question(principal, attempt_id)


@router.post("/{attempt_id}/pause", response_model=AttemptSnapshot, operation_id="pause_attempt")
def pause_attempt(
    attempt_id: UUID, body: AttemptRevision, principal: Learner, service: Service, key: Key
) -> JSONResponse:
    return command_response(
        service.command(principal, key, attempt_id, "pause", body.expected_revision)
    )


@router.post("/{attempt_id}/resume", response_model=AttemptSnapshot, operation_id="resume_attempt")
def resume_attempt(
    attempt_id: UUID, body: AttemptRevision, principal: Learner, service: Service, key: Key
) -> JSONResponse:
    return command_response(
        service.command(principal, key, attempt_id, "resume", body.expected_revision)
    )


@router.post("/{attempt_id}/extend", response_model=AttemptSnapshot, operation_id="extend_attempt")
def extend_attempt(
    attempt_id: UUID, body: ExtendAttempt, principal: Learner, service: Service, key: Key
) -> JSONResponse:
    return command_response(
        service.command(
            principal,
            key,
            attempt_id,
            "extend",
            body.expected_revision,
            body.additional_budget_seconds,
            body.reason,
        )
    )


@router.post("/{attempt_id}/defer", response_model=AttemptSnapshot, operation_id="defer_attempt")
def defer_attempt(
    attempt_id: UUID, body: EndAttempt, principal: Learner, service: Service, key: Key
) -> JSONResponse:
    return command_response(
        service.command(
            principal, key, attempt_id, "defer", body.expected_revision, reason=body.reason
        )
    )


@router.post(
    "/{attempt_id}/abandon", response_model=AttemptSnapshot, operation_id="abandon_attempt"
)
def abandon_attempt(
    attempt_id: UUID, body: EndAttempt, principal: Learner, service: Service, key: Key
) -> JSONResponse:
    return command_response(
        service.command(
            principal, key, attempt_id, "abandon", body.expected_revision, reason=body.reason
        )
    )
