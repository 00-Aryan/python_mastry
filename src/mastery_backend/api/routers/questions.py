"""Thin HTTP translation; content services own use cases and transactions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.responses import JSONResponse

from mastery_backend.api.admin_responses import command_response, content_errors
from mastery_backend.api.dependencies import (
    catalog_service,
    content_administrator,
    content_service,
    idempotency_key,
)
from mastery_backend.api.errors import ErrorEnvelope
from mastery_backend.api.schemas.questions import CreateQuestion, ExpectedRevision, PatchDraft
from mastery_backend.application.catalog_service import CatalogService
from mastery_backend.application.content_service import ContentService
from mastery_backend.domain.content import ContentError, DraftContent
from mastery_backend.domain.content_records import (
    AdminQuestionVersion,
    PublicQuestionVersion,
    QuestionLifecycle,
    QuestionListQuery,
    QuestionPage,
)
from mastery_backend.domain.identity import Principal

Admin = Annotated[Principal, Depends(content_administrator)]
Content = Annotated[ContentService, Depends(content_service)]
Catalog = Annotated[CatalogService, Depends(catalog_service)]
Key = Annotated[str, Depends(idempotency_key)]

admin_router = APIRouter(
    prefix="/api/v1/admin",
    tags=["content administration"],
    responses={
        **content_errors,
        401: {"model": ErrorEnvelope, "description": "Local identity missing or unavailable"},
        403: {
            "model": ErrorEnvelope,
            "description": "Stored admin role or local request guard denied",
        },
        409: {
            "model": ErrorEnvelope,
            "description": "Revision, lifecycle, publication or idempotency conflict",
        },
    },
)
catalog_router = APIRouter(prefix="/api/v1", tags=["questions"], responses=content_errors)


@admin_router.post(
    "/questions",
    response_model=AdminQuestionVersion,
    status_code=201,
    operation_id="create_question",
)
def create_question(
    body: CreateQuestion, principal: Admin, service: Content, key: Key
) -> JSONResponse:
    return command_response(
        service.create_question(principal, key, body.code, body.family_id, body.draft)
    )


@admin_router.post(
    "/questions/{question_id}/versions",
    response_model=AdminQuestionVersion,
    status_code=201,
    operation_id="create_question_version",
)
def create_question_version(
    question_id: UUID, body: DraftContent, principal: Admin, service: Content, key: Key
) -> JSONResponse:
    return command_response(service.create_version(principal, key, question_id, body))


@admin_router.get(
    "/question-versions/{version_id}",
    response_model=AdminQuestionVersion,
    operation_id="read_admin_question_version",
)
def read_admin_question_version(
    version_id: UUID, principal: Admin, service: Content
) -> AdminQuestionVersion:
    return service.read_admin_version(principal, version_id)


@admin_router.patch(
    "/question-versions/{version_id}",
    response_model=AdminQuestionVersion,
    operation_id="edit_question_draft",
)
def edit_question_draft(
    version_id: UUID, body: PatchDraft, principal: Admin, service: Content
) -> AdminQuestionVersion:
    changes = body.model_dump(exclude_unset=True, exclude={"expected_revision"})
    return service.patch_draft(principal, version_id, body.expected_revision, changes)


@admin_router.delete(
    "/question-versions/{version_id}", status_code=204, operation_id="delete_question_draft"
)
def delete_question_draft(
    version_id: UUID,
    principal: Admin,
    service: Content,
    expected_revision: Annotated[int, Query(gt=0)],
) -> Response:
    service.delete_draft(principal, version_id, expected_revision)
    return Response(status_code=204)


@admin_router.post(
    "/question-versions/{version_id}/publish",
    response_model=AdminQuestionVersion,
    operation_id="publish_question_version",
    responses={
        503: {
            "model": ErrorEnvelope,
            "description": "VERIFICATION_UNAVAILABLE until trusted reference verification exists; "
            "draft stays unchanged",
        }
    },
)
def publish_question_version(
    version_id: UUID, body: ExpectedRevision, principal: Admin, service: Content, key: Key
) -> JSONResponse:
    return command_response(
        service.publish_version(principal, key, version_id, body.expected_revision)
    )


@admin_router.post(
    "/questions/{question_id}/archive",
    response_model=QuestionLifecycle,
    operation_id="archive_question",
)
def archive_question(
    question_id: UUID, body: ExpectedRevision, principal: Admin, service: Content, key: Key
) -> JSONResponse:
    return command_response(
        service.archive_question(principal, key, question_id, body.expected_revision)
    )


@catalog_router.get("/questions", response_model=QuestionPage, operation_id="list_questions")
def list_questions(
    request: Request, query: Annotated[QuestionListQuery, Query()], service: Catalog
) -> QuestionPage:
    if query.limit > request.app.state.settings.max_page_size:
        raise ContentError("VALIDATION_ERROR", "The requested page exceeds MAX_PAGE_SIZE.")
    return service.list_questions(query)


@catalog_router.get(
    "/questions/{question_id}", response_model=PublicQuestionVersion, operation_id="read_question"
)
def read_question(question_id: UUID, service: Catalog) -> PublicQuestionVersion:
    return service.read_question(question_id)


@catalog_router.get(
    "/question-versions/{version_id}",
    response_model=PublicQuestionVersion,
    operation_id="read_question_version",
)
def read_question_version(version_id: UUID, service: Catalog) -> PublicQuestionVersion:
    return service.read_version(version_id)
