"""Skill edits and prerequisite replacement have explicit revision preconditions."""

from uuid import UUID

from pydantic import Field, model_validator

from mastery_backend.domain.content import ContentValue
from mastery_backend.domain.skill_records import Competency, SkillTitle


class PatchSkill(ContentValue):
    expected_revision: int = Field(gt=0)
    title: SkillTitle | None = None
    competency: Competency | None = None

    @model_validator(mode="after")
    def editable_fields(self) -> "PatchSkill":
        fields = self.model_fields_set - {"expected_revision"}
        if not fields or any(getattr(self, field) is None for field in fields):
            raise ValueError("Supply a non-null title or competency")
        return self


class AddPrerequisite(ContentValue):
    prerequisite_skill_id: UUID
    expected_graph_revision: int = Field(ge=0)


class ReplacePrerequisites(ContentValue):
    prerequisite_skill_ids: list[UUID] = Field(max_length=100)
    expected_graph_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def unique_prerequisites(self) -> "ReplacePrerequisites":
        if len(set(self.prerequisite_skill_ids)) != len(self.prerequisite_skill_ids):
            raise ValueError("Supply each prerequisite only once")
        return self


class ArchiveSkill(ContentValue):
    expected_revision: int = Field(gt=0)
    expected_graph_revision: int = Field(ge=0)


class GraphMutationRecord(ContentValue):
    curriculum_id: UUID
    graph_revision: int
    dependent_skill_id: UUID
    prerequisite_skill_ids: list[UUID]
