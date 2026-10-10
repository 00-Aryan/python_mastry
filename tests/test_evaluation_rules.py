"""Pure state and protocol rules, without execution or fake correctness claims."""

import pytest
from pydantic import ValidationError

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.evaluations import (
    POLICY_CONFIG,
    EvaluationPolicy,
    validate_evaluation_transition,
)


@pytest.mark.parametrize(
    "before,after",
    [
        ("passed", "pending"),
        ("failed", "running"),
        ("infrastructure_error", "running"),
        ("pending", "passed"),
        ("running", "running"),
    ],
)
def test_illegal_transitions(before, after):
    with pytest.raises(ContentError):
        validate_evaluation_transition(before, after)


@pytest.mark.parametrize(
    "before,after",
    [
        ("pending", "running"),
        ("pending", "infrastructure_error"),
        ("running", "pending"),
        ("running", "passed"),
        ("running", "failed"),
        ("running", "infrastructure_error"),
    ],
)
def test_documented_transitions(before, after):
    validate_evaluation_transition(before, after)


@pytest.mark.parametrize(
    "change",
    [
        {"protocol_version": 2},
        {"maximum_dispatches": 4},
        {"lease_seconds": 0},
        {"deadline_seconds": 301},
    ],
)
def test_versioned_policy_bounds(change):
    with pytest.raises(ValidationError):
        EvaluationPolicy.model_validate({**POLICY_CONFIG, **change})
