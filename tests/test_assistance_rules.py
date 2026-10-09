"""Pinned assistance bounds and accumulated multi-phase overdue duration."""

from datetime import UTC, datetime, timedelta

import pytest

from mastery_backend.domain.assistance import validate_wait_budget
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.timer_policy import (
    AssistancePolicy,
    TimerPolicy,
    TimerState,
    project_timer,
)


def policy():
    return TimerPolicy(
        minimum_budget_seconds=60,
        maximum_budget_seconds=3600,
        maximum_extension_seconds=1800,
        allowed_modes=["practice", "assessment"],
        assistance=AssistancePolicy(minimum_wait_seconds=60, maximum_wait_seconds=86400),
    )


@pytest.mark.parametrize("seconds", [60, 86400])
def test_pinned_wait_bounds_accept_exact_limits(seconds):
    validate_wait_budget(policy(), seconds)


@pytest.mark.parametrize("seconds", [0, 59, 86401])
def test_pinned_wait_bounds_reject_unsupported_content(seconds):
    with pytest.raises(ContentError) as caught:
        validate_wait_budget(policy(), seconds)
    assert caught.value.code == "ASSISTANCE_UNAVAILABLE"


def test_legacy_policy_cannot_invent_assistance_rules():
    legacy = policy().model_copy(update={"assistance": None})
    with pytest.raises(ContentError) as caught:
        validate_wait_budget(legacy, 60)
    assert caught.value.code == "POLICY_UNAVAILABLE"


def test_overdue_duration_excludes_all_prior_phase_work():
    now = datetime(2026, 10, 10, tzinfo=UTC)
    state = TimerState(
        budget_seconds=60,
        phase_elapsed_ms=10000,
        phase_running_since=now,
        total_elapsed_ms=150000,
        total_running_since=now,
        expired_at=None,
        last_reconciled_at=now,
        prior_phase_elapsed_ms=130000,
    )
    running = project_timer(state, now + timedelta(seconds=20))
    assert running.total_elapsed_ms == 170000
    assert running.phase_elapsed_ms == 30000
    assert running.overdue_ms == 10000
    expired = project_timer(state, now + timedelta(seconds=60))
    assert expired.phase_elapsed_ms == 60000
    assert expired.overdue_ms == 20000
