"""Pinned asset access after ownership checks; no transaction commits."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from mastery_backend.domain.content import ContentError
from mastery_backend.infrastructure.database.assistance_models import AssistanceGrant
from mastery_backend.infrastructure.database.content_models import (
    QuestionAssistanceStep,
    QuestionSolution,
)


class AssistanceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replay(self, attempt_id: UUID, operation: str, key: str) -> AssistanceGrant | None:
        return self.session.scalar(
            select(AssistanceGrant).where(
                AssistanceGrant.attempt_id == attempt_id,
                AssistanceGrant.operation == operation,
                AssistanceGrant.request_key == key,
            )
        )

    def next_step(
        self, attempt_id: UUID, version_id: UUID, solution: bool
    ) -> QuestionAssistanceStep:
        granted = select(AssistanceGrant.step_id).where(AssistanceGrant.attempt_id == attempt_id)
        query = select(QuestionAssistanceStep).where(
            QuestionAssistanceStep.version_id == version_id
        )
        if solution:
            query = query.where(QuestionAssistanceStep.kind == "full_solution")
        else:
            query = query.where(QuestionAssistanceStep.id.not_in(granted))
        step = self.session.scalar(query.order_by(QuestionAssistanceStep.position).limit(1))
        if step is None or not step.content.strip():
            raise ContentError(
                "ASSISTANCE_UNAVAILABLE",
                "Pinned assistance asset is unavailable; contact the content administrator.",
            )
        if not solution and step.kind == "full_solution":
            raise ContentError(
                "ASSISTANCE_EXHAUSTED", "No further hints remain; confirm the full-solution escape."
            )
        return step

    def solution(self, version_id: UUID) -> QuestionSolution:
        solution = self.session.get(QuestionSolution, version_id)
        if solution is None or any(
            not value.strip()
            for value in (
                solution.reference_code,
                solution.explanation,
                solution.expected_complexity,
            )
        ):
            raise ContentError(
                "ASSISTANCE_UNAVAILABLE",
                "Pinned solution is unavailable; contact the content administrator.",
            )
        return solution

    def history(self, attempt_id: UUID) -> list[AssistanceGrant]:
        return list(
            self.session.scalars(
                select(AssistanceGrant)
                .join(QuestionAssistanceStep, QuestionAssistanceStep.id == AssistanceGrant.step_id)
                .where(AssistanceGrant.attempt_id == attempt_id)
                .order_by(QuestionAssistanceStep.position)
                .limit(5)
            )
        )
