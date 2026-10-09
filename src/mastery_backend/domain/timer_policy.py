"""Pure phase timer projection, pinned duration bounds and persistent expiry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field

from mastery_backend.domain.content import ContentError, ContentValue

Lifecycle = Literal["active", "paused", "completed", "deferred", "abandoned"]
AttemptCommand = Literal["pause", "resume", "extend", "defer", "abandon"]
PILOT_TIMER_POLICY_CODE = "pilot-assistance-1"


class AssistancePolicy(ContentValue):
    minimum_wait_seconds: int = Field(gt=0)
    maximum_wait_seconds: int = Field(gt=0)


class TimerPolicy(ContentValue):
    minimum_budget_seconds: int = Field(gt=0)
    maximum_budget_seconds: int = Field(gt=0)
    maximum_extension_seconds: int = Field(gt=0)
    allowed_modes: list[Literal["practice", "assessment"]]

    assistance: AssistancePolicy | None = None

    def validate_budget(self, seconds: int) -> None:
        if not self.minimum_budget_seconds <= seconds <= self.maximum_budget_seconds:
            raise ContentError("INVALID_BUDGET", "Budget must fit the pinned timer policy bounds.")

    def validate_extension(self, budget_seconds: int, additional_seconds: int) -> None:
        if not 1 <= additional_seconds <= self.maximum_extension_seconds:
            raise ContentError("INVALID_BUDGET", "Extension exceeds the pinned per-command bound.")
        self.validate_budget(budget_seconds + additional_seconds)


@dataclass(frozen=True)
class TimerState:
    budget_seconds: int
    phase_elapsed_ms: int
    phase_running_since: datetime | None
    total_elapsed_ms: int
    total_running_since: datetime | None
    expired_at: datetime | None
    last_reconciled_at: datetime
    prior_phase_elapsed_ms: int = 0


@dataclass(frozen=True)
class TimerProjection:
    phase_elapsed_ms: int
    total_elapsed_ms: int
    remaining_ms: int
    overdue_ms: int
    expired_at: datetime | None


def normalized_server_time(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ContentError("CLOCK_UNAVAILABLE", "Server clock must provide aware UTC timestamps.")
    utc_now = now.astimezone(UTC)
    return utc_now.replace(microsecond=(utc_now.microsecond // 1000) * 1000)


def elapsed_milliseconds(start: datetime | None, now: datetime) -> int:
    if start is None:
        return 0
    if now < start:
        raise ContentError(
            "CLOCK_UNAVAILABLE", "Server clock moved backward; retry after synchronization."
        )
    delta = now - start
    return delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000


def project_timer(state: TimerState, now: datetime) -> TimerProjection:
    if now < state.last_reconciled_at:
        raise ContentError(
            "CLOCK_UNAVAILABLE", "Server clock moved backward; retry after synchronization."
        )
    budget_ms = state.budget_seconds * 1000
    phase_elapsed = min(
        budget_ms, state.phase_elapsed_ms + elapsed_milliseconds(state.phase_running_since, now)
    )
    total_elapsed = state.total_elapsed_ms + elapsed_milliseconds(state.total_running_since, now)
    expired_at = state.expired_at
    if expired_at is None and state.phase_running_since is not None and phase_elapsed == budget_ms:
        expired_at = state.phase_running_since + timedelta(
            milliseconds=budget_ms - state.phase_elapsed_ms
        )
    return TimerProjection(
        phase_elapsed,
        total_elapsed,
        budget_ms - phase_elapsed,
        max(0, total_elapsed - phase_elapsed - state.prior_phase_elapsed_ms),
        expired_at,
    )


def validate_transition(
    lifecycle: Lifecycle, command: AttemptCommand, expired_at: datetime | None
) -> Lifecycle:
    if command == "pause" and lifecycle == "active":
        return "paused"
    if command == "resume" and lifecycle == "paused":
        return "active"
    if command in {"extend", "defer", "abandon"} and lifecycle in {"active", "paused"}:
        if command == "extend":
            if expired_at is not None:
                raise ContentError(
                    "PHASE_EXPIRED", "The interval expired; extension cannot reopen it."
                )
            return lifecycle
        return "deferred" if command == "defer" else "abandoned"
    raise ContentError(
        "INVALID_ATTEMPT_STATE", "This command is not valid in the current attempt state."
    )
