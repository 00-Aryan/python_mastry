"""Versioned orchestration values; no execution or eligibility calculations."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from mastery_backend.domain.content import ContentError, ContentValue

EvaluationState = Literal["pending", "running", "passed", "failed", "infrastructure_error"]
Outcome = Literal["passed", "incorrect", "syntax_error", "resource_limit", "infrastructure_error"]
TERMINAL_STATES = frozenset({"passed", "failed", "infrastructure_error"})
POLICY_ID = UUID("00000000-0000-0000-0000-000000000201")
POLICY_CONFIG = {
    "protocol_version": 1,
    "maximum_dispatches": 3,
    "lease_seconds": 30,
    "deadline_seconds": 300,
    "backoff_seconds": 5,
}


def validate_evaluation_transition(before: str, after: str) -> None:
    allowed = {
        "pending": {"running", "infrastructure_error"},
        "running": {"pending", "passed", "failed", "infrastructure_error"},
    }
    if after not in allowed.get(before, set()):
        raise ContentError("INVALID_EVALUATION_STATE", "Evaluation transition is not allowed.")


class EvaluationPolicy(ContentValue):
    protocol_version: Literal[1]
    maximum_dispatches: int = Field(ge=1, le=3)
    lease_seconds: int = Field(ge=1, le=30)
    deadline_seconds: int = Field(ge=1, le=300)
    backoff_seconds: int = Field(ge=1, le=10)


class RunnerCorrelation(ContentValue):
    protocol_version: Literal[1] = 1
    job_id: UUID
    generation: int = Field(ge=1)
    lease_token: UUID
    submission_id: UUID
    question_version_id: UUID
    policy_version_id: UUID
    test_bundle_id: UUID
    evaluator_policy_version_id: UUID
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    bundle_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    runner_identity: str = Field(min_length=1, max_length=100)


class RunnerTest(ContentValue):
    id: UUID
    visibility: Literal["public", "private"]
    input_json: list[Any]
    expected_json: Any
    assertion_rule: Literal["equals"]
    critical: bool


class RunnerRequest(RunnerCorrelation):
    request_id: str | None = Field(default=None, max_length=128)
    source_code: str
    contract: dict[str, Any]
    tests: list[RunnerTest]
    execution_deadline: datetime


class RunnerResult(RunnerCorrelation):
    outcome: Outcome


class EvaluationTransition(ContentValue):
    sequence_number: int
    state: EvaluationState
    reason_code: str
    occurred_at: datetime
    generation: int


class EvaluationSummary(ContentValue):
    id: UUID
    submission_id: UUID
    question_version_id: UUID
    policy_version_id: UUID
    test_bundle_id: UUID
    evaluator_policy_version_id: UUID
    status: EvaluationState
    category: Outcome | None
    requested_at: datetime
    deadline_at: datetime
    finished_at: datetime | None
    generation: int


class EvaluationDetail(EvaluationSummary):
    transitions: list[EvaluationTransition]


class EvaluationListQuery(ContentValue):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)


class EvaluationPage(ContentValue):
    items: list[EvaluationSummary]
    next_cursor: str | None
