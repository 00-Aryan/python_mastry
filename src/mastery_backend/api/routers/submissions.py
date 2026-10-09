"""Thin receipt HTTP routes; source is passed only to the storage use case."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse

from mastery_backend.api.admin_responses import command_response, content_errors
from mastery_backend.api.dependencies import idempotency_key, learner, submission_service
from mastery_backend.api.errors import ErrorEnvelope
from mastery_backend.api.schemas.submissions import AcceptSubmission
from mastery_backend.application.submission_service import SubmissionService
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal
from mastery_backend.domain.submission_records import (
    SubmissionDetail,
    SubmissionListQuery,
    SubmissionPage,
)

Learner = Annotated[Principal, Depends(learner)]
Service = Annotated[SubmissionService, Depends(submission_service)]
Key = Annotated[str, Depends(idempotency_key)]
router = APIRouter(
    prefix="/api/v1",
    tags=["submission receipts"],
    responses={
        **content_errors,
        401: {"model": ErrorEnvelope, "description": "Active local identity required"},
        403: {"model": ErrorEnvelope, "description": "Stored learner role required"},
        409: {
            "model": ErrorEnvelope,
            "description": "Stale revision, invalid lifecycle or conflicting retry",
        },
        413: {
            "model": ErrorEnvelope,
            "description": "Source or HTTP body exceeds configured byte limit",
        },
    },
)


@router.post(
    "/attempts/{attempt_id}/submissions",
    response_model=SubmissionDetail,
    status_code=201,
    operation_id="accept_submission",
)
def accept_submission(
    attempt_id: UUID, body: AcceptSubmission, principal: Learner, service: Service, key: Key
) -> JSONResponse:
    return command_response(
        service.accept(
            principal, attempt_id, key, body.source_code, body.purpose, body.expected_revision
        )
    )


@router.get(
    "/submissions/{submission_id}", response_model=SubmissionDetail, operation_id="read_submission"
)
def read_submission(submission_id: UUID, principal: Learner, service: Service) -> SubmissionDetail:
    return service.read(principal, submission_id)


@router.get(
    "/attempts/{attempt_id}/submissions",
    response_model=SubmissionPage,
    operation_id="list_attempt_submissions",
)
def list_attempt_submissions(
    attempt_id: UUID,
    request: Request,
    query: Annotated[SubmissionListQuery, Query()],
    principal: Learner,
    service: Service,
) -> SubmissionPage:
    if query.limit > request.app.state.settings.max_page_size:
        raise ContentError("VALIDATION_ERROR", "The requested page exceeds MAX_PAGE_SIZE.")
    return service.list_submissions(principal, attempt_id, query)
