"""Explicit HTTP allowlists; public payloads never inherit private authoring fields."""

from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from mastery_backend.domain.content import (
    AssistanceStep,
    Code,
    ContentValue,
    Difficulty,
    DraftContent,
    Example,
    FunctionContract,
    IncorrectSolution,
    Mode,
    RevisionLink,
    SkillMapping,
    Solution,
    TestCase,
)


class CreateQuestion(ContentValue):
    code: Code
    family_id: UUID
    draft: DraftContent


class ExpectedRevision(ContentValue):
    expected_revision: int = Field(gt=0)


class PatchDraft(ExpectedRevision):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    statement: Annotated[str, Field(min_length=1, max_length=65536)] | None = None
    track: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    difficulty: Difficulty | None = None
    assessment_role: Mode | None = None
    supported_modes: list[Mode] | None = None
    suggested_budget_seconds: int | None = Field(default=None, gt=0, le=86400)
    contract: FunctionContract | None = None
    skill_mappings: list[SkillMapping] | None = None
    pattern_ids: list[UUID] | None = None
    examples: list[Example] | None = None
    test_cases: list[TestCase] | None = None
    assistance_steps: list[AssistanceStep] | None = None
    solution: Solution | None = None
    revision_links: list[RevisionLink] | None = None
    incorrect_solutions: list[IncorrectSolution] | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def validate_patch(self) -> "PatchDraft":
        fields = self.model_fields_set - {"expected_revision"}
        if not fields:
            raise ValueError("Supply at least one editable field")
        if any(getattr(self, field) is None for field in fields - {"contract", "solution"}):
            raise ValueError("Only contract and solution accept null")
        return self
