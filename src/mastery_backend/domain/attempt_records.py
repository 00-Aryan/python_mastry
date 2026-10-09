"""Owned attempt snapshots expose timing and public context, never private assets."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from mastery_backend.domain.content import ContentValue
from mastery_backend.domain.timer_policy import Lifecycle


class AttemptTimer(ContentValue):
    phase_number: int
    phase_started_at: datetime
    budget_seconds: int
    active_elapsed_ms: int
    remaining_ms: int
    server_now: datetime
    running_since: datetime | None
    expired_at: datetime | None


class AttemptSnapshot(ContentValue):
    id: UUID
    question_version_id: UUID
    policy_version_id: UUID
    policy_version: str
    mode: Literal["practice", "assessment"]
    lifecycle_state: Lifecycle
    assistance_level: Literal[
        "none", "directional", "pattern", "pseudocode", "partial_code", "full_solution"
    ]
    assistance_eligible: bool
    revision: int
    started_at: datetime
    finished_at: datetime | None
    independent_interval_ended_at: datetime | None
    independent_end_reason: (
        Literal["expired", "deferred", "abandoned", "assistance_requested"] | None
    )
    timing_accommodated: bool
    family_previously_attempted: bool
    total_active_elapsed_ms: int
    overdue_active_elapsed_ms: int
    timer: AttemptTimer


class AttemptListQuery(ContentValue):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)
    mode: Literal["practice", "assessment"] | None = None
    lifecycle_state: Lifecycle | None = None


class AttemptPage(ContentValue):
    items: list[AttemptSnapshot]
    next_cursor: str | None
