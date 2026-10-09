"""Ownership-filtered attempts and append-only events; services own commits."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from mastery_backend.domain.attempt_records import AttemptListQuery
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.timer_policy import PILOT_TIMER_POLICY_CODE, TimerPolicy
from mastery_backend.infrastructure.database.attempt_models import (
    Attempt,
    AttemptEvent,
    AttemptPhase,
    LearningPolicyVersion,
    UserQuestionFamilyHistory,
)
from mastery_backend.infrastructure.database.content_models import (
    Question,
    QuestionVersion,
    QuestionVersionMode,
)


class AttemptRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def owned_attempt(self, user_id: UUID, attempt_id: UUID) -> Attempt:
        attempt = self.session.scalar(
            select(Attempt)
            .where(
                Attempt.id == attempt_id,
                Attempt.user_id == user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if attempt is None:
            raise ContentError("NOT_FOUND", "Owned attempt not found.")
        return attempt

    def phase(self, attempt_id: UUID) -> AttemptPhase:
        return self.session.scalars(
            select(AttemptPhase).where(
                AttemptPhase.attempt_id == attempt_id,
                AttemptPhase.phase_number == 0,
            )
        ).one()

    def policy(self, policy_id: UUID | None = None) -> tuple[LearningPolicyVersion, TimerPolicy]:
        query = select(LearningPolicyVersion)
        query = (
            query.where(LearningPolicyVersion.id == policy_id)
            if policy_id
            else query.where(LearningPolicyVersion.version_code == PILOT_TIMER_POLICY_CODE)
        )
        policy = self.session.scalar(query)
        if policy is None:
            raise ContentError("POLICY_UNAVAILABLE", "Pinned timer policy is unavailable.")
        return policy, TimerPolicy.model_validate(policy.configuration_json)

    def start_context(self, version_id: UUID, mode: str) -> UUID:
        # Lock the parent before rechecking availability, matching question archival.
        question_id = self.session.scalar(
            select(QuestionVersion.question_id).where(
                QuestionVersion.id == version_id, QuestionVersion.status == "published"
            )
        )
        if question_id is None:
            raise ContentError("NOT_FOUND", "Available published question version not found.")
        question = self.session.scalar(
            select(Question)
            .where(Question.id == question_id, Question.archived_at.is_(None))
            .with_for_update(read=True)
        )
        if question is None:
            raise ContentError("NOT_FOUND", "Available published question version not found.")
        supported = self.session.scalar(
            select(QuestionVersionMode.mode).where(
                QuestionVersionMode.version_id == version_id, QuestionVersionMode.mode == mode
            )
        )
        if supported is None:
            raise ContentError("INVALID_MODE", "The published question does not support this mode.")
        return question.family_id

    def family_history(self, user_id: UUID, family_id: UUID) -> UserQuestionFamilyHistory | None:
        return self.session.get(UserQuestionFamilyHistory, (user_id, family_id))

    def append_event(
        self,
        attempt: Attempt,
        event_type: str,
        occurred_at: datetime,
        payload: dict[str, Any],
        command_id: UUID | None,
    ) -> None:
        attempt.last_event_sequence += 1
        self.session.add(
            AttemptEvent(
                attempt_id=attempt.id,
                sequence_number=attempt.last_event_sequence,
                event_type=event_type,
                occurred_at=occurred_at,
                payload_json=payload,
                command_id=command_id,
            )
        )

    def page(
        self, user_id: UUID, query: AttemptListQuery, after: tuple[datetime, UUID] | None
    ) -> list[Attempt]:
        statement = select(Attempt).where(Attempt.user_id == user_id)
        if query.mode:
            statement = statement.where(Attempt.mode == query.mode)
        if query.lifecycle_state:
            statement = statement.where(Attempt.lifecycle_state == query.lifecycle_state)
        if after:
            statement = statement.where(tuple_(Attempt.started_at, Attempt.id) < after)
        rows = list(
            self.session.scalars(
                statement.order_by(Attempt.started_at.desc(), Attempt.id.desc()).limit(
                    query.limit + 1
                )
            )
        )
        identifiers = [row.id for row in rows[: query.limit]]
        # A list reconciles several attempts; acquire those locks in UUID order.
        list(
            self.session.scalars(
                select(Attempt)
                .where(
                    Attempt.id.in_(identifiers),
                    Attempt.user_id == user_id,
                )
                .order_by(Attempt.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        return rows

    def phases(self, attempts: list[Attempt]) -> dict[UUID, AttemptPhase]:
        return {
            phase.attempt_id: phase
            for phase in self.session.scalars(
                select(AttemptPhase).where(
                    AttemptPhase.attempt_id.in_([attempt.id for attempt in attempts]),
                    AttemptPhase.phase_number == 0,
                )
            )
        }

    def policy_codes(self, attempts: list[Attempt]) -> dict[UUID, str]:
        return {
            identifier: code
            for identifier, code in self.session.execute(
                select(LearningPolicyVersion.id, LearningPolicyVersion.version_code).where(
                    LearningPolicyVersion.id.in_(
                        {attempt.policy_version_id for attempt in attempts}
                    )
                )
            )
        }
