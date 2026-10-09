"""Learner queries project public columns only; never load private ORM relationships."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.content_records import PublicQuestionVersion, QuestionListQuery
from mastery_backend.infrastructure.database import content_models as models


class CatalogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def public_version(
        self, version_id: UUID, *, include_archived: bool = False
    ) -> PublicQuestionVersion:
        return self.public_versions([version_id], include_archived=include_archived)[0]

    def public_versions(
        self, version_ids: list[UUID], *, include_archived: bool = False
    ) -> list[PublicQuestionVersion]:
        if not version_ids:
            return []
        statement = (
            select(
                models.QuestionVersion.id,
                models.QuestionVersion.question_id,
                models.Question.code,
                models.QuestionVersion.version_number,
                models.QuestionVersion.title,
                models.QuestionVersion.statement,
                models.QuestionVersion.track,
                models.QuestionVersion.difficulty,
                models.QuestionVersion.suggested_budget_seconds,
                models.QuestionVersion.contract_json,
            )
            .join(models.Question)
            .where(
                models.QuestionVersion.id.in_(version_ids),
                models.QuestionVersion.status == "published",
            )
        )
        if not include_archived:
            statement = statement.where(models.Question.archived_at.is_(None))
        rows = self.session.execute(statement).mappings()
        by_id: dict[UUID, dict[str, Any]] = {}
        for row in rows:
            fields = dict(row)
            fields["contract"] = fields.pop("contract_json")
            fields.update(supported_modes=[], skill_ids=[], pattern_ids=[], examples=[])
            by_id[row["id"]] = fields
        if len(by_id) != len(set(version_ids)):
            raise ContentError("NOT_FOUND", "Available published question not found.")
        modes = self.session.execute(
            select(models.QuestionVersionMode.version_id, models.QuestionVersionMode.mode)
            .where(models.QuestionVersionMode.version_id.in_(version_ids))
            .order_by(models.QuestionVersionMode.mode)
        )
        for version_id, mode in modes:
            by_id[version_id]["supported_modes"].append(mode)
        skills = self.session.execute(
            select(models.QuestionVersionSkill.version_id, models.QuestionVersionSkill.skill_id)
            .where(models.QuestionVersionSkill.version_id.in_(version_ids))
            .order_by(models.QuestionVersionSkill.skill_id)
        )
        for version_id, skill_id in skills:
            by_id[version_id]["skill_ids"].append(skill_id)
        patterns = self.session.execute(
            select(
                models.QuestionVersionPattern.version_id, models.QuestionVersionPattern.pattern_id
            )
            .where(models.QuestionVersionPattern.version_id.in_(version_ids))
            .order_by(models.QuestionVersionPattern.pattern_id)
        )
        for version_id, pattern_id in patterns:
            by_id[version_id]["pattern_ids"].append(pattern_id)
        examples = self.session.scalars(
            select(models.QuestionExample)
            .where(models.QuestionExample.version_id.in_(version_ids))
            .order_by(models.QuestionExample.position)
        )
        for example in examples:
            by_id[example.version_id]["examples"].append(
                {
                    "position": example.position,
                    "input": example.input_json,
                    "expected_output": example.output_json,
                    "explanation": example.explanation,
                }
            )
        return [
            PublicQuestionVersion.model_validate(by_id[version_id]) for version_id in version_ids
        ]

    def current_version_id(self, question_id: UUID) -> UUID:
        identifier = self.session.scalar(
            select(models.QuestionVersion.id)
            .join(models.Question)
            .where(
                models.Question.id == question_id,
                models.Question.archived_at.is_(None),
                models.QuestionVersion.status == "published",
            )
            .order_by(models.QuestionVersion.version_number.desc())
            .limit(1)
        )
        if identifier is None:
            raise ContentError("NOT_FOUND", "Available published question not found.")
        return identifier

    def page_ids(
        self, query: QuestionListQuery, after: tuple[datetime, UUID] | None
    ) -> list[tuple[UUID, datetime, UUID]]:
        latest = (
            select(
                models.QuestionVersion.question_id,
                func.max(models.QuestionVersion.version_number).label("number"),
            )
            .where(models.QuestionVersion.status == "published")
            .group_by(models.QuestionVersion.question_id)
            .subquery()
        )
        statement = (
            select(models.QuestionVersion.id, models.Question.created_at, models.Question.id)
            .join(models.Question)
            .join(
                latest,
                and_(
                    latest.c.question_id == models.Question.id,
                    latest.c.number == models.QuestionVersion.version_number,
                ),
            )
            .where(models.Question.archived_at.is_(None))
        )
        if query.difficulty is not None:
            statement = statement.where(models.QuestionVersion.difficulty == query.difficulty)
        if query.track is not None:
            statement = statement.where(models.QuestionVersion.track == query.track)
        if query.skill_id is not None or query.curriculum_id is not None:
            skill_query = (
                select(models.QuestionVersionSkill.version_id)
                .join(models.Skill)
                .where(models.QuestionVersionSkill.version_id == models.QuestionVersion.id)
            )
            if query.skill_id is not None:
                skill_query = skill_query.where(models.Skill.id == query.skill_id)
            if query.curriculum_id is not None:
                skill_query = skill_query.where(models.Skill.curriculum_id == query.curriculum_id)
            statement = statement.where(skill_query.exists())
        if after is not None:
            created_at, question_id = after
            statement = statement.where(
                or_(
                    models.Question.created_at > created_at,
                    and_(
                        models.Question.created_at == created_at, models.Question.id > question_id
                    ),
                )
            )
        rows = self.session.execute(
            statement.order_by(models.Question.created_at, models.Question.id).limit(
                query.limit + 1
            )
        )
        return [(row[0], row[1], row[2]) for row in rows]
