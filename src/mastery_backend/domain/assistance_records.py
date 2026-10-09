"""Explicit projections of granted content, never future assets or private tests."""

from datetime import datetime
from uuid import UUID

from mastery_backend.domain.assistance import AssistanceTrigger
from mastery_backend.domain.attempt_records import AttemptSnapshot
from mastery_backend.domain.content import AssistanceKind, ContentValue, Solution


class GrantedAssistance(ContentValue):
    id: UUID
    step_id: UUID
    position: int
    kind: AssistanceKind
    content: str
    granted_at: datetime
    reason: AssistanceTrigger
    solution: Solution | None = None


class AssistanceResponse(ContentValue):
    grant: GrantedAssistance
    attempt: AttemptSnapshot


class AssistanceHistory(ContentValue):
    attempt_id: UUID
    grants: list[GrantedAssistance]
