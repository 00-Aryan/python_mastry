"""Persist reference artifacts and their immutable evaluator configuration; never commit."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from mastery_backend.domain.content import ContentError
from mastery_backend.infrastructure.database.evaluation_models import EvaluationPolicyVersion
from mastery_backend.infrastructure.database.publication_models import (
    PublicationVerificationArtifact,
)


def append_artifact(
    session: Session, artifact: PublicationVerificationArtifact, configuration: dict[str, object]
) -> None:
    session.execute(
        insert(EvaluationPolicyVersion)
        .values(
            id=artifact.evaluator_policy_version_id,
            version_code="publication-v1-" + artifact.evaluator_policy_version_id.hex,
            configuration_json=configuration,
        )
        .on_conflict_do_nothing(index_elements=[EvaluationPolicyVersion.id])
    )
    policy = session.get(EvaluationPolicyVersion, artifact.evaluator_policy_version_id)
    if policy is None or policy.configuration_json != configuration:
        raise ContentError("VERIFICATION_MISMATCH", "Evaluator policy does not match.")
    session.add(artifact)
    session.flush()
