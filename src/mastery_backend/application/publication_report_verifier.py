"""Read authenticated local database evidence; never run code or trust an HTTP receipt."""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.clock import Clock
from mastery_backend.application.publication_verification import VerificationProof
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.evaluations import EvaluationPolicy
from mastery_backend.domain.publication_artifacts import (
    PublicationArtifactSummary,
    PublicationSnapshot,
    validate_publication_artifact,
)
from mastery_backend.domain.question_quality import QualityCheckResult
from mastery_backend.infrastructure.database.evaluation_models import EvaluationPolicyVersion
from mastery_backend.infrastructure.database.publication_models import (
    PublicationQualityEvidence,
    PublicationVerificationArtifact,
)
from mastery_backend.infrastructure.database.publication_repository import latest_artifact


class StoredReferenceVerifier:
    def __init__(
        self, factory: sessionmaker[Session], clock: Clock, approved_policy_id: UUID
    ) -> None:
        self.factory, self.clock, self.approved_policy_id = factory, clock, approved_policy_id

    def _proof(
        self, session: Session, snapshot: PublicationSnapshot, row: PublicationVerificationArtifact
    ) -> VerificationProof:
        if row.verifier_version == "reference-v1":
            raise ContentError(
                "VERIFICATION_UNAVAILABLE", "Fresh quality verification is required."
            )
        quality_row = session.get(PublicationQualityEvidence, row.id)
        policy = session.get(EvaluationPolicyVersion, row.evaluator_policy_version_id)
        if policy is None or policy.version_code != "publication-v2-" + self.approved_policy_id.hex:
            raise ContentError(
                "VERIFICATION_UNAVAILABLE", "An approved verifier policy is unavailable."
            )
        try:
            configuration = EvaluationPolicy.model_validate(policy.configuration_json)
        except ValidationError:
            raise ContentError("VERIFICATION_UNAVAILABLE", "Unsupported verifier policy.") from None
        try:
            report = PublicationArtifactSummary.model_validate(
                {
                    **{
                        field: getattr(row, field)
                        for field in PublicationArtifactSummary.model_fields
                        if field not in {"result", "quality"}
                    },
                    "result": row.result_json,
                    "quality": QualityCheckResult.model_validate(
                        {
                            "reason_code": quality_row.reason_code,
                            "total_candidates": quality_row.total_candidates,
                            "killed_candidates": quality_row.killed_candidates,
                            "executions": quality_row.executions,
                        }
                    )
                    if quality_row is not None
                    else None,
                }
            )
            validate_publication_artifact(
                report,
                row.snapshot_bytes,
                snapshot,
                self.approved_policy_id,
                configuration,
                self.clock.now(),
            )
        except ValidationError:
            raise ContentError("VERIFICATION_MISMATCH", "Invalid reference verification.") from None
        return VerificationProof(
            content_hash=report.content_hash,
            verifier_version=report.verifier_version,
            verification_id=str(report.id),
        )

    def verify(self, snapshot: PublicationSnapshot) -> VerificationProof:
        # The caller has already released its authoring transaction and all locks.
        with self.factory.begin() as session:
            row = latest_artifact(session, snapshot.question_version_id)
            if row is None:
                raise ContentError(
                    "VERIFICATION_UNAVAILABLE", "Verify this draft before publishing."
                )
            return self._proof(session, snapshot, row)

    def recheck(
        self, session: Session, snapshot: PublicationSnapshot, proof: VerificationProof
    ) -> None:
        # Pure validation + database reads only, inside the caller's final short transaction.
        row = latest_artifact(session, snapshot.question_version_id)
        if row is None or str(row.id) != proof.verification_id:
            raise ContentError(
                "VERIFICATION_STALE", "Reference verification changed; retry publication."
            )
        if self._proof(session, snapshot, row) != proof:
            raise ContentError("VERIFICATION_MISMATCH", "Verification does not match this content.")
