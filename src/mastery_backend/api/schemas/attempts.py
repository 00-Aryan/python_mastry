"""Learner command allowlists reject caller ownership, clocks and success claims."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from mastery_backend.domain.content import ContentValue


class StartAttempt(ContentValue):
    question_version_id: UUID
    mode: Literal["practice", "assessment"]
    independent_budget_seconds: int = Field(strict=True, gt=0, le=86400)


class AttemptRevision(ContentValue):
    expected_revision: int = Field(strict=True, gt=0)


class EndAttempt(AttemptRevision):
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class ExtendAttempt(EndAttempt):
    additional_budget_seconds: int = Field(strict=True, gt=0, le=86400)
