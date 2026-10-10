"""Trusted adapter boundary. No transport or learner-code executor is registered."""

from typing import Protocol

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.evaluations import RunnerRequest, RunnerResult


class RunnerAdapter(Protocol):
    @property
    def identity(self) -> str: ...

    def dispatch(self, request: RunnerRequest) -> RunnerResult:
        """Authenticate transport/results and enforce execution deadline before return."""
        ...


def require_supported_runner(adapter: RunnerAdapter | None, environment: str) -> RunnerAdapter:
    # There are no reviewed real adapters yet. This is not an environment switch
    # that enables a fake in local development or production.
    if environment != "test" or adapter is None:
        raise ContentError(
            "EVALUATION_UNAVAILABLE", "A supported isolated evaluator is unavailable."
        )
    if not adapter.identity or len(adapter.identity) > 100:
        raise ContentError(
            "EVALUATION_UNAVAILABLE", "A supported isolated evaluator is unavailable."
        )
    return adapter
