"""Skill and prerequisite queries; callers own transactions and curriculum locks."""

from uuid import UUID

from sqlalchemy import delete, or_, select, tuple_
from sqlalchemy.orm import Session

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.skill_records import EdgeRecord, GraphQuery, SkillListQuery, SkillRecord
from mastery_backend.infrastructure.database.content_models import (
    Curriculum,
    Question,
    QuestionVersion,
    QuestionVersionSkill,
    Skill,
    SkillPrerequisite,
)


class SkillRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def curriculum(self, curriculum_id: UUID, *, write: bool) -> Curriculum:
        curriculum = self.session.scalar(
            select(Curriculum).where(Curriculum.id == curriculum_id).with_for_update(read=not write)
        )
        if curriculum is None:
            raise ContentError("NOT_FOUND", "Curriculum does not exist.")
        return curriculum

    def skill(self, skill_id: UUID, *, lock: bool = False) -> Skill:
        query = select(Skill).where(Skill.id == skill_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        skill = self.session.scalar(query)
        if skill is None:
            raise ContentError("NOT_FOUND", "Skill does not exist.")
        return skill

    def graph(self, curriculum_id: UUID) -> tuple[dict[UUID, str], list[tuple[UUID, UUID]]]:
        codes = {
            identifier: code
            for identifier, code in self.session.execute(
                select(Skill.id, Skill.code).where(Skill.curriculum_id == curriculum_id)
            )
        }
        edges = [
            (prerequisite, dependent)
            for prerequisite, dependent in self.session.execute(
                select(
                    SkillPrerequisite.prerequisite_skill_id, SkillPrerequisite.dependent_skill_id
                ).where(SkillPrerequisite.curriculum_id == curriculum_id)
            )
        ]
        return codes, edges

    def page(self, query: SkillListQuery, after: tuple[str, UUID] | None) -> list[SkillRecord]:
        statement = select(Skill).order_by(Skill.code, Skill.id).limit(query.limit + 1)
        if query.curriculum_id:
            statement = statement.where(Skill.curriculum_id == query.curriculum_id)
        if not query.include_archived:
            statement = statement.where(Skill.archived_at.is_(None))
        if after:
            statement = statement.where(tuple_(Skill.code, Skill.id) > after)
        return [SkillRecord.model_validate(row) for row in self.session.scalars(statement)]

    def active_skills(self, identifiers: set[UUID], curriculum_id: UUID) -> None:
        found = set(
            self.session.scalars(
                select(Skill.id).where(
                    Skill.id.in_(identifiers),
                    Skill.curriculum_id == curriculum_id,
                    Skill.archived_at.is_(None),
                )
            )
        )
        if found != identifiers:
            raise ContentError(
                "INVALID_SKILL",
                "Every prerequisite must exist, be active and belong to this curriculum.",
            )

    def incoming(self, dependent_id: UUID) -> list[UUID]:
        return list(
            self.session.scalars(
                select(SkillPrerequisite.prerequisite_skill_id)
                .where(SkillPrerequisite.dependent_skill_id == dependent_id)
                .order_by(SkillPrerequisite.prerequisite_skill_id)
            )
        )

    def replace_incoming(self, dependent: Skill, prerequisites: list[UUID]) -> None:
        self.session.execute(
            delete(SkillPrerequisite).where(SkillPrerequisite.dependent_skill_id == dependent.id)
        )
        self.session.add_all(
            [
                SkillPrerequisite(
                    prerequisite_skill_id=identifier,
                    dependent_skill_id=dependent.id,
                    curriculum_id=dependent.curriculum_id,
                )
                for identifier in prerequisites
            ]
        )

    def has_incident_edges(self, skill_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(SkillPrerequisite.prerequisite_skill_id)
                .where(
                    or_(
                        SkillPrerequisite.prerequisite_skill_id == skill_id,
                        SkillPrerequisite.dependent_skill_id == skill_id,
                    )
                )
                .limit(1)
            )
            is not None
        )

    def has_available_question_mappings(self, skill_id: UUID) -> bool:
        return (
            self.session.scalar(
                select(QuestionVersionSkill.version_id)
                .join(QuestionVersion, QuestionVersion.id == QuestionVersionSkill.version_id)
                .join(Question, Question.id == QuestionVersion.question_id)
                .where(QuestionVersionSkill.skill_id == skill_id, Question.archived_at.is_(None))
                .limit(1)
            )
            is not None
        )

    def bounded_graph(self, query: GraphQuery) -> tuple[list[SkillRecord], list[EdgeRecord]]:
        identifiers: set[UUID] | None = None
        if query.center_skill_id is not None:
            center = self.skill(query.center_skill_id)
            if center.curriculum_id != query.curriculum_id or center.archived_at is not None:
                raise ContentError(
                    "NOT_FOUND", "The center skill is not active in this curriculum."
                )
            identifiers = {center.id}
            frontier = identifiers.copy()
            traversed: set[tuple[UUID, UUID]] = set()
            for _ in range(query.depth):
                conditions = []
                if query.direction in {"both", "prerequisites"}:
                    conditions.append(SkillPrerequisite.dependent_skill_id.in_(frontier))
                if query.direction in {"both", "dependents"}:
                    conditions.append(SkillPrerequisite.prerequisite_skill_id.in_(frontier))
                rows = self.session.execute(
                    select(
                        SkillPrerequisite.prerequisite_skill_id,
                        SkillPrerequisite.dependent_skill_id,
                    )
                    .where(SkillPrerequisite.curriculum_id == query.curriculum_id, or_(*conditions))
                    .limit(query.max_edges + 1)
                ).all()
                traversed.update((prerequisite, dependent) for prerequisite, dependent in rows)
                neighbors = {identifier for row in rows for identifier in row}
                frontier = neighbors - identifiers
                identifiers.update(neighbors)
                self.check_bounds(len(identifiers), len(traversed), query)
                if not frontier:
                    break
        nodes_query = (
            select(Skill)
            .where(Skill.curriculum_id == query.curriculum_id, Skill.archived_at.is_(None))
            .order_by(Skill.code, Skill.id)
            .limit(query.max_nodes + 1)
        )
        if identifiers is not None:
            nodes_query = nodes_query.where(Skill.id.in_(identifiers))
        nodes = list(self.session.scalars(nodes_query))
        identifiers = {node.id for node in nodes}
        rows = self.session.execute(
            select(SkillPrerequisite.prerequisite_skill_id, SkillPrerequisite.dependent_skill_id)
            .where(
                SkillPrerequisite.curriculum_id == query.curriculum_id,
                SkillPrerequisite.prerequisite_skill_id.in_(identifiers),
                SkillPrerequisite.dependent_skill_id.in_(identifiers),
            )
            .order_by(SkillPrerequisite.prerequisite_skill_id, SkillPrerequisite.dependent_skill_id)
            .limit(query.max_edges + 1)
        ).all()
        self.check_bounds(len(nodes), len(rows), query)
        return (
            [SkillRecord.model_validate(node) for node in nodes],
            [
                EdgeRecord(prerequisite_skill_id=prerequisite, dependent_skill_id=dependent)
                for prerequisite, dependent in rows
            ],
        )

    @staticmethod
    def check_bounds(nodes: int, edges: int, query: GraphQuery) -> None:
        if nodes > query.max_nodes or edges > query.max_edges:
            raise ContentError(
                "GRAPH_READ_LIMIT",
                "Graph exceeds requested bounds; use a smaller neighborhood or larger bounds.",
            )
