"""Assistance inputs accept intent and revision, never trusted elapsed time."""

from typing import Literal

from pydantic import Field

from mastery_backend.api.schemas.attempts import AttemptRevision


class NextAssistance(AttemptRevision):
    trigger: Literal["budget_expired", "learner_request"]


class SolutionEscape(AttemptRevision):
    confirmation: bool = Field(strict=True)
