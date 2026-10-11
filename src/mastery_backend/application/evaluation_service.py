"""Atomic owned admission and bounded public reads, without runner/network work."""

import base64
import binascii
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.attempt_service import AttemptService
from mastery_backend.application.clock import Clock
from mastery_backend.application.command_replay import CommandResult, request_hash
from mastery_backend.application.evaluation_transactions import check_pending_assessment
from mastery_backend.domain.content import ContentError, ContentValue
from mastery_backend.domain.evaluations import (
    POLICY_ID,
    EvaluationDetail,
    EvaluationListQuery,
    EvaluationPage,
    EvaluationPolicy,
    EvaluationSummary,
    EvaluationTransition,
)
from mastery_backend.domain.identity import Principal
from mastery_backend.domain.submissions import validate_submission_lifecycle
from mastery_backend.domain.timer_policy import normalized_server_time, project_timer
from mastery_backend.infrastructure.database.attempt_repository import AttemptRepository
from mastery_backend.infrastructure.database.evaluation_models import (
    EvaluationDispatchIntent,
    EvaluationEvent,
    EvaluationJob,
    EvaluationPolicyVersion,
    EvaluationRequestReceipt,
)
from mastery_backend.infrastructure.database.evaluation_repository import (
    EvaluationRepository,
)
from mastery_backend.infrastructure.database.submission_repository import SubmissionRepository
from mastery_backend.infrastructure.observability.logging import logger, request_id_context
from mastery_backend.infrastructure.runner.runner_protocol import (
    RunnerAdapter,
    require_supported_runner,
)


class EvaluationCursor(ContentValue):
    upper_sequence: int
    after_sequence: int
    expires_at: datetime
    filter_hash: str


def evaluation_policy(session: Session, identifier: UUID) -> EvaluationPolicy:
    record = session.get(EvaluationPolicyVersion, identifier)
    try:
        if record is None:
            raise ValueError("Missing policy")
        return EvaluationPolicy.model_validate(record.configuration_json)
    except (ValueError, ValidationError):
        raise ContentError("EVALUATION_UNAVAILABLE", "Evaluator policy is unavailable.") from None


