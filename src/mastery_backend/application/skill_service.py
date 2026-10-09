"""Skill use cases serialize curriculum changes and validate before committing."""

import base64
import binascii
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.admin_commands import AdminCommands, CommandResult
from mastery_backend.domain.content import ContentError, ContentValue
from mastery_backend.domain.identity import Principal
from mastery_backend.domain.skill_graph import validate_acyclic_graph
from mastery_backend.domain.skill_records import (
    CreateSkill,
    GraphQuery,
    GraphRecord,
    SkillContent,
    SkillListQuery,
    SkillPage,
    SkillRecord,
)
from mastery_backend.infrastructure.database.content_models import Skill
from mastery_backend.infrastructure.database.skill_repository import SkillRepository


class SkillCursor(ContentValue):
    code: str
    skill_id: UUID
    expires_at: datetime
    filter_hash: str


class SkillService:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory
        self.commands = AdminCommands(factory)

    @staticmethod
    def check_revision(actual: int, expected: int) -> None:
        if actual != expected:
            raise ContentError(
                "STALE_REVISION", "Skill or graph changed; reload its revision before retrying."
            )

    def create(self, principal: Principal, key: str, body: CreateSkill) -> CommandResult:
        def action(session: Session) -> CommandResult:
            curriculum = SkillRepository(session).curriculum(body.curriculum_id, write=True)
            skill = Skill(**body.model_dump())
            session.add(skill)
            curriculum.graph_revision += 1
            session.flush()
            record = SkillRecord.model_validate(skill)
            return CommandResult(record.model_dump(mode="json"), 201, f"/api/v1/skills/{skill.id}")

        return self.commands.run(
            principal, "POST /api/v1/admin/skills", key, body.model_dump(mode="json"), action
        )

    def read(self, skill_id: UUID) -> SkillRecord:
        with self.factory.begin() as session:
            # Detail preserves archived identity; catalogs hide it unless requested.
            return SkillRecord.model_validate(SkillRepository(session).skill(skill_id))

    def patch(
        self, principal: Principal, skill_id: UUID, expected_revision: int, changes: dict[str, Any]
    ) -> SkillRecord:
        try:
            with self.factory.begin() as session:
                self.commands.authorize(session, principal)
                repository = SkillRepository(session)
                curriculum_id = repository.skill(skill_id).curriculum_id
                curriculum = repository.curriculum(curriculum_id, write=True)
                skill = repository.skill(skill_id, lock=True)
                self.check_revision(skill.revision, expected_revision)
                self.check_active(skill)
                content = SkillContent.model_validate(
                    {"title": skill.title, "competency": skill.competency, **changes}
                )
                skill.title, skill.competency = content.title, content.competency
                skill.revision += 1
                curriculum.graph_revision += 1
                session.flush()
                return SkillRecord.model_validate(skill)
        except IntegrityError:
            raise ContentError(
                "CONTENT_CONFLICT", "Skill conflicts with a database constraint."
            ) from None

    @staticmethod
    def check_active(skill: Skill) -> None:
        if skill.archived_at is not None:
            raise ContentError("SKILL_ARCHIVED", "Archived skills cannot be edited or linked.")

    def archive(
        self,
        principal: Principal,
        key: str,
        skill_id: UUID,
        expected_revision: int,
        expected_graph_revision: int,
    ) -> CommandResult:
        def action(session: Session) -> CommandResult:
            repository = SkillRepository(session)
            curriculum_id = repository.skill(skill_id).curriculum_id
            curriculum = repository.curriculum(curriculum_id, write=True)
            skill = repository.skill(skill_id, lock=True)
            self.check_revision(curriculum.graph_revision, expected_graph_revision)
            self.check_revision(skill.revision, expected_revision)
            self.check_active(skill)
            if repository.has_incident_edges(skill_id):
                raise ContentError(
                    "SKILL_IN_USE",
                    "Remove all incoming and outgoing prerequisite edges before archiving.",
                )
            if repository.has_available_question_mappings(skill_id):
                raise ContentError(
                    "SKILL_IN_USE",
                    "Remove draft mappings or archive their questions before archiving this skill.",
                )
            skill.archived_at = datetime.now(UTC)
            skill.revision += 1
            curriculum.graph_revision += 1
            session.flush()
            return CommandResult(SkillRecord.model_validate(skill).model_dump(mode="json"))

        return self.commands.run(
            principal,
            f"POST /api/v1/admin/skills/{skill_id}/archive",
            key,
            {
                "expected_revision": expected_revision,
                "expected_graph_revision": expected_graph_revision,
            },
            action,
        )

    def change_prerequisites(
        self,
        principal: Principal,
        dependent_id: UUID,
        prerequisites: list[UUID],
        expected_graph_revision: int,
        mode: Literal["add", "replace", "remove"],
        key: str | None = None,
    ) -> CommandResult:
        def action(session: Session) -> CommandResult:
            repository = SkillRepository(session)
            curriculum_id = repository.skill(dependent_id).curriculum_id
            curriculum = repository.curriculum(curriculum_id, write=True)
            dependent = repository.skill(dependent_id, lock=True)
            self.check_revision(curriculum.graph_revision, expected_graph_revision)
            self.check_active(dependent)
            incoming = repository.incoming(dependent_id)
            if mode == "add":
                if prerequisites[0] in incoming:
                    raise ContentError(
                        "DUPLICATE_EDGE", "Prerequisite edge already exists; reload the graph."
                    )
                proposed = incoming + prerequisites
            elif mode == "remove":
                if prerequisites[0] not in incoming:
                    raise ContentError("NOT_FOUND", "Prerequisite edge does not exist.")
                proposed = [identifier for identifier in incoming if identifier != prerequisites[0]]
            else:
                proposed = prerequisites
            repository.active_skills(set(proposed) | {dependent_id}, curriculum_id)
            codes, edges = repository.graph(curriculum_id)
            resulting = [(start, end) for start, end in edges if end != dependent_id]
            resulting.extend((start, dependent_id) for start in proposed)
            validate_acyclic_graph(codes, resulting)
            if set(proposed) != set(incoming):
                repository.replace_incoming(dependent, proposed)
                curriculum.graph_revision += 1
            session.flush()
            return CommandResult(
                {
                    "curriculum_id": str(curriculum_id),
                    "graph_revision": curriculum.graph_revision,
                    "dependent_skill_id": str(dependent_id),
                    "prerequisite_skill_ids": sorted(str(identifier) for identifier in proposed),
                },
                201 if mode == "add" else 200,
                f"/api/v1/admin/skills/{dependent_id}/prerequisites/{prerequisites[0]}"
                if mode == "add"
                else None,
            )

        if mode == "add":
            assert key is not None
            return self.commands.run(
                principal,
                f"POST /api/v1/admin/skills/{dependent_id}/prerequisites",
                key,
                {
                    "prerequisite_skill_id": str(prerequisites[0]),
                    "expected_graph_revision": expected_graph_revision,
                },
                action,
            )
        with self.factory.begin() as session:
            self.commands.authorize(session, principal)
            return action(session)

    def graph(self, query: GraphQuery) -> GraphRecord:
        with self.factory.begin() as session:
            repository = SkillRepository(session)
            curriculum = repository.curriculum(query.curriculum_id, write=False)
            nodes, edges = repository.bounded_graph(query)
            return GraphRecord(
                curriculum_id=curriculum.id,
                graph_revision=curriculum.graph_revision,
                nodes=nodes,
                edges=edges,
            )

    def list_skills(self, query: SkillListQuery) -> SkillPage:
        digest = self.commands.request_hash(
            query.model_dump(mode="json", exclude={"cursor", "limit"})
        )
        cursor = None
        if query.cursor:
            try:
                cursor = SkillCursor.model_validate_json(
                    base64.b64decode(query.cursor, altchars=b"-_", validate=True)
                )
                if (
                    cursor.expires_at.tzinfo is None
                    or cursor.expires_at <= datetime.now(UTC)
                    or cursor.filter_hash != digest
                ):
                    raise ValueError("invalid cursor")
            except (ValueError, binascii.Error):
                raise ContentError(
                    "INVALID_CURSOR", "Skill cursor is invalid or expired."
                ) from None
        with self.factory.begin() as session:
            after = (cursor.code, cursor.skill_id) if cursor else None
            rows = SkillRepository(session).page(query, after)
            next_cursor = None
            if len(rows) > query.limit:
                last = rows[query.limit - 1]
                next_cursor = base64.urlsafe_b64encode(
                    SkillCursor(
                        code=last.code,
                        skill_id=last.id,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                        filter_hash=digest,
                    )
                    .model_dump_json()
                    .encode()
                ).decode()
            return SkillPage(
                items=rows[: query.limit],
                next_cursor=next_cursor,
            )
