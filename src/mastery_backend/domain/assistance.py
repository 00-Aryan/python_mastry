"""Pure assistance release rules; eligibility never implies disclosure."""

from datetime import datetime
from typing import Literal

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.timer_policy import Lifecycle, TimerPolicy

AssistanceTrigger = Literal["budget_expired", "learner_request", "solution_escape"]


def validate_assistance_release(
    lifecycle: Lifecycle,
    assistance_level: str,
    expired_at: datetime | None,
    trigger: AssistanceTrigger,
    policy: TimerPolicy,
) -> None:
    if lifecycle not in {"active", "paused"}:
        raise ContentError(
            "INVALID_ATTEMPT_STATE", "Only active or paused attempts can receive help."
        )
    if policy.assistance is None:
        raise ContentError("POLICY_UNAVAILABLE", "Pinned policy does not support assistance.")
    if assistance_level == "full_solution":
        raise ContentError("ASSISTANCE_EXHAUSTED", "The full solution has already been granted.")
    if trigger != "solution_escape" and expired_at is None:
        if assistance_level != "none" or trigger == "budget_expired":
            raise ContentError(
                "ASSISTANCE_NOT_READY",
                "Wait for the interval to expire, or confirm the solution escape.",
            )


def validate_wait_budget(policy: TimerPolicy, seconds: int) -> None:
    bounds = policy.assistance
    if bounds is None:
        raise ContentError("POLICY_UNAVAILABLE", "Pinned policy does not support assistance.")
    if not bounds.minimum_wait_seconds <= seconds <= bounds.maximum_wait_seconds:
        raise ContentError(
            "ASSISTANCE_UNAVAILABLE",
            "Pinned assistance interval is unavailable; contact the content administrator.",
        )
