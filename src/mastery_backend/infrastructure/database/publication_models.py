"""Append-only authored snapshots and trusted reference-verification receipts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mastery_backend.infrastructure.database.content_models import Base


class PublicationVerificationArtifact(Base):
    __tablename__ = "publication_verification_artifacts"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_publication_artifact_revision"),
        CheckConstraint(
            "octet_length(snapshot_bytes) BETWEEN 1 AND 1048576 AND "
            "content_hash = encode(sha256(snapshot_bytes), 'hex')",
            name="ck_publication_artifact_snapshot",
        ),
        CheckConstraint(
            "bundle_hash ~ '^[a-f0-9]{64}$' AND reference_hash ~ '^[a-f0-9]{64}$'",
            name="ck_publication_artifact_hashes",
        ),
        CheckConstraint(
            "verifier_identity = 'local-reference-verifier' AND "
            "verifier_version IN ('reference-v1','quality-v2')",
            name="ck_publication_artifact_verifier",
        ),
        CheckConstraint(
            "jsonb_typeof(result_json) = 'object' AND octet_length(result_json::text) <= 512",
            name="ck_publication_artifact_result",
        ),
        CheckConstraint(
            "jsonb_typeof(result_json->'outcome') = 'string' AND "
            "jsonb_typeof(result_json->'checked_cases') = 'number' AND "
            "jsonb_typeof(result_json->'total_cases') = 'number' AND "
            "result_json ?& ARRAY['outcome','checked_cases','total_cases'] AND "
            "result_json - ARRAY['outcome','checked_cases','total_cases'] = '{}'::jsonb AND "
            "result_json->>'outcome' IN ('passed','incorrect','syntax_error','runtime_error',"
            "'resource_limit','infrastructure_error') AND "
            "(result_json->>'total_cases')::integer BETWEEN 1 AND 64 AND "
            "(result_json->>'checked_cases')::integer BETWEEN 0 AND "
            "(result_json->>'total_cases')::integer AND "
            "(result_json->>'outcome' <> 'passed' OR "
            "result_json->>'checked_cases' = result_json->>'total_cases')",
            name="ck_publication_artifact_counts",
        ),
        Index("ix_publication_artifact_version", "question_version_id", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    question_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT")
    )
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    revision: Mapped[int]
    snapshot_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    content_hash: Mapped[str] = mapped_column(String(64))
    bundle_hash: Mapped[str] = mapped_column(String(64))
    reference_hash: Mapped[str] = mapped_column(String(64))
    evaluator_policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluator_policy_versions.id", ondelete="RESTRICT")
    )
    verifier_identity: Mapped[str] = mapped_column(String(100))
    verifier_version: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONB)


class PublicationQualityEvidence(Base):
    __tablename__ = "publication_quality_evidence"
    __table_args__ = (
        CheckConstraint(
            "reason_code IN ('PASSED','INVALID_CONTRACT','INVALID_CANDIDATES',"
            "'REFERENCE_FAILED','WEAK_SUITE','INFRASTRUCTURE_ERROR','RESOURCE_LIMIT')",
            name="ck_quality_reason",
        ),
        CheckConstraint(
            "total_candidates BETWEEN 0 AND 8 AND killed_candidates BETWEEN 0 AND "
            "total_candidates AND executions BETWEEN 0 AND 256",
            name="ck_quality_counts",
        ),
        CheckConstraint(
            "reason_code <> 'PASSED' OR (total_candidates >= 2 AND "
            "killed_candidates = total_candidates AND executions >= 2 + 2 * total_candidates)",
            name="ck_quality_passed",
        ),
    )
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("publication_verification_artifacts.id", ondelete="RESTRICT"), primary_key=True
    )
    reason_code: Mapped[str] = mapped_column(String(32))
    total_candidates: Mapped[int]
    killed_candidates: Mapped[int]
    executions: Mapped[int]
