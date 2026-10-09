"""Exact deterministic timer rules, independent of HTTP/database clocks."""

from datetime import UTC, datetime, timedelta

import pytest

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.timer_policy import (
    TimerPolicy,
    TimerState,
    normalized_server_time,
    project_timer,
    validate_transition,
)

START = datetime(2026, 10, 9, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "elapsed,remaining,overdue,expired",
    [(0, 60000, 0, False), (59999, 1, 0, False), (60000, 0, 0, True), (75000, 0, 15000, True)],
)
def test_exact_expiry_and_overdue(
    elapsed: int, remaining: int, overdue: int, expired: bool
) -> None:
    state = TimerState(60, 0, START, 0, START, None, START)
    projection = project_timer(state, START + timedelta(milliseconds=elapsed))
    assert projection.remaining_ms == remaining
    assert projection.total_elapsed_ms == elapsed
    assert projection.overdue_ms == overdue
    assert (projection.expired_at is not None) == expired
    if expired:
        assert projection.expired_at == START + timedelta(seconds=60)
        assert projection.phase_elapsed_ms == 60000


def test_pause_resume_projection_excludes_confirmed_pause() -> None:
    paused = TimerState(60, 12500, None, 12500, None, None, START + timedelta(seconds=12.5))
    assert project_timer(paused, START + timedelta(hours=1)).remaining_ms == 47500
    resumed_at = START + timedelta(hours=1)
    resumed = TimerState(60, 12500, resumed_at, 12500, resumed_at, None, resumed_at)
    projection = project_timer(resumed, resumed_at + timedelta(milliseconds=47500))
    assert projection.expired_at == resumed_at + timedelta(milliseconds=47500)
    assert projection.total_elapsed_ms == 60000


def test_clock_normalization_and_backward_jumps() -> None:
    assert normalized_server_time(START.replace(microsecond=123999)).microsecond == 123000
    with pytest.raises(ContentError) as caught:
        normalized_server_time(START.replace(tzinfo=None))
    assert caught.value.code == "CLOCK_UNAVAILABLE"
    with pytest.raises(ContentError):
        project_timer(
            TimerState(60, 0, START, 0, START, None, START), START - timedelta(milliseconds=1)
        )
    with pytest.raises(ContentError):
        project_timer(TimerState(60, 0, START + timedelta(seconds=1), 0, START, None, START), START)


def test_policy_and_transition_bounds() -> None:
    policy = TimerPolicy(
        minimum_budget_seconds=60,
        maximum_budget_seconds=3600,
        maximum_extension_seconds=1800,
        allowed_modes=["practice", "assessment"],
    )
    for value in [60, 3600]:
        policy.validate_budget(value)
    for value in [0, 59, 3601]:
        with pytest.raises(ContentError):
            policy.validate_budget(value)
    policy.validate_extension(60, 1800)
    for budget, extension in [(60, 0), (60, 1801), (3600, 1)]:
        with pytest.raises(ContentError):
            policy.validate_extension(budget, extension)
    assert validate_transition("active", "pause", None) == "paused"
    assert validate_transition("paused", "resume", START) == "active"
    assert validate_transition("paused", "defer", None) == "deferred"
    with pytest.raises(ContentError) as expired:
        validate_transition("active", "extend", START)
    assert expired.value.code == "PHASE_EXPIRED"
    for state, command in [
        ("paused", "pause"),
        ("active", "resume"),
        ("deferred", "resume"),
        ("abandoned", "extend"),
    ]:
        with pytest.raises(ContentError):
            validate_transition(state, command, None)
