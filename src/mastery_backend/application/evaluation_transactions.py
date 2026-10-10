"""Shared evaluation transitions and deadline admission rules under existing locks."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.evaluations import TERMINAL_STATES, validate_evaluation_transition
from mastery_backend.infrastructure.database.evaluation_models import EvaluationEvent, EvaluationJob
from mastery_backend.infrastructure.database.evaluation_repository import EvaluationRepository


def transition_evaluation(
    session: Session,
    job: EvaluationJob,
    state: str,
    reason: str,
    now: datetime,
    category: str | None = None,
) -> None:
    validate_evaluation_transition(job.status, state)
    with session.no_autoflush:
        previous = EvaluationRepository(session).transitions(job.id)
    if previous and now < previous[-1].occurred_at:
        raise ContentError("CLOCK_UNAVAILABLE", "Server time precedes recorded evaluation history.")
    job.status = state
    job.last_sequence += 1
    job.category = category
    if state != "running":
        job.lease_token = None
        job.lease_until = None
    if state in TERMINAL_STATES:
        job.finished_at = now
    session.flush()
    session.add(
        EvaluationEvent(
            job_id=job.id,
            sequence_number=job.last_sequence,
            state=state,
            reason_code=reason,
            occurred_at=now,
            generation=job.generation,
        )
    )
    session.flush()


def check_pending_assessment(session: Session, attempt_id: UUID, now: datetime) -> None:
    # Caller already owns the user/attempt locks. Job comes last, as in result application.
    job = EvaluationRepository(session).pending_assessment(attempt_id)
    if job is None:
        return
    if now >= job.deadline_at:
        transition_evaluation(
            session, job, "infrastructure_error", "DEADLINE_EXCEEDED", now, "infrastructure_error"
        )
        return
    raise ContentError("EVALUATION_PENDING", "Wait for the pending assessment to resolve.")
