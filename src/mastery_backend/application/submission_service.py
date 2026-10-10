"""Owned receipt transactions and immutable acceptance-time evidence."""

import base64
import binascii
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.attempt_service import AttemptService
from mastery_backend.application.clock import Clock
from mastery_backend.application.command_replay import CommandResult, request_hash
from mastery_backend.application.evaluation_transactions import check_pending_assessment
from mastery_backend.domain.content import ContentError, ContentValue
from mastery_backend.domain.identity import Principal
from mastery_backend.domain.submission_records import (
    SubmissionDetail,
    SubmissionEvidence,
    SubmissionListQuery,
    SubmissionPage,
    SubmissionSummary,
)
from mastery_backend.domain.submissions import (
    SubmissionPurpose,
    validate_submission_lifecycle,
    validate_submission_source,
)
from mastery_backend.domain.timer_policy import normalized_server_time, project_timer
from mastery_backend.infrastructure.database.attempt_repository import AttemptRepository
from mastery_backend.infrastructure.database.submission_models import Submission
from mastery_backend.infrastructure.database.submission_repository import SubmissionRepository
from mastery_backend.infrastructure.observability.logging import logger


class SubmissionCursor(ContentValue):
    upper_sequence: int
    after_sequence: int
    expires_at: datetime
    filter_hash: str


class SubmissionService:
    def __init__(
        self, factory: sessionmaker[Session], clock: Clock, maximum_code_bytes: int
    ) -> None:
        self.factory = factory
        self.attempts = AttemptService(factory, clock)
        self.clock = clock
        self.maximum_code_bytes = maximum_code_bytes

    @staticmethod
    def detail(submission: Submission) -> SubmissionDetail:
        summary = SubmissionSummary.model_validate(submission, from_attributes=True)
        return SubmissionDetail.model_validate(
            {
                **summary.model_dump(),
                "source_code": submission.source_code,
                "evidence": submission.evidence_json,
            }
        )

    def accept(
        self,
        principal: Principal,
        attempt_id: UUID,
        key: str,
        source_code: str,
        purpose: SubmissionPurpose,
        expected_revision: int,
    ) -> CommandResult:
        digest = request_hash(
            {"source_code": source_code, "purpose": purpose, "expected_revision": expected_revision}
        )
        try:
            with self.factory.begin() as session:
                self.attempts.authorize(session, principal)
                attempts = AttemptRepository(session)
                attempt = attempts.owned_attempt(principal.user_id, attempt_id)
                receipts = SubmissionRepository(session)
                replay = receipts.replay(attempt_id, key)
                if replay is not None:
                    if replay.request_hash != digest:
                        raise ContentError(
                            "IDEMPOTENCY_CONFLICT", "Submission key was used with different input."
                        )
                    return CommandResult(
                        self.detail(replay).model_dump(mode="json"),
                        201,
                        f"/api/v1/submissions/{replay.id}",
                        True,
                    )
                if attempt.revision != expected_revision:
                    raise ContentError("STALE_REVISION", "Attempt changed; reload before retrying.")
                validate_submission_lifecycle(attempt.lifecycle_state)
                code_hash, source_bytes = validate_submission_source(
                    source_code, self.maximum_code_bytes
                )
                phase = attempts.phase(attempt_id)
                now = normalized_server_time(self.clock.now())
                if purpose == "assessment":
                    check_pending_assessment(session, attempt_id, now)
                command_id = uuid4()
                self.attempts.reconcile_expiry(attempts, attempt, phase, now, command_id)
                projection = project_timer(self.attempts.timer_state(attempt, phase), now)
                self.attempts.materialize(attempt, phase, projection, now)
                attempt.total_running_since = now if attempt.lifecycle_state == "active" else None
                if phase.running_since is not None:
                    phase.running_since = now
                attempt.revision += 1
                submission_id = uuid4()
                attempts.append_event(
                    attempt,
                    "submission_received",
                    now,
                    {"submission_id": str(submission_id), "purpose": purpose},
                    command_id,
                )
                session.flush()
                evidence = SubmissionEvidence(
                    attempt=self.attempts.snapshot(attempts, attempt, phase, now),
                    phase_id=phase.id,
                    assistance_grant_ids=receipts.grant_ids(attempt_id),
                )
                submission = Submission(
                    id=submission_id,
                    attempt_id=attempt_id,
                    question_version_id=attempt.question_version_id,
                    policy_version_id=attempt.policy_version_id,
                    phase_id=phase.id,
                    source_code=source_code,
                    code_hash=code_hash,
                    source_bytes=source_bytes,
                    accepted_code_limit_bytes=self.maximum_code_bytes,
                    purpose=purpose,
                    accepted_at=now,
                    accepted_event_sequence=attempt.last_event_sequence,
                    attempt_revision=attempt.revision,
                    evidence_json=evidence.model_dump(mode="json"),
                    request_key=key,
                    request_hash=digest,
                )
                receipts.insert(submission)
                result = CommandResult(
                    self.detail(submission).model_dump(mode="json"),
                    201,
                    f"/api/v1/submissions/{submission_id}",
                )
            logger.info(
                "submission_received",
                extra={
                    "attempt_id": str(attempt_id),
                    "submission_id": str(submission_id),
                    "revision": attempt.revision,
                    "policy_version": evidence.attempt.policy_version,
                    "reason_code": "SOURCE_RECEIVED",
                },
            )
            return result
        except IntegrityError:
            raise ContentError(
                "SUBMISSION_CONFLICT",
                "Submission conflicts with stored history; reload before retrying.",
            ) from None

    def read(self, principal: Principal, submission_id: UUID) -> SubmissionDetail:
        with self.factory.begin() as session:
            self.attempts.authorize(session, principal)
            return self.detail(
                SubmissionRepository(session).owned_detail(principal.user_id, submission_id)
            )

    def list_submissions(
        self, principal: Principal, attempt_id: UUID, query: SubmissionListQuery
    ) -> SubmissionPage:
        digest = request_hash(
            {
                "user_id": str(principal.user_id),
                "attempt_id": str(attempt_id),
                "purpose": query.purpose,
            }
        )
        cursor = None
        if query.cursor:
            try:
                cursor = SubmissionCursor.model_validate_json(
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
                    "INVALID_CURSOR", "Submission cursor is invalid or expired."
                ) from None
        with self.factory.begin() as session:
            self.attempts.authorize(session, principal)
            attempt = AttemptRepository(session).owned_attempt(principal.user_id, attempt_id)
            upper = cursor.upper_sequence if cursor else attempt.last_event_sequence
            rows = SubmissionRepository(session).page(
                attempt_id,
                query.limit,
                query.purpose,
                upper,
                cursor.after_sequence if cursor else None,
            )
            items = rows[: query.limit]
            next_cursor = None
            if len(rows) > query.limit:
                next_cursor = base64.urlsafe_b64encode(
                    SubmissionCursor(
                        upper_sequence=upper,
                        after_sequence=items[-1].accepted_event_sequence,
                        expires_at=cursor.expires_at
                        if cursor
                        else datetime.now(UTC) + timedelta(days=1),
                        filter_hash=digest,
                    )
                    .model_dump_json()
                    .encode()
                ).decode()
            return SubmissionPage(
                items=[
                    SubmissionSummary.model_validate(row, from_attributes=True) for row in items
                ],
                next_cursor=next_cursor,
            )
