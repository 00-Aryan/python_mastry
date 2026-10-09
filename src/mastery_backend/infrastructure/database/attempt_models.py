"""Normalized attempts, phases, immutable policies and ordered lifecycle facts."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mastery_backend.domain.timer_policy import Lifecycle
from mastery_backend.infrastructure.database.content_models import Base


class LearningPolicyVersion(Base):
    __tablename__ = "learning_policy_versions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version_code: Mapped[str] = mapped_column(String(64), unique=True)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint("mode IN ('practice','assessment')", name="ck_attempt_mode"),
        CheckConstraint(
            "lifecycle_state IN ('active','paused','completed','deferred','abandoned')",
            name="ck_attempt_lifecycle",
        ),
        CheckConstraint("assistance_level = 'none'", name="ck_attempt_assistance"),
        CheckConstraint(
            "revision > 0 AND last_event_sequence >= 0 AND total_active_elapsed_ms >= 0",
            name="ck_attempt_counters",
        ),
        CheckConstraint(
            "(lifecycle_state IN ('active','paused') AND finished_at IS NULL) OR "
            "(lifecycle_state IN ('completed','deferred','abandoned') AND finished_at IS "
            "NOT NULL)",
            name="ck_attempt_finished",
        ),
        CheckConstraint(
            "(lifecycle_state = 'active' AND total_running_since IS NOT NULL) OR "
            "(lifecycle_state <> 'active' AND total_running_since IS NULL)",
            name="ck_attempt_running",
        ),
        CheckConstraint(
            "(independent_interval_ended_at IS NULL AND independent_end_reason IS NULL) OR "
            "(independent_interval_ended_at IS NOT NULL AND independent_end_reason IS NOT NULL "
            "AND independent_end_reason IN "
            "('expired','deferred','abandoned'))",
            name="ck_attempt_independent_end",
        ),
        CheckConstraint(
            "last_reconciled_at >= started_at AND (finished_at IS NULL OR finished_at >= "
            "started_at)",
            name="ck_attempt_timestamps",
        ),
        Index("ix_attempt_owner_history", "user_id", "started_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    question_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT")
    )
    policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_policy_versions.id", ondelete="RESTRICT")
    )
    mode: Mapped[str] = mapped_column(String(32))
    lifecycle_state: Mapped[Lifecycle] = mapped_column(String(16))
    assistance_level: Mapped[str] = mapped_column(String(32), default="none")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    last_event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_active_elapsed_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    total_running_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reconciled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    independent_interval_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    independent_end_reason: Mapped[str | None] = mapped_column(String(16))
    timing_accommodated: Mapped[bool] = mapped_column(Boolean, default=False)
    family_previously_attempted: Mapped[bool] = mapped_column(Boolean)


class AttemptPhase(Base):
    __tablename__ = "attempt_phases"
    __table_args__ = (
        UniqueConstraint("attempt_id", "phase_number", name="uq_attempt_phase_number"),
        CheckConstraint("phase_number = 0 AND kind = 'independent'", name="ck_phase_kind"),
        CheckConstraint(
            "budget_seconds > 0 AND active_elapsed_ms >= 0 AND active_elapsed_ms <= "
            "budget_seconds::bigint * 1000",
            name="ck_phase_durations",
        ),
        CheckConstraint(
            "expired_at IS NULL OR (closed_at IS NOT NULL AND closed_at = expired_at "
            "AND running_since IS NULL AND "
            "active_elapsed_ms = budget_seconds::bigint * 1000)",
            name="ck_phase_expired",
        ),
        CheckConstraint("closed_at IS NULL OR running_since IS NULL", name="ck_phase_closed"),
        Index(
            "ix_attempt_open_phase",
            "attempt_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("attempts.id", ondelete="RESTRICT"))
    phase_number: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(32), default="independent")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    budget_seconds: Mapped[int] = mapped_column(Integer)
    active_elapsed_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    running_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttemptEvent(Base):
    __tablename__ = "attempt_events"
    __table_args__ = (
        UniqueConstraint("attempt_id", "sequence_number", name="uq_attempt_event_sequence"),
        CheckConstraint("sequence_number > 0", name="ck_attempt_event_sequence"),
        CheckConstraint(
            "event_type IN "
            "('started','paused','resumed','extended','expired','deferred','abandoned')",
            name="ck_attempt_event_type",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("attempts.id", ondelete="RESTRICT"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    command_id: Mapped[UUID | None] = mapped_column()


class UserQuestionFamilyHistory(Base):
    __tablename__ = "user_question_family_history"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_families.id", ondelete="RESTRICT"), primary_key=True
    )
    first_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
