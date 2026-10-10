"""Owned evaluation admission and safe status projections; no result callback."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse

from mastery_backend.api.admin_responses import command_response, content_errors
from mastery_backend.api.dependencies import evaluation_service, idempotency_key, learner
from mastery_backend.api.errors import ErrorEnvelope
from mastery_backend.api.schemas.attempts import AttemptRevision
from mastery_backend.application.evaluation_service import EvaluationService
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.evaluations import EvaluationDetail, EvaluationListQuery, EvaluationPage
from mastery_backend.domain.identity import Principal

Learner = Annotated[Principal, Depends(learner)]
Service = Annotated[EvaluationService, Depends(evaluation_service)]
Key = Annotated[str, Depends(idempotency_key)]
router = APIRouter(
    prefix="/api/v1",
    tags=["evaluations"],
    responses={
        **content_errors,
        401: {"model": ErrorEnvelope},
        403: {"model": ErrorEnvelope},
        409: {"model": ErrorEnvelope},
        503: {"model": ErrorEnvelope, "description": "No supported isolated runner is configured"},
    },
)


@router.post(
    "/submissions/{submission_id}/evaluations",
    response_model=EvaluationDetail,
    status_code=202,
    operation_id="request_submission_evaluation",
)
def request_evaluation(
    submission_id: UUID, body: AttemptRevision, principal: Learner, service: Service, key: Key
) -> JSONResponse:
    return command_response(service.request(principal, submission_id, key, body.expected_revision))


@router.get(
    "/evaluations/{job_id}", response_model=EvaluationDetail, operation_id="read_evaluation"
)
def read_evaluation(job_id: UUID, principal: Learner, service: Service) -> EvaluationDetail:
    return service.read(principal, job_id)


@router.get(
    "/attempts/{attempt_id}/evaluations",
    response_model=EvaluationPage,
    operation_id="list_attempt_evaluations",
)
def list_evaluations(
    attempt_id: UUID,
    request: Request,
    query: Annotated[EvaluationListQuery, Query()],
    principal: Learner,
    service: Service,
) -> EvaluationPage:
    if query.limit > request.app.state.settings.max_page_size:
        raise ContentError("VALIDATION_ERROR", "The requested page exceeds MAX_PAGE_SIZE.")
    return service.list_evaluations(principal, attempt_id, query)
