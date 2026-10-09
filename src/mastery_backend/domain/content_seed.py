"""Explicit authoring reference inputs, without graphs or generated learning content."""

from uuid import UUID

from pydantic import Field

from mastery_backend.domain.content import Code, ContentValue, NonEmptyText


class CurriculumSeed(ContentValue):
    id: UUID
    code: Code
    title: str = Field(min_length=1, max_length=200)


class SkillSeed(CurriculumSeed):
    curriculum_id: UUID
    competency: NonEmptyText


class PatternSeed(CurriculumSeed):
    pass


class QuestionFamilySeed(ContentValue):
    id: UUID
    code: Code
    novelty_definition: NonEmptyText


class ReferenceCatalogSeed(ContentValue):
    curricula: list[CurriculumSeed] = Field(default_factory=list, max_length=100)
    skills: list[SkillSeed] = Field(default_factory=list, max_length=100)
    patterns: list[PatternSeed] = Field(default_factory=list, max_length=100)
    question_families: list[QuestionFamilySeed] = Field(default_factory=list, max_length=100)
