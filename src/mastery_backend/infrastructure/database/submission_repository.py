"""Ownership-filtered immutable receipt queries; services own transactions."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.submissions import SubmissionPurpose
from mastery_backend.infrastructure.database.assistance_models import AssistanceGrant
from mastery_backend.infrastructure.database.attempt_models import Attempt
from mastery_backend.infrastructure.database.submission_models import Submission


class SubmissionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replay(self, attempt_id: UUID, key: str) -> Submission | None:
        return self.session.scalar(
            select(Submission).where(
                Submission.attempt_id == attempt_id, Submission.request_key == key
            )
        )

    def owned_detail(self, user_id: UUID, submission_id: UUID) -> Submission:
        submission = self.session.scalar(
            select(Submission)
            .join(Attempt, Attempt.id == Submission.attempt_id)
            .where(Submission.id == submission_id, Attempt.user_id == user_id)
        )
        if submission is None:
            raise ContentError("NOT_FOUND", "Owned submission not found.")
        return submission

    def grant_ids(self, attempt_id: UUID) -> list[UUID]:
        return list(
            self.session.scalars(
                select(AssistanceGrant.id)
                .where(AssistanceGrant.attempt_id == attempt_id)
                .order_by(AssistanceGrant.granted_at, AssistanceGrant.id)
            )
        )

    def insert(self, submission: Submission) -> None:
        self.session.add(submission)
        self.session.flush()

    def page(
        self,
        attempt_id: UUID,
        limit: int,
        purpose: SubmissionPurpose | None,
        upper_sequence: int,
        after_sequence: int | None,
    ) -> list[Submission]:
        query = (
            select(Submission)
            .options(
                load_only(
                    Submission.id,
                    Submission.attempt_id,
                    Submission.question_version_id,
                    Submission.policy_version_id,
                    Submission.purpose,
                    Submission.code_hash,
                    Submission.source_bytes,
                    Submission.accepted_at,
                    Submission.accepted_event_sequence,
                    Submission.attempt_revision,
                )
            )
            .where(
                Submission.attempt_id == attempt_id,
                Submission.accepted_event_sequence <= upper_sequence,
            )
        )
        if purpose:
            query = query.where(Submission.purpose == purpose)
        if after_sequence is not None:
            query = query.where(Submission.accepted_event_sequence < after_sequence)
        return list(
            self.session.scalars(
                query.order_by(Submission.accepted_event_sequence.desc()).limit(limit + 1)
            )
        )
