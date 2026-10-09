"""Append-only stage grants and indefinite, attempt-scoped command receipts."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mastery_backend.infrastructure.database.content_models import Base


class AssistanceGrant(Base):
    __tablename__ = "assistance_grants"
    __table_args__ = (
        UniqueConstraint("attempt_id", "step_id", name="uq_assistance_grant_step"),
        UniqueConstraint(
            "attempt_id", "operation", "request_key", name="uq_assistance_grant_request"
        ),
        CheckConstraint("operation IN ('next','solution')", name="ck_assistance_operation"),
        CheckConstraint(
            "reason IN ('budget_expired','learner_request','solution_escape')",
            name="ck_assistance_reason",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("attempts.id", ondelete="RESTRICT"))
    step_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_assistance_steps.id", ondelete="RESTRICT")
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(32))
    command_id: Mapped[UUID] = mapped_column()
    operation: Mapped[str] = mapped_column(String(16))
    request_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
