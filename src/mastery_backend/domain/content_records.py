"""Content snapshots and catalog query values shared across adapters."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from mastery_backend.domain.content import (
    ContentValue,
    Difficulty,
    DraftContent,
    Example,
    FunctionContract,
    Mode,
)


class AdminQuestionVersion(DraftContent):
    id: UUID
    question_id: UUID
    code: str
    version_number: int
    revision: int
    question_revision: int
    status: Literal["draft", "published"]
    published_at: datetime | None
    archived_at: datetime | None


class PublicQuestionVersion(ContentValue):
    id: UUID
    question_id: UUID
    code: str
    version_number: int
    title: str
    statement: str
    track: str
    difficulty: Difficulty
    supported_modes: list[Mode]
    suggested_budget_seconds: int
    contract: FunctionContract
    skill_ids: list[UUID]
    pattern_ids: list[UUID]
    examples: list[Example]


class QuestionListQuery(ContentValue):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2000)
    skill_id: UUID | None = None
    difficulty: Difficulty | None = None
    track: str | None = Field(default=None, min_length=1, max_length=64)
    curriculum_id: UUID | None = None


class QuestionPage(ContentValue):
    items: list[PublicQuestionVersion]
    next_cursor: str | None


class QuestionLifecycle(ContentValue):
    id: UUID
    revision: int
    archived_at: datetime | None
