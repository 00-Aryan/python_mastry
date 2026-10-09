"""Content queries and flushes. The application owns all commits and rollbacks."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mastery_backend.domain.content import ContentError, DraftContent
from mastery_backend.infrastructure.database import content_models as models


class ContentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def question(self, question_id: UUID, *, lock: bool = False) -> models.Question:
        query = select(models.Question).where(models.Question.id == question_id)
        if lock:
            query = query.with_for_update()
        question = self.session.scalar(query)
        if question is None:
            raise ContentError("NOT_FOUND", "Question not found.")
        return question

    def version(self, version_id: UUID, *, lock: bool = False) -> models.QuestionVersion:
        # Every mutation locks question first, then version (including publication).
        question_id = self.session.scalar(
            select(models.QuestionVersion.question_id).where(
                models.QuestionVersion.id == version_id
            )
        )
        if question_id is None:
            raise ContentError("NOT_FOUND", "Question version not found.")
        self.question(question_id, lock=lock)
        query = select(models.QuestionVersion).where(models.QuestionVersion.id == version_id)
        if lock:
            query = query.with_for_update()
        version = self.session.scalar(query)
        if version is None:
            raise ContentError("NOT_FOUND", "Question version not found.")
        return version

    def validate_references(self, content: DraftContent, version_id: UUID | None = None) -> None:
        skill_ids = {mapping.skill_id for mapping in content.skill_mappings}
        if skill_ids:
            found = set(
                self.session.scalars(
                    select(models.Skill.id).where(
                        models.Skill.id.in_(skill_ids), models.Skill.archived_at.is_(None)
                    )
                )
            )
            if found != skill_ids:
                raise ContentError("INVALID_SKILL", "A skill is missing or archived.")
        if content.pattern_ids:
            found = set(
                self.session.scalars(
                    select(models.Pattern.id).where(models.Pattern.id.in_(content.pattern_ids))
                )
            )
            if found != set(content.pattern_ids):
                raise ContentError("INVALID_PATTERN", "A pattern is missing.")
        for link in content.revision_links:
            target = self.session.execute(
                select(models.QuestionVersion.status, models.Question.archived_at)
                .join(models.Question)
                .where(models.QuestionVersion.id == link.target_version_id)
            ).first()
            if (
                link.target_version_id == version_id
                or target is None
                or (target.status != "published" or target.archived_at is not None)
            ):
                raise ContentError(
                    "INVALID_LINK", "Links require another available published version."
                )

    def next_version(
        self, question: models.Question, content: DraftContent
    ) -> models.QuestionVersion:
        question.last_version_number += 1
        version = models.QuestionVersion(
            question_id=question.id, version_number=question.last_version_number
        )
        self.replace_content(version, content)
        self.session.add(version)
        self.session.flush()
        return version

    def replace_content(self, version: models.QuestionVersion, content: DraftContent) -> None:
        # Delete existing children before replacement to avoid transient unique conflicts.
        if version.id is not None:
            for collection in (
                "modes",
                "skills",
                "patterns",
                "examples",
                "test_cases",
                "assistance_steps",
                "links",
            ):
                getattr(version, collection).clear()
            version.solution = None
            self.session.flush()
        version.title = content.title
        version.statement = content.statement
        version.track = content.track
        version.difficulty = content.difficulty
        version.assessment_role = content.assessment_role
        version.suggested_budget_seconds = content.suggested_budget_seconds
        version.contract_json = (
            content.contract.model_dump(mode="json") if content.contract else None
        )
        version.modes = [models.QuestionVersionMode(mode=mode) for mode in content.supported_modes]
        version.skills = [
            models.QuestionVersionSkill(
                skill_id=mapping.skill_id,
                attribution_role=mapping.attribution_role,
                rubric_json=mapping.rubric,
            )
            for mapping in content.skill_mappings
        ]
        version.patterns = [
            models.QuestionVersionPattern(pattern_id=identifier)
            for identifier in content.pattern_ids
        ]
        version.examples = [
            models.QuestionExample(
                position=example.position,
                input_json=example.input,
                output_json=example.expected_output,
                explanation=example.explanation,
            )
            for example in content.examples
        ]
        version.test_cases = [
            models.QuestionTestCase(
                position=test.position,
                visibility=test.visibility,
                input_json=test.input,
                expected_json=test.expected_output,
                assertion_rule=test.assertion_rule,
                critical=test.critical,
            )
            for test in content.test_cases
        ]
        version.assistance_steps = [
            models.QuestionAssistanceStep(**step.model_dump()) for step in content.assistance_steps
        ]
        version.solution = (
            models.QuestionSolution(**content.solution.model_dump()) if content.solution else None
        )
        version.links = [
            models.QuestionLink(**link.model_dump()) for link in content.revision_links
        ]

    def content(self, version: models.QuestionVersion) -> DraftContent:
        values: dict[str, Any] = {
            "title": version.title,
            "statement": version.statement,
            "track": version.track,
            "difficulty": version.difficulty,
            "assessment_role": version.assessment_role,
            "suggested_budget_seconds": version.suggested_budget_seconds,
            "contract": version.contract_json,
            "supported_modes": sorted(mode.mode for mode in version.modes),
            "skill_mappings": [
                {
                    "skill_id": mapping.skill_id,
                    "attribution_role": mapping.attribution_role,
                    "rubric": mapping.rubric_json,
                }
                for mapping in sorted(version.skills, key=lambda value: value.skill_id)
            ],
            "pattern_ids": sorted(mapping.pattern_id for mapping in version.patterns),
            "examples": [
                {
                    "position": example.position,
                    "input": example.input_json,
                    "expected_output": example.output_json,
                    "explanation": example.explanation,
                }
                for example in sorted(version.examples, key=lambda value: value.position)
            ],
            "test_cases": [
                {
                    "position": test.position,
                    "input": test.input_json,
                    "expected_output": test.expected_json,
                    "visibility": test.visibility,
                    "assertion_rule": test.assertion_rule,
                    "critical": test.critical,
                }
                for test in sorted(version.test_cases, key=lambda value: value.position)
            ],
            "assistance_steps": [
                {
                    "position": step.position,
                    "kind": step.kind,
                    "content": step.content,
                    "next_budget_seconds": step.next_budget_seconds,
                }
                for step in sorted(version.assistance_steps, key=lambda value: value.position)
            ],
            "solution": {
                "reference_code": version.solution.reference_code,
                "explanation": version.solution.explanation,
                "expected_complexity": version.solution.expected_complexity,
            }
            if version.solution
            else None,
            "revision_links": [
                {"target_version_id": link.target_version_id, "link_type": link.link_type}
                for link in sorted(
                    version.links, key=lambda value: (value.target_version_id, value.link_type)
                )
            ],
        }
        return DraftContent.model_validate(values)

    def delete_draft(self, version: models.QuestionVersion) -> None:
        referenced = self.session.scalar(
            select(func.count())
            .select_from(models.QuestionLink)
            .where(models.QuestionLink.target_version_id == version.id)
        )
        if referenced:
            raise ContentError("VERSION_REFERENCED", "Referenced versions cannot be deleted.")
        self.session.delete(version)
        self.session.flush()
