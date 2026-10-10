"""Owned evaluation queries, normalized bundle creation and durable work selection."""

from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from mastery_backend.application.command_replay import request_hash
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.evaluations import RunnerTest
from mastery_backend.infrastructure.database.attempt_models import Attempt
from mastery_backend.infrastructure.database.content_models import QuestionTestCase, QuestionVersion
from mastery_backend.infrastructure.database.evaluation_models import (
    EvaluationDispatchIntent,
    EvaluationEvent,
    EvaluationJob,
    EvaluationRequestReceipt,
    TestBundle,
    TestBundleMember,
)


class EvaluationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def pending_assessment(self, attempt_id: UUID) -> EvaluationJob | None:
        return self.session.scalar(
            select(EvaluationJob)
            .where(
                EvaluationJob.attempt_id == attempt_id,
                EvaluationJob.purpose == "assessment",
                EvaluationJob.status.in_(["pending", "running"]),
            )
            .with_for_update()
        )

    def job(self, job_id: UUID, *, lock: bool = False) -> EvaluationJob:
        query = select(EvaluationJob).where(EvaluationJob.id == job_id)
        if lock:
            query = query.with_for_update()
        row = self.session.scalar(query)
        if row is None:
            raise ContentError("NOT_FOUND", "Evaluation not found.")
        return row

    def owned_job(self, owner_id: UUID, job_id: UUID) -> EvaluationJob:
        row = self.session.scalar(
            select(EvaluationJob)
            .join(Attempt, Attempt.id == EvaluationJob.attempt_id)
            .where(EvaluationJob.id == job_id, Attempt.user_id == owner_id)
            .with_for_update(of=EvaluationJob)
        )
        if row is None:
            raise ContentError("NOT_FOUND", "Evaluation not found.")
        return row

    def replay(self, submission_id: UUID, key: str) -> EvaluationRequestReceipt | None:
        return self.session.get(EvaluationRequestReceipt, (submission_id, key))

    def transitions(self, job_id: UUID) -> list[EvaluationEvent]:
        # Three generations imply at most eight transitions; bound even corrupt data.
        return list(
            self.session.scalars(
                select(EvaluationEvent)
                .where(EvaluationEvent.job_id == job_id)
                .order_by(EvaluationEvent.sequence_number)
                .limit(8)
            )
        )

    def bundle(self, version_id: UUID, purpose: str) -> TestBundle:
        identifier = uuid5(version_id, "evaluation-bundle-v1:" + purpose)
        existing = self.session.get(TestBundle, identifier)
        if existing is not None:
            return existing
        tests = self.selected_tests(version_id, purpose)
        contract = self.session.scalar(
            select(QuestionVersion.contract_json).where(
                QuestionVersion.id == version_id, QuestionVersion.status == "published"
            )
        )
        if not tests or contract is None:
            raise ContentError(
                "EVALUATION_UNAVAILABLE", "Published evaluation assets are unavailable."
            )
        digest = request_hash(
            {
                "contract": contract,
                "tests": [
                    RunnerTest.model_validate(row, from_attributes=True).model_dump(mode="json")
                    for row in tests
                ],
            }
        )
        inserted = self.session.scalar(
            insert(TestBundle)
            .values(
                id=identifier, question_version_id=version_id, purpose=purpose, content_hash=digest
            )
            .on_conflict_do_nothing()
            .returning(TestBundle.id)
        )
        if inserted is not None:
            self.session.add_all(
                [TestBundleMember(bundle_id=identifier, test_id=row.id) for row in tests]
            )
            self.session.flush()
        bundle = self.session.get(TestBundle, identifier)
        assert bundle is not None
        return bundle

    def selected_tests(self, version_id: UUID, purpose: str) -> list[QuestionTestCase]:
        query = select(QuestionTestCase).where(QuestionTestCase.version_id == version_id)
        if purpose == "public_run":
            query = query.where(QuestionTestCase.visibility == "public")
        return list(self.session.scalars(query.order_by(QuestionTestCase.position)))

    def bundle_tests(self, bundle_id: UUID) -> list[QuestionTestCase]:
        return list(
            self.session.scalars(
                select(QuestionTestCase)
                .join(TestBundleMember, TestBundleMember.test_id == QuestionTestCase.id)
                .where(TestBundleMember.bundle_id == bundle_id)
                .order_by(QuestionTestCase.position)
            )
        )

    def due_job(self, now: datetime) -> EvaluationJob | None:
        return self.session.scalar(
            select(EvaluationJob)
            .join(EvaluationDispatchIntent)
            .where(EvaluationJob.status == "pending", EvaluationJob.next_retry_at <= now)
            .order_by(EvaluationJob.requested_at, EvaluationJob.id)
            .with_for_update(skip_locked=True, of=EvaluationJob)
            .limit(1)
        )

    def recovery_ids(self, now: datetime, limit: int) -> list[UUID]:
        return list(
            self.session.scalars(
                select(EvaluationJob.id)
                .where(
                    EvaluationJob.status.in_(["pending", "running"]),
                    (EvaluationJob.deadline_at <= now) | (EvaluationJob.lease_until <= now),
                )
                .order_by(EvaluationJob.requested_at, EvaluationJob.id)
                .limit(limit)
            )
        )

    def page(
        self, attempt_id: UUID, limit: int, upper: int | None, after: int | None
    ) -> list[EvaluationJob]:
        query = select(EvaluationJob).where(EvaluationJob.attempt_id == attempt_id)
        if upper is not None:
            query = query.where(EvaluationJob.requested_event_sequence <= upper)
        if after is not None:
            query = query.where(EvaluationJob.requested_event_sequence < after)
        return list(
            self.session.scalars(
                query.order_by(EvaluationJob.requested_event_sequence.desc()).limit(limit + 1)
            )
        )
