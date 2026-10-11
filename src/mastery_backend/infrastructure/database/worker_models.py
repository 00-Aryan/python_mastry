"""Local worker authority/readiness and append-only signed execution provenance."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mastery_backend.infrastructure.database.content_models import Base


class ExecutionWorkerIdentity(Base):
    __tablename__ = "execution_worker_identities"
    __table_args__ = (CheckConstraint("length(credential_hash) = 64", name="ck_worker_hash"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    credential_hash: Mapped[str] = mapped_column(String(64))
    runner_identity: Mapped[str] = mapped_column(String(100), unique=True)
    evaluator_policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluator_policy_versions.id", ondelete="RESTRICT")
    )
    revoked: Mapped[bool] = mapped_column(default=False)
    ready_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationRunProvenance(Base):
    __tablename__ = "evaluation_run_provenance"
    __table_args__ = (
        CheckConstraint("generation BETWEEN 1 AND 3", name="ck_provenance_generation"),
        CheckConstraint("length(signature) = 64", name="ck_provenance_signature"),
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_jobs.id", ondelete="RESTRICT"), primary_key=True
    )
    generation: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[UUID] = mapped_column(
        ForeignKey("execution_worker_identities.id", ondelete="RESTRICT")
    )
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    signature: Mapped[str] = mapped_column(String(64))
