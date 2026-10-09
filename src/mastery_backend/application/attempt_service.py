"""Owned attempt transactions, clock reconciliation and durable lifecycle commands."""

import base64
import binascii
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.clock import Clock
from mastery_backend.application.command_replay import (
    CommandResult,
    record_command,
    replay_command,
    request_hash,
)
from mastery_backend.domain.attempt_records import AttemptListQuery, AttemptPage, AttemptSnapshot
from mastery_backend.domain.content import ContentError, ContentValue
from mastery_backend.domain.content_records import PublicQuestionVersion
from mastery_backend.domain.identity import Principal, require_learner
from mastery_backend.domain.timer_policy import (
    AttemptCommand,
    TimerProjection,
    TimerState,
    normalized_server_time,
    project_timer,
    validate_transition,
)
from mastery_backend.infrastructure.database.attempt_models import (
    Attempt,
    AttemptPhase,
    UserQuestionFamilyHistory,
)
from mastery_backend.infrastructure.database.attempt_repository import AttemptRepository
from mastery_backend.infrastructure.database.catalog_repository import CatalogRepository
from mastery_backend.infrastructure.database.identity_repository import load_principal
from mastery_backend.infrastructure.observability.logging import logger


class AttemptCursor(ContentValue):
    attempt_id: UUID
    started_at: datetime
    expires_at: datetime
    filter_hash: str


