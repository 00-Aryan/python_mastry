"""Owned assistance routes; all release and transaction rules live in services."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse

from mastery_backend.api.admin_responses import command_response, content_errors
from mastery_backend.api.dependencies import assistance_service, idempotency_key, learner
from mastery_backend.api.errors import ErrorEnvelope
from mastery_backend.api.schemas.assistance import NextAssistance, SolutionEscape
from mastery_backend.application.assistance_service import AssistanceService
from mastery_backend.domain.assistance_records import AssistanceHistory, AssistanceResponse
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal

Learner = Annotated[Principal, Depends(learner)]
Service = Annotated[AssistanceService, Depends(assistance_service)]
Key = Annotated[str, Depends(idempotency_key)]
router = APIRouter(
    prefix="/api/v1/attempts/{attempt_id}/assistance",
    tags=["progressive assistance"],
    responses={
        **content_errors,
        401: {"model": ErrorEnvelope, "description": "Active local identity required"},
        403: {"model": ErrorEnvelope, "description": "Stored learner role required"},
        409: {
            "model": ErrorEnvelope,
            "description": "Revision, waiting interval, exhausted ladder or retry conflict",
        },
        503: {
            "model": ErrorEnvelope,
            "description": "Pinned policy/assets or database unavailable",
        },
    },
)


@router.post("/next", response_model=AssistanceResponse, operation_id="grant_next_assistance")
def grant_next_assistance(
    attempt_id: UUID, body: NextAssistance, principal: Learner, service: Service, key: Key
) -> JSONResponse:
    return command_response(
        service.grant(principal, attempt_id, key, "next", body.expected_revision, body.trigger)
    )


@router.post("/solution", response_model=AssistanceResponse, operation_id="grant_full_solution")
def grant_full_solution(
    attempt_id: UUID, body: SolutionEscape, principal: Learner, service: Service, key: Key
) -> JSONResponse:
    if not body.confirmation:
        raise ContentError("VALIDATION_ERROR", "Confirm full-solution disclosure explicitly.")
    return command_response(
        service.grant(
            principal, attempt_id, key, "solution", body.expected_revision, "solution_escape"
        )
    )


@router.get("", response_model=AssistanceHistory, operation_id="read_assistance_history")
def read_assistance_history(
    attempt_id: UUID, principal: Learner, service: Service
) -> AssistanceHistory:
    return service.history(principal, attempt_id)
