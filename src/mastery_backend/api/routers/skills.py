"""Thin skill HTTP routes; application services own graph locks and transactions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.responses import JSONResponse

from mastery_backend.api.admin_responses import command_response, content_errors
from mastery_backend.api.dependencies import content_administrator, idempotency_key, skill_service
from mastery_backend.api.errors import ErrorEnvelope
from mastery_backend.api.schemas.skills import (
    AddPrerequisite,
    ArchiveSkill,
    GraphMutationRecord,
    PatchSkill,
    ReplacePrerequisites,
)
from mastery_backend.application.skill_service import SkillService
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal
from mastery_backend.domain.skill_records import (
    CreateSkill,
    GraphQuery,
    GraphRecord,
    SkillListQuery,
    SkillPage,
    SkillRecord,
)

Admin = Annotated[Principal, Depends(content_administrator)]
Service = Annotated[SkillService, Depends(skill_service)]
Key = Annotated[str, Depends(idempotency_key)]
router = APIRouter(prefix="/api/v1", tags=["skills"], responses=content_errors)
admin_router = APIRouter(
    prefix="/api/v1/admin",
    tags=["skill administration"],
    responses={
        **content_errors,
        401: {"model": ErrorEnvelope, "description": "Configured local identity unavailable"},
        403: {"model": ErrorEnvelope, "description": "Stored content_admin role required"},
        409: {
            "model": ErrorEnvelope,
            "description": "Stale revision, duplicate, cycle or archival conflict",
        },
    },
)


@router.get("/skills/graph", response_model=GraphRecord, operation_id="read_skill_graph")
def read_skill_graph(query: Annotated[GraphQuery, Query()], service: Service) -> GraphRecord:
    return service.graph(query)


@router.get("/skills", response_model=SkillPage, operation_id="list_skills")
def list_skills(
    request: Request, query: Annotated[SkillListQuery, Query()], service: Service
) -> SkillPage:
    if query.limit > request.app.state.settings.max_page_size:
        raise ContentError("VALIDATION_ERROR", "The requested page exceeds MAX_PAGE_SIZE.")
    return service.list_skills(query)


@router.get("/skills/{skill_id}", response_model=SkillRecord, operation_id="read_skill")
def read_skill(skill_id: UUID, service: Service) -> SkillRecord:
    return service.read(skill_id)


@admin_router.post(
    "/skills", response_model=SkillRecord, status_code=201, operation_id="create_skill"
)
def create_skill(body: CreateSkill, principal: Admin, service: Service, key: Key) -> JSONResponse:
    return command_response(service.create(principal, key, body))


@admin_router.patch("/skills/{skill_id}", response_model=SkillRecord, operation_id="edit_skill")
def edit_skill(skill_id: UUID, body: PatchSkill, principal: Admin, service: Service) -> SkillRecord:
    return service.patch(
        principal,
        skill_id,
        body.expected_revision,
        body.model_dump(exclude_unset=True, exclude={"expected_revision"}),
    )


@admin_router.post(
    "/skills/{skill_id}/archive", response_model=SkillRecord, operation_id="archive_skill"
)
def archive_skill(
    skill_id: UUID, body: ArchiveSkill, principal: Admin, service: Service, key: Key
) -> JSONResponse:
    return command_response(
        service.archive(
            principal, key, skill_id, body.expected_revision, body.expected_graph_revision
        )
    )


@admin_router.post(
    "/skills/{dependent_id}/prerequisites",
    response_model=GraphMutationRecord,
    status_code=201,
    operation_id="add_skill_prerequisite",
)
def add_skill_prerequisite(
    dependent_id: UUID, body: AddPrerequisite, principal: Admin, service: Service, key: Key
) -> JSONResponse:
    return command_response(
        service.change_prerequisites(
            principal,
            dependent_id,
            [body.prerequisite_skill_id],
            body.expected_graph_revision,
            "add",
            key,
        )
    )


@admin_router.put(
    "/skills/{dependent_id}/prerequisites",
    response_model=GraphMutationRecord,
    operation_id="replace_skill_prerequisites",
)
def replace_skill_prerequisites(
    dependent_id: UUID, body: ReplacePrerequisites, principal: Admin, service: Service
) -> JSONResponse:
    return command_response(
        service.change_prerequisites(
            principal,
            dependent_id,
            body.prerequisite_skill_ids,
            body.expected_graph_revision,
            "replace",
        )
    )


@admin_router.delete(
    "/skills/{dependent_id}/prerequisites/{prerequisite_id}",
    status_code=204,
    operation_id="remove_skill_prerequisite",
)
def remove_skill_prerequisite(
    dependent_id: UUID,
    prerequisite_id: UUID,
    principal: Admin,
    service: Service,
    expected_graph_revision: Annotated[int, Query(ge=0)],
) -> Response:
    service.change_prerequisites(
        principal, dependent_id, [prerequisite_id], expected_graph_revision, "remove"
    )
    return Response(status_code=204)