class EvaluationService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        clock: Clock,
        adapter: RunnerAdapter | None = None,
        environment: str = "development",
    ) -> None:
        self.factory = factory
        self.clock = clock
        self.attempts = AttemptService(factory, clock)
        self.adapter = adapter
        self.environment = environment

    @staticmethod
    def detail(repo: EvaluationRepository, job: EvaluationJob) -> EvaluationDetail:
        return EvaluationDetail(
            **EvaluationSummary.model_validate(job, from_attributes=True).model_dump(),
            transitions=[
                EvaluationTransition.model_validate(row, from_attributes=True)
                for row in repo.transitions(job.id)
            ],
        )

    def request(
        self, principal: Principal, submission_id: UUID, key: str, expected_revision: int
    ) -> CommandResult:
        digest = request_hash({"expected_revision": expected_revision})
        try:
            with self.factory.begin() as session:
                self.attempts.authorize(session, principal)
                submission = SubmissionRepository(session).owned_detail(
                    principal.user_id, submission_id
                )
                attempts = AttemptRepository(session)
                attempt = attempts.owned_attempt(principal.user_id, submission.attempt_id)
                repo = EvaluationRepository(session)
                replay = repo.replay(submission_id, key)
                if replay:
                    if replay.request_hash != digest:
                        raise ContentError(
                            "IDEMPOTENCY_CONFLICT", "This key was used with different input."
                        )
                    return CommandResult(
                        replay.response_json, 202, f"/api/v1/evaluations/{replay.job_id}", True
                    )
                adapter = require_supported_runner(self.adapter, self.environment)
                if (
                    session.scalar(
                        select(EvaluationJob.id).where(EvaluationJob.submission_id == submission_id)
                    )
                    is not None
                ):
                    raise ContentError(
                        "EVALUATION_EXISTS",
                        "This submission already has an evaluation; read its status.",
                    )
                if attempt.revision != expected_revision:
                    raise ContentError("STALE_REVISION", "Attempt changed; reload before retrying.")
                validate_submission_lifecycle(attempt.lifecycle_state)
                policy_id = getattr(adapter, "evaluator_policy_id", POLICY_ID)
                policy = evaluation_policy(session, policy_id)
                bundle = repo.bundle(submission.question_version_id, submission.purpose)
                phase = attempts.phase(attempt.id)
                now = normalized_server_time(self.clock.now())
                check_pending_assessment(session, attempt.id, now)
                command_id = uuid4()
                self.attempts.reconcile_expiry(attempts, attempt, phase, now, command_id)
                projection = project_timer(self.attempts.timer_state(attempt, phase), now)
                self.attempts.materialize(attempt, phase, projection, now)
                attempt.total_running_since = now if attempt.lifecycle_state == "active" else None
                if phase.running_since is not None:
                    phase.running_since = now
                attempt.revision += 1
                job = EvaluationJob(
                    id=uuid4(),
                    attempt_id=attempt.id,
                    submission_id=submission_id,
                    question_version_id=submission.question_version_id,
                    policy_version_id=submission.policy_version_id,
                    test_bundle_id=bundle.id,
                    evaluator_policy_version_id=policy_id,
                    purpose=submission.purpose,
                    runner_identity=adapter.identity,
                    status="pending",
                    requested_event_sequence=attempt.last_event_sequence + 1,
                    requested_at=now,
                    next_retry_at=now,
                    deadline_at=now + timedelta(seconds=policy.deadline_seconds),
                    generation=0,
                    last_sequence=1,
                )
                attempts.append_event(
                    attempt,
                    "evaluation_requested",
                    now,
                    {"job_id": str(job.id), "submission_id": str(submission_id)},
                    command_id,
                )
                session.flush()
                session.add(job)
                session.flush()
                session.add(
                    EvaluationEvent(
                        job_id=job.id,
                        sequence_number=1,
                        state="pending",
                        reason_code="REQUESTED",
                        occurred_at=now,
                        generation=0,
                    )
                )
                session.add(
                    EvaluationDispatchIntent(job_id=job.id, request_id=request_id_context.get())
                )
                session.flush()
                body = self.detail(repo, job).model_dump(mode="json")
                session.add(
                    EvaluationRequestReceipt(
                        submission_id=submission_id,
                        request_key=key,
                        job_id=job.id,
                        request_hash=digest,
                        response_json=body,
                    )
                )
                session.flush()
                result = CommandResult(body, 202, f"/api/v1/evaluations/{job.id}")
            logger.info(
                "evaluation_requested",
                extra={
                    "job_id": str(job.id),
                    "attempt_id": str(job.attempt_id),
                    "submission_id": str(submission_id),
                    "reason_code": "REQUESTED",
                },
            )
            return result
        except IntegrityError:
            raise ContentError(
                "EVALUATION_CONFLICT",
                "Evaluation conflicts with stored history; reload before retrying.",
            ) from None

    def read(self, principal: Principal, job_id: UUID) -> EvaluationDetail:
        with self.factory.begin() as session:
            self.attempts.authorize(session, principal)
            repo = EvaluationRepository(session)
            return self.detail(repo, repo.owned_job(principal.user_id, job_id))

    def list_evaluations(
        self, principal: Principal, attempt_id: UUID, query: EvaluationListQuery
    ) -> EvaluationPage:
        digest = request_hash({"owner": str(principal.user_id), "attempt": str(attempt_id)})
        cursor = None
        if query.cursor:
            try:
                cursor = EvaluationCursor.model_validate_json(
                    base64.b64decode(query.cursor, altchars=b"-_", validate=True)
                )
                if (
                    cursor.expires_at.tzinfo is None
                    or cursor.expires_at <= datetime.now(UTC)
                    or cursor.filter_hash != digest
                    or not 0 < cursor.after_sequence <= cursor.upper_sequence
                ):
                    raise ValueError("Invalid cursor")
            except (ValueError, binascii.Error):
                raise ContentError(
                    "INVALID_CURSOR", "Evaluation cursor is invalid or expired."
                ) from None
        with self.factory.begin() as session:
            self.attempts.authorize(session, principal)
            AttemptRepository(session).owned_attempt(principal.user_id, attempt_id)
            rows = EvaluationRepository(session).page(
                attempt_id,
                query.limit,
                cursor.upper_sequence if cursor else None,
                cursor.after_sequence if cursor else None,
            )
            items = rows[: query.limit]
            next_cursor = None
            if len(rows) > query.limit:
                next_cursor = base64.urlsafe_b64encode(
                    EvaluationCursor(
                        upper_sequence=cursor.upper_sequence
                        if cursor
                        else rows[0].requested_event_sequence,
                        after_sequence=items[-1].requested_event_sequence,
                        expires_at=cursor.expires_at
                        if cursor
                        else datetime.now(UTC) + timedelta(days=1),
                        filter_hash=digest,
                    )
                    .model_dump_json()
                    .encode()
                ).decode()
            return EvaluationPage(
                items=[
                    EvaluationSummary.model_validate(row, from_attributes=True) for row in items
                ],
                next_cursor=next_cursor,
            )
