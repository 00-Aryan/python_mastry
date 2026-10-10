"""Atomic owned grants, server-timed waiting phases and permanent retry receipts."""

from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.attempt_service import AttemptService
from mastery_backend.application.clock import Clock
from mastery_backend.application.command_replay import CommandResult, request_hash
from mastery_backend.application.evaluation_transactions import check_pending_assessment
from mastery_backend.domain.assistance import (
    AssistanceTrigger,
    validate_assistance_release,
    validate_wait_budget,
)
from mastery_backend.domain.assistance_records import (
    AssistanceHistory,
    AssistanceResponse,
    GrantedAssistance,
)
from mastery_backend.domain.content import ContentError, Solution
from mastery_backend.domain.identity import Principal
from mastery_backend.domain.timer_policy import normalized_server_time, project_timer
from mastery_backend.infrastructure.database.assistance_models import AssistanceGrant
from mastery_backend.infrastructure.database.assistance_repository import AssistanceRepository
from mastery_backend.infrastructure.database.attempt_models import AttemptPhase
from mastery_backend.infrastructure.database.attempt_repository import AttemptRepository
from mastery_backend.infrastructure.observability.logging import logger


class AssistanceService:
    def __init__(self, factory: sessionmaker[Session], clock: Clock) -> None:
        self.factory = factory
        self.attempts = AttemptService(factory, clock)
        self.clock = clock

    def grant(
        self,
        principal: Principal,
        attempt_id: UUID,
        key: str,
        operation: Literal["next", "solution"],
        expected_revision: int,
        trigger: AssistanceTrigger,
    ) -> CommandResult:
        payload: dict[str, Any] = {"expected_revision": expected_revision}
        payload.update({"confirmation": True} if operation == "solution" else {"trigger": trigger})
        digest = request_hash(payload)
        try:
            with self.factory.begin() as session:
                self.attempts.authorize(session, principal)
                attempts = AttemptRepository(session)
                attempt = attempts.owned_attempt(principal.user_id, attempt_id)
                assets = AssistanceRepository(session)
                replay = assets.replay(attempt_id, operation, key)
                if replay is not None:
                    if replay.request_hash != digest:
                        raise ContentError(
                            "IDEMPOTENCY_CONFLICT", "This key was used with different input."
                        )
                    return CommandResult(replay.response_json, replayed=True)
                if attempt.revision != expected_revision:
                    raise ContentError("STALE_REVISION", "Attempt changed; reload before retrying.")
                phase = attempts.phase(attempt_id)
                now = normalized_server_time(self.clock.now())
                check_pending_assessment(session, attempt_id, now)
                command_id = uuid4()
                self.attempts.reconcile_expiry(attempts, attempt, phase, now, command_id)
                policy_record, policy = attempts.policy(attempt.policy_version_id)
                validate_assistance_release(
                    attempt.lifecycle_state,
                    attempt.assistance_level,
                    phase.expired_at,
                    trigger,
                    policy,
                )
                step = assets.next_step(
                    attempt_id, attempt.question_version_id, operation == "solution"
                )
                solution = None
                if operation == "solution":
                    record = assets.solution(attempt.question_version_id)
                    solution = Solution(
                        reference_code=record.reference_code,
                        explanation=record.explanation,
                        expected_complexity=record.expected_complexity,
                    )
                else:
                    validate_wait_budget(policy, step.next_budget_seconds)
                projection = project_timer(self.attempts.timer_state(attempt, phase), now)
                self.attempts.materialize(attempt, phase, projection, now)
                attempt.total_running_since = now if attempt.lifecycle_state == "active" else None
                if phase.closed_at is None:
                    phase.closed_at = now
                    phase.running_since = None
                if attempt.independent_interval_ended_at is None:
                    attempt.independent_interval_ended_at = now
                    attempt.independent_end_reason = "assistance_requested"
                attempt.assistance_level = step.kind
                attempt.revision += 1
                # Close/materialize the old phase before inserting another open phase.
                session.flush()
                if operation != "solution":
                    attempt.prior_phase_elapsed_ms += phase.active_elapsed_ms
                    phase = AttemptPhase(
                        attempt_id=attempt_id,
                        phase_number=phase.phase_number + 1,
                        kind="assistance",
                        started_at=now,
                        budget_seconds=step.next_budget_seconds,
                        active_elapsed_ms=0,
                        running_since=now if attempt.lifecycle_state == "active" else None,
                    )
                    session.add(phase)
                grant_id = uuid4()
                granted = GrantedAssistance.model_validate(
                    {
                        "id": grant_id,
                        "step_id": step.id,
                        "position": step.position,
                        "kind": step.kind,
                        "content": step.content,
                        "granted_at": now,
                        "reason": trigger,
                        "solution": solution,
                    }
                )
                attempts.append_event(
                    attempt,
                    "assistance_granted",
                    now,
                    {
                        "grant_id": str(grant_id),
                        "step_id": str(step.id),
                        "reason": trigger,
                        "phase_number": phase.phase_number,
                    },
                    command_id,
                )
                session.flush()
                response = AssistanceResponse(
                    grant=granted,
                    attempt=self.attempts.snapshot(
                        attempts, attempt, phase, now, policy_record.version_code
                    ),
                ).model_dump(mode="json")
                session.add(
                    AssistanceGrant(
                        id=grant_id,
                        attempt_id=attempt_id,
                        step_id=step.id,
                        granted_at=now,
                        reason=trigger,
                        command_id=command_id,
                        operation=operation,
                        request_key=key,
                        request_hash=digest,
                        response_json=response,
                    )
                )
                session.flush()
            logger.info(
                "assistance_granted",
                extra={
                    "attempt_id": str(attempt_id),
                    "grant_id": str(grant_id),
                    "assistance_kind": step.kind,
                    "reason_code": trigger,
                    "revision": response["attempt"]["revision"],
                    "policy_version": policy_record.version_code,
                },
            )
            return CommandResult(response)
        except IntegrityError:
            raise ContentError(
                "ATTEMPT_CONFLICT",
                "Assistance conflicts with stored history; reload before retrying.",
            ) from None

    def history(self, principal: Principal, attempt_id: UUID) -> AssistanceHistory:
        with self.factory.begin() as session:
            self.attempts.authorize(session, principal)
            AttemptRepository(session).owned_attempt(principal.user_id, attempt_id)
            grants = AssistanceRepository(session).history(attempt_id)
            return AssistanceHistory(
                attempt_id=attempt_id,
                grants=[
                    GrantedAssistance.model_validate(grant.response_json["grant"])
                    for grant in grants
                ],
            )
