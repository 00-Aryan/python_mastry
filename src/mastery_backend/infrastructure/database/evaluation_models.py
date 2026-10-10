"""Evaluation pins, durable dispatch intent, current projection and immutable history."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
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

from mastery_backend.infrastructure.database.content_models import Base


class EvaluationPolicyVersion(Base):
    __tablename__ = "evaluator_policy_versions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    version_code: Mapped[str] = mapped_column(String(100), unique=True)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSONB)


class TestBundle(Base):
    __tablename__ = "evaluation_test_bundles"
    __table_args__ = (
        UniqueConstraint("question_version_id", "purpose", name="uq_evaluation_bundle"),
        CheckConstraint("purpose IN ('public_run','assessment')", name="ck_bundle_purpose"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    question_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT")
    )
    purpose: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))


class TestBundleMember(Base):
    __tablename__ = "evaluation_test_bundle_members"
    bundle_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_test_bundles.id", ondelete="RESTRICT"), primary_key=True
    )
    test_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_test_cases.id", ondelete="RESTRICT"), primary_key=True
    )


class EvaluationJob(Base):
    __tablename__ = "evaluation_jobs"
    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_evaluation_submission"),
        CheckConstraint(
            "status IN ('pending','running','passed','failed','infrastructure_error')",
            name="ck_evaluation_status",
        ),
        CheckConstraint(
            "category IS NULL OR category IN "
            "('passed','incorrect','syntax_error','resource_limit','infrastructure_error')",
            name="ck_evaluation_category",
        ),
        CheckConstraint(
            "generation >= 0 AND generation <= 3 AND last_sequence > 0",
            name="ck_evaluation_counters",
        ),
        CheckConstraint(
            "(status = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL)"
            " OR (status <> 'running' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_evaluation_lease",
        ),
        CheckConstraint(
            "(status IN ('pending','running') AND finished_at IS NULL AND category IS NULL)"
            " OR (status = 'passed' AND category = 'passed' AND finished_at IS NOT NULL)"
            " OR (status = 'failed' AND category IN ('incorrect','syntax_error',"
            "'resource_limit') AND finished_at IS NOT NULL) OR "
            "(status = 'infrastructure_error' AND category = 'infrastructure_error' "
            "AND finished_at IS NOT NULL)",
            name="ck_evaluation_result",
        ),
        CheckConstraint(
            "deadline_at > requested_at AND next_retry_at >= requested_at",
            name="ck_evaluation_times",
        ),
        Index("ix_evaluation_dispatch", "status", "next_retry_at"),
        Index("ix_evaluation_history", "attempt_id", "requested_event_sequence"),
        Index(
            "ix_evaluation_pending_assessment",
            "attempt_id",
            postgresql_where=text("purpose = 'assessment' AND status IN ('pending','running')"),
            unique=True,
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("attempts.id", ondelete="RESTRICT"))
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id", ondelete="RESTRICT"))
    question_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT")
    )
    policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_policy_versions.id", ondelete="RESTRICT")
    )
    test_bundle_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_test_bundles.id", ondelete="RESTRICT")
    )
    evaluator_policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluator_policy_versions.id", ondelete="RESTRICT")
    )
    purpose: Mapped[str] = mapped_column(String(16))
    runner_identity: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(32))
    requested_event_sequence: Mapped[int] = mapped_column(Integer)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    generation: Mapped[int] = mapped_column(Integer, default=0)
    last_sequence: Mapped[int] = mapped_column(Integer, default=1)
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationDispatchIntent(Base):
    __tablename__ = "evaluation_dispatch_intents"
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_jobs.id", ondelete="RESTRICT"), primary_key=True
    )
    request_id: Mapped[str | None] = mapped_column(String(128))


class EvaluationEvent(Base):
    __tablename__ = "evaluation_events"
    __table_args__ = (
        CheckConstraint(
            "sequence_number > 0 AND generation >= 0", name="ck_evaluation_event_count"
        ),
        CheckConstraint(
            "state IN ('pending','running','passed','failed','infrastructure_error')",
            name="ck_evaluation_event_state",
        ),
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_jobs.id", ondelete="RESTRICT"), primary_key=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(32))
    reason_code: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    generation: Mapped[int] = mapped_column(Integer)


class EvaluationRequestReceipt(Base):
    __tablename__ = "evaluation_request_receipts"
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="RESTRICT"), primary_key=True
    )
    request_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("evaluation_jobs.id", ondelete="RESTRICT"))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
