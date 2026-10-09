"""Immutable source, acceptance evidence and indefinite attempt-scoped retry keys."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mastery_backend.infrastructure.database.content_models import Base


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("attempt_id", "request_key", name="uq_submission_request"),
        UniqueConstraint("attempt_id", "accepted_event_sequence", name="uq_submission_event"),
        ForeignKeyConstraint(
            ["attempt_id", "accepted_event_sequence"],
            ["attempt_events.attempt_id", "attempt_events.sequence_number"],
            ondelete="RESTRICT",
            name="fk_submission_event",
        ),
        CheckConstraint("purpose IN ('public_run','assessment')", name="ck_submission_purpose"),
        CheckConstraint(
            "source_bytes > 0 AND source_bytes <= accepted_code_limit_bytes "
            "AND source_bytes = octet_length(source_code)",
            name="ck_submission_bytes",
        ),
        CheckConstraint(
            "code_hash = encode(sha256(convert_to(source_code, 'UTF8')), 'hex')",
            name="ck_submission_hash",
        ),
        CheckConstraint(
            "attempt_revision > 0 AND accepted_event_sequence > 0", name="ck_submission_counters"
        ),
        Index("ix_submission_history", "attempt_id", "accepted_event_sequence"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("attempts.id", ondelete="RESTRICT"))
    question_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT")
    )
    policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_policy_versions.id", ondelete="RESTRICT")
    )
    phase_id: Mapped[UUID] = mapped_column(ForeignKey("attempt_phases.id", ondelete="RESTRICT"))
    source_code: Mapped[str] = mapped_column(Text)
    code_hash: Mapped[str] = mapped_column(String(64))
    source_bytes: Mapped[int] = mapped_column(Integer)
    accepted_code_limit_bytes: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(16))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_event_sequence: Mapped[int] = mapped_column(Integer)
    attempt_revision: Mapped[int] = mapped_column(Integer)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    request_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