class AttemptService:
    def __init__(self, factory: sessionmaker[Session], clock: Clock) -> None:
        self.factory = factory
        self.clock = clock

    @staticmethod
    def authorize(session: Session, principal: Principal) -> None:
        require_learner(principal)
        require_learner(load_principal(session, principal.user_id, lock=True))

    @staticmethod
    def timer_state(attempt: Attempt, phase: AttemptPhase) -> TimerState:
        return TimerState(
            phase.budget_seconds,
            phase.active_elapsed_ms,
            phase.running_since,
            attempt.total_active_elapsed_ms,
            attempt.total_running_since,
            phase.expired_at,
            attempt.last_reconciled_at,
        )

    def reconcile_expiry(
        self,
        repository: AttemptRepository,
        attempt: Attempt,
        phase: AttemptPhase,
        now: datetime,
        command_id: UUID | None,
    ) -> None:
        projection = project_timer(self.timer_state(attempt, phase), now)
        if phase.expired_at is not None or projection.expired_at is None:
            return
        phase.active_elapsed_ms = projection.phase_elapsed_ms
        phase.expired_at = projection.expired_at
        phase.closed_at = projection.expired_at
        phase.running_since = None
        attempt.total_active_elapsed_ms = projection.total_elapsed_ms
        attempt.total_running_since = now if attempt.lifecycle_state == "active" else None
        attempt.last_reconciled_at = now
        attempt.independent_interval_ended_at = projection.expired_at
        attempt.independent_end_reason = "expired"
        attempt.revision += 1
        repository.append_event(
            attempt,
            "expired",
            projection.expired_at,
            {"observed_at": now.isoformat(), "budget_seconds": phase.budget_seconds},
            command_id,
        )

    def snapshot(
        self,
        repository: AttemptRepository,
        attempt: Attempt,
        phase: AttemptPhase,
        now: datetime,
        policy_code: str | None = None,
    ) -> AttemptSnapshot:
        if policy_code is None:
            policy_code = repository.policy(attempt.policy_version_id)[0].version_code
        projection = project_timer(self.timer_state(attempt, phase), now)
        return AttemptSnapshot.model_validate(
            {
                "id": attempt.id,
                "question_version_id": attempt.question_version_id,
                "policy_version_id": attempt.policy_version_id,
                "policy_version": policy_code,
                "mode": attempt.mode,
                "lifecycle_state": attempt.lifecycle_state,
                "assistance_level": attempt.assistance_level,
                "assistance_eligible": phase.expired_at is not None
                and attempt.lifecycle_state in {"active", "paused"},
                "revision": attempt.revision,
                "started_at": attempt.started_at,
                "finished_at": attempt.finished_at,
                "independent_interval_ended_at": attempt.independent_interval_ended_at,
                "independent_end_reason": attempt.independent_end_reason,
                "timing_accommodated": attempt.timing_accommodated,
                "family_previously_attempted": attempt.family_previously_attempted,
                "total_active_elapsed_ms": projection.total_elapsed_ms,
                "overdue_active_elapsed_ms": projection.overdue_ms,
                "timer": {
                    "phase_number": phase.phase_number,
                    "phase_started_at": phase.started_at,
                    "budget_seconds": phase.budget_seconds,
                    "active_elapsed_ms": projection.phase_elapsed_ms,
                    "remaining_ms": projection.remaining_ms,
                    "server_now": now,
                    "running_since": phase.running_since,
                    "expired_at": phase.expired_at,
                },
            }
        )

    def start(
        self, principal: Principal, key: str, version_id: UUID, mode: str, budget_seconds: int
    ) -> CommandResult:
        operation = "POST /api/v1/attempts"
        digest = request_hash(
            {
                "question_version_id": str(version_id),
                "mode": mode,
                "independent_budget_seconds": budget_seconds,
            }
        )
        try:
            with self.factory.begin() as session:
                self.authorize(session, principal)
                replay = replay_command(session, principal, operation, key, digest)
                if replay:
                    return replay
                repository = AttemptRepository(session)
                policy_record, policy = repository.policy()
                policy.validate_budget(budget_seconds)
                if mode not in policy.allowed_modes:
                    raise ContentError(
                        "INVALID_MODE", "Mode is not released in the pinned timer policy."
                    )
                family_id = repository.start_context(version_id, mode)
                now = normalized_server_time(self.clock.now())
                history = repository.family_history(principal.user_id, family_id)
                if history is not None and now < history.first_attempt_at:
                    raise ContentError(
                        "CLOCK_UNAVAILABLE", "Server clock precedes stored family history."
                    )
                attempt = Attempt(
                    user_id=principal.user_id,
                    question_version_id=version_id,
                    policy_version_id=policy_record.id,
                    mode=mode,
                    lifecycle_state="active",
                    started_at=now,
                    total_running_since=now,
                    last_reconciled_at=now,
                    family_previously_attempted=history is not None,
                )
                session.add(attempt)
                session.flush()
                phase = AttemptPhase(
                    attempt_id=attempt.id,
                    started_at=now,
                    budget_seconds=budget_seconds,
                    running_since=now,
                )
                session.add(phase)
                if history is None:
                    session.add(
                        UserQuestionFamilyHistory(
                            user_id=principal.user_id, family_id=family_id, first_attempt_at=now
                        )
                    )
                repository.append_event(
                    attempt, "started", now, {"budget_seconds": budget_seconds}, uuid4()
                )
                session.flush()
                result = CommandResult(
                    self.snapshot(
                        repository, attempt, phase, now, policy_record.version_code
                    ).model_dump(mode="json"),
                    201,
                    f"/api/v1/attempts/{attempt.id}",
                )
                record_command(session, principal, operation, key, digest, result)
            logger.info(
                "attempt_started",
                extra={
                    "attempt_id": str(attempt.id),
                    "revision": attempt.revision,
                    "policy_version": policy_record.version_code,
                    "state_after": "active",
                },
            )
            return result
        except IntegrityError:
            raise ContentError(
                "ATTEMPT_CONFLICT", "Attempt conflicts with stored history; reload before retrying."
            ) from None

    def read(self, principal: Principal, attempt_id: UUID) -> AttemptSnapshot:
        with self.factory.begin() as session:
            self.authorize(session, principal)
            repository = AttemptRepository(session)
            attempt = repository.owned_attempt(principal.user_id, attempt_id)
            phase = repository.phase(attempt.id)
            now = normalized_server_time(self.clock.now())
            self.reconcile_expiry(repository, attempt, phase, now, None)
            return self.snapshot(repository, attempt, phase, now)

    def public_question(self, principal: Principal, attempt_id: UUID) -> PublicQuestionVersion:
        with self.factory.begin() as session:
            self.authorize(session, principal)
            attempt = AttemptRepository(session).owned_attempt(principal.user_id, attempt_id)
            return CatalogRepository(session).public_version(
                attempt.question_version_id, include_archived=True
            )

    def command(
        self,
        principal: Principal,
        key: str,
        attempt_id: UUID,
        command: AttemptCommand,
        expected_revision: int,
        additional_seconds: int | None = None,
        reason: str | None = None,
    ) -> CommandResult:
        operation = f"POST /api/v1/attempts/{attempt_id}/{command}"
        payload: dict[str, Any] = {"expected_revision": expected_revision}
        if command in {"extend", "defer", "abandon"}:
            payload["reason"] = reason
        if command == "extend":
            payload["additional_budget_seconds"] = additional_seconds
        digest = request_hash(payload)
        try:
            with self.factory.begin() as session:
                self.authorize(session, principal)
                repository = AttemptRepository(session)
                attempt = repository.owned_attempt(principal.user_id, attempt_id)
                replay = replay_command(session, principal, operation, key, digest)
                if replay:
                    return replay
                if attempt.revision != expected_revision:
                    raise ContentError("STALE_REVISION", "Attempt changed; reload before retrying.")
                phase = repository.phase(attempt.id)
                now = normalized_server_time(self.clock.now())
                command_id = uuid4()
                self.reconcile_expiry(repository, attempt, phase, now, command_id)
                state_before = attempt.lifecycle_state
                next_state = validate_transition(state_before, command, phase.expired_at)
                policy_record, policy = repository.policy(attempt.policy_version_id)
                projection = project_timer(self.timer_state(attempt, phase), now)
                if command == "extend":
                    if additional_seconds is None:
                        raise ContentError("INVALID_BUDGET", "Supply additional budget seconds.")
                    policy.validate_extension(phase.budget_seconds, additional_seconds)
                    phase.budget_seconds += additional_seconds
                self.materialize(attempt, phase, projection, now)
                attempt.lifecycle_state = next_state
                attempt.total_running_since = now if next_state == "active" else None
                phase.running_since = (
                    now if next_state == "active" and phase.closed_at is None else None
                )
                if command in {"defer", "abandon"}:
                    attempt.finished_at = now
                    if phase.closed_at is None:
                        phase.closed_at = now
                    if attempt.independent_interval_ended_at is None:
                        attempt.independent_interval_ended_at = now
                        attempt.independent_end_reason = (
                            "deferred" if command == "defer" else "abandoned"
                        )
                if attempt.mode == "assessment" and command in {"pause", "extend"}:
                    attempt.timing_accommodated = True
                attempt.revision += 1
                event_type = {
                    "pause": "paused",
                    "resume": "resumed",
                    "extend": "extended",
                    "defer": "deferred",
                    "abandon": "abandoned",
                }[command]
                repository.append_event(attempt, event_type, now, payload, command_id)
                session.flush()
                result = CommandResult(
                    self.snapshot(
                        repository, attempt, phase, now, policy_record.version_code
                    ).model_dump(mode="json")
                )
                record_command(session, principal, operation, key, digest, result)
            logger.info(
                "attempt_transition",
                extra={
                    "attempt_id": str(attempt_id),
                    "state_before": state_before,
                    "state_after": next_state,
                    "revision": result.body["revision"],
                    "policy_version": policy_record.version_code,
                },
            )
            return result
        except IntegrityError:
            raise ContentError(
                "ATTEMPT_CONFLICT", "Attempt conflicts with stored history; reload before retrying."
            ) from None

    @staticmethod
    def materialize(
        attempt: Attempt, phase: AttemptPhase, projection: TimerProjection, now: datetime
    ) -> None:
        attempt.total_active_elapsed_ms = projection.total_elapsed_ms
        phase.active_elapsed_ms = projection.phase_elapsed_ms
        attempt.last_reconciled_at = now

    def list_attempts(self, principal: Principal, query: AttemptListQuery) -> AttemptPage:
        digest = request_hash(
            {
                "user_id": str(principal.user_id),
                **query.model_dump(mode="json", exclude={"cursor", "limit"}),
            }
        )
        cursor = None
        if query.cursor:
            try:
                cursor = AttemptCursor.model_validate_json(
                    base64.b64decode(query.cursor, altchars=b"-_", validate=True)
                )
                if (
                    cursor.started_at.tzinfo is None
                    or cursor.expires_at.tzinfo is None
                    or cursor.expires_at <= datetime.now(UTC)
                    or cursor.filter_hash != digest
                ):
                    raise ValueError("Invalid cursor")
            except (ValueError, binascii.Error):
                raise ContentError(
                    "INVALID_CURSOR", "Attempt cursor is invalid or expired."
                ) from None
        with self.factory.begin() as session:
            self.authorize(session, principal)
            repository = AttemptRepository(session)
            rows = repository.page(
                principal.user_id, query, (cursor.started_at, cursor.attempt_id) if cursor else None
            )
            items = rows[: query.limit]
            phases = repository.phases(items)
            policy_codes = repository.policy_codes(items)
            now = normalized_server_time(self.clock.now())
            snapshots = []
            for attempt in items:
                phase = phases[attempt.id]
                self.reconcile_expiry(repository, attempt, phase, now, None)
                snapshots.append(
                    self.snapshot(
                        repository, attempt, phase, now, policy_codes[attempt.policy_version_id]
                    )
                )
            next_cursor = None
            if len(rows) > query.limit:
                last = items[-1]
                next_cursor = base64.urlsafe_b64encode(
                    AttemptCursor(
                        attempt_id=last.id,
                        started_at=last.started_at,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                        filter_hash=digest,
                    )
                    .model_dump_json()
                    .encode()
                ).decode()
            return AttemptPage(items=snapshots, next_cursor=next_cursor)
