"""Lease orchestration; adapter calls occur only after the claim transaction ends."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.clock import Clock
from mastery_backend.application.evaluation_service import evaluation_policy
from mastery_backend.application.evaluation_transactions import transition_evaluation
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.evaluations import (
    TERMINAL_STATES,
    RunnerCorrelation,
    RunnerRequest,
    RunnerResult,
    RunnerTest,
)
from mastery_backend.domain.timer_policy import normalized_server_time
from mastery_backend.infrastructure.database.attempt_models import Attempt
from mastery_backend.infrastructure.database.content_models import QuestionVersion, User
from mastery_backend.infrastructure.database.evaluation_models import (
    EvaluationDispatchIntent,
    EvaluationJob,
    TestBundle,
)
from mastery_backend.infrastructure.database.evaluation_repository import EvaluationRepository
from mastery_backend.infrastructure.database.submission_models import Submission
from mastery_backend.infrastructure.observability.logging import logger, request_id_context
from mastery_backend.infrastructure.runner.runner_protocol import (
    RunnerAdapter,
    require_supported_runner,
)


class EvaluationWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        clock: Clock,
        adapter: RunnerAdapter | None = None,
        environment: str = "development",
    ) -> None:
        self.factory, self.clock = factory, clock
        self.adapter, self.environment = adapter, environment

    transition = staticmethod(transition_evaluation)

    @staticmethod
    def lock_context(session: Session, job_id: UUID) -> EvaluationJob:
        # Discover immutable ownership, then use the same order as API mutations.
        context = session.execute(
            select(Attempt.id, Attempt.user_id)
            .join(EvaluationJob, EvaluationJob.attempt_id == Attempt.id)
            .where(EvaluationJob.id == job_id)
        ).one_or_none()
        if context is None:
            raise ContentError("NOT_FOUND", "Evaluation not found.")
        session.get(User, context.user_id, with_for_update=True)
        session.get(Attempt, context.id, with_for_update=True)
        return EvaluationRepository(session).job(job_id, lock=True)

    def claim(self) -> RunnerRequest | None:
        adapter = require_supported_runner(self.adapter, self.environment)
        with self.factory.begin() as session:
            now = normalized_server_time(self.clock.now())
            repo = EvaluationRepository(session)
            job = repo.due_job(now)
            if job is None:
                return None
            if job.deadline_at <= now:
                self.transition(
                    session,
                    job,
                    "infrastructure_error",
                    "DEADLINE_EXCEEDED",
                    now,
                    "infrastructure_error",
                )
                return None
            if job.runner_identity != adapter.identity:
                self.transition(
                    session,
                    job,
                    "infrastructure_error",
                    "RUNNER_UNAVAILABLE",
                    now,
                    "infrastructure_error",
                )
                return None
            policy = evaluation_policy(session, job.evaluator_policy_version_id)
            job.generation += 1
            job.lease_token = uuid4()
            job.lease_until = min(now + timedelta(seconds=policy.lease_seconds), job.deadline_at)
            self.transition(session, job, "running", "LEASED", now)
            intent = session.get(EvaluationDispatchIntent, job.id)
            assert intent is not None
            submission = session.get(Submission, job.submission_id)
            bundle = session.get(TestBundle, job.test_bundle_id)
            contract = session.scalar(
                select(QuestionVersion.contract_json).where(
                    QuestionVersion.id == job.question_version_id
                )
            )
            assert submission is not None and bundle is not None and contract is not None
            return RunnerRequest(
                job_id=job.id,
                request_id=intent.request_id,
                generation=job.generation,
                lease_token=job.lease_token,
                submission_id=job.submission_id,
                question_version_id=job.question_version_id,
                policy_version_id=job.policy_version_id,
                test_bundle_id=job.test_bundle_id,
                evaluator_policy_version_id=job.evaluator_policy_version_id,
                source_hash=submission.code_hash,
                bundle_hash=bundle.content_hash,
                runner_identity=job.runner_identity,
                source_code=submission.source_code,
                contract=contract,
                tests=[
                    RunnerTest.model_validate(row, from_attributes=True)
                    for row in repo.bundle_tests(bundle.id)
                ],
                execution_deadline=job.lease_until,
            )

    def apply_result(self, result: RunnerResult) -> bool:
        adapter = require_supported_runner(self.adapter, self.environment)
        with self.factory.begin() as session:
            job = self.lock_context(session, result.job_id)
            now = normalized_server_time(self.clock.now())
            if (
                job.status != "running"
                or adapter.identity != job.runner_identity
                or job.lease_token != result.lease_token
                or job.generation != result.generation
                or job.lease_until is None
                or now >= job.lease_until
                or now >= job.deadline_at
            ):
                return False
            submission = session.get(Submission, job.submission_id)
            bundle = session.get(TestBundle, job.test_bundle_id)
            assert submission is not None and bundle is not None
            expected = RunnerCorrelation(
                job_id=job.id,
                generation=job.generation,
                lease_token=job.lease_token,
                submission_id=job.submission_id,
                question_version_id=job.question_version_id,
                policy_version_id=job.policy_version_id,
                test_bundle_id=job.test_bundle_id,
                evaluator_policy_version_id=job.evaluator_policy_version_id,
                source_hash=submission.code_hash,
                bundle_hash=bundle.content_hash,
                runner_identity=job.runner_identity,
            )
            if (
                result.model_dump(include=set(RunnerCorrelation.model_fields))
                != expected.model_dump()
            ):
                return False
            if result.outcome == "infrastructure_error":
                self.retry_or_finish(session, job, "RUNNER_INFRASTRUCTURE", now)
            else:
                state = "passed" if result.outcome == "passed" else "failed"
                self.transition(session, job, state, "RUNNER_RESULT", now, result.outcome)
            return True

    def retry_or_finish(
        self, session: Session, job: EvaluationJob, reason: str, now: datetime
    ) -> None:
        policy = evaluation_policy(session, job.evaluator_policy_version_id)
        if job.generation >= policy.maximum_dispatches or now >= job.deadline_at:
            self.transition(
                session, job, "infrastructure_error", reason, now, "infrastructure_error"
            )
        else:
            job.next_retry_at = now + timedelta(seconds=policy.backoff_seconds * job.generation)
            self.transition(session, job, "pending", reason, now)

    def dispatch_failed(self, request: RunnerRequest, reason: str = "DISPATCH_FAILED") -> bool:
        require_supported_runner(self.adapter, self.environment)
        if reason not in {"DISPATCH_FAILED", "RUNNER_TIMEOUT", "INVALID_RESULT"}:
            raise ValueError("Unsupported infrastructure reason")
        with self.factory.begin() as session:
            job = self.lock_context(session, request.job_id)
            if (
                job.status != "running"
                or job.generation != request.generation
                or job.lease_token != request.lease_token
            ):
                return False
            self.retry_or_finish(session, job, reason, normalized_server_time(self.clock.now()))
            return True

    def recover(self, limit: int = 100) -> int:
        require_supported_runner(self.adapter, self.environment)
        if not 1 <= limit <= 100:
            raise ValueError("Recovery limit must be 1–100")
        with self.factory() as session:
            ids = EvaluationRepository(session).recovery_ids(
                normalized_server_time(self.clock.now()), limit
            )
        recovered = 0
        for identifier in ids:
            with self.factory.begin() as session:
                job = self.lock_context(session, identifier)
                now = normalized_server_time(self.clock.now())
                if job.status in TERMINAL_STATES:
                    continue
                if now >= job.deadline_at:
                    self.transition(
                        session,
                        job,
                        "infrastructure_error",
                        "DEADLINE_EXCEEDED",
                        now,
                        "infrastructure_error",
                    )
                elif (
                    job.status == "running"
                    and job.lease_until is not None
                    and now >= job.lease_until
                ):
                    self.retry_or_finish(session, job, "LEASE_EXPIRED", now)
                else:
                    continue
                recovered += 1
        return recovered

    def dispatch_once(self) -> bool:
        adapter = require_supported_runner(self.adapter, self.environment)
        request = self.claim()
        if request is None:
            return False
        context_token = request_id_context.set(request.request_id)
        try:
            try:
                result = adapter.dispatch(request)
                if not isinstance(result, RunnerResult):
                    self.dispatch_failed(request, "INVALID_RESULT")
                    return True
            except TimeoutError:
                self.dispatch_failed(request, "RUNNER_TIMEOUT")
            except Exception:
                logger.exception(
                    "evaluation_dispatch_failed", extra={"job_id": str(request.job_id)}
                )
                self.dispatch_failed(request)
            else:
                if not self.apply_result(result):
                    reason = (
                        "RUNNER_TIMEOUT"
                        if normalized_server_time(self.clock.now()) >= request.execution_deadline
                        else "INVALID_RESULT"
                    )
                    self.dispatch_failed(request, reason)
            return True
        finally:
            request_id_context.reset(context_token)
