"""Owned receipt projections distinguish accepted source from future evaluation."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from mastery_backend.domain.attempt_records import AttemptSnapshot
from mastery_backend.domain.content import ContentValue
from mastery_backend.domain.submissions import SubmissionPurpose


class SubmissionEvidence(ContentValue):
    attempt: AttemptSnapshot
    phase_id: UUID
    assistance_grant_ids: list[UUID]


class SubmissionSummary(ContentValue):
    id: UUID
    attempt_id: UUID
    question_version_id: UUID
    policy_version_id: UUID
    purpose: SubmissionPurpose
    status: Literal["received"] = "received"
    evaluation: Literal["not_requested"] = "not_requested"
    code_hash: str
    source_bytes: int
    accepted_at: datetime
    accepted_event_sequence: int
    attempt_revision: int


class SubmissionDetail(SubmissionSummary):
    source_code: str
    evidence: SubmissionEvidence


class SubmissionListQuery(ContentValue):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)
    purpose: SubmissionPurpose | None = None


class SubmissionPage(ContentValue):
    items: list[SubmissionSummary]
    next_cursor: str | None
