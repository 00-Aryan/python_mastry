"""Pure report validation: no fake execution or correctness certification."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from mastery_backend.domain.content import ContentError, DraftContent, content_snapshot
from mastery_backend.domain.publication_artifacts import (
    PublicationArtifactSummary,
    PublicationSnapshot,
    ReferenceCheckResult,
    bundle_bytes,
    digest,
    reference_evaluator_policy,
    reference_evaluator_policy_id,
    validate_publication_artifact,
)


@pytest.fixture
def evidence(complete_draft):
    content = DraftContent.model_validate(complete_draft)
    snapshot = content_snapshot(content)
    policy = reference_evaluator_policy("1" * 64, "2" * 64)
    policy_id = reference_evaluator_policy_id(policy)
    context = PublicationSnapshot(uuid4(), 1, snapshot, digest(snapshot))
    report = PublicationArtifactSummary(
        id=uuid4(),
        question_version_id=context.question_version_id,
        revision=1,
        content_hash=context.content_hash,
        bundle_hash=digest(bundle_bytes(content)),
        reference_hash=digest(content.solution.reference_code.encode()),
        evaluator_policy_version_id=policy_id,
        verifier_identity="local-reference-verifier",
        verifier_version="reference-v1",
        created_at=datetime(2026, 10, 16, tzinfo=UTC),
        result=ReferenceCheckResult(outcome="passed", checked_cases=2, total_cases=2),
    )
    return report, context, policy


@pytest.mark.parametrize(
    "age,valid",
    [
        (timedelta(), True),
        (timedelta(seconds=86400, microseconds=-1), True),
        (timedelta(seconds=86400), False),
        (timedelta(microseconds=-1), False),
    ],
)
def test_exact_freshness_boundaries(evidence, age, valid):
    report, context, policy = evidence

    def validate():
        validate_publication_artifact(
            report,
            context.immutable_snapshot,
            context,
            report.evaluator_policy_version_id,
            policy,
            report.created_at + age,
        )

    if valid:
        validate()
    else:
        with pytest.raises(ContentError) as caught:
            validate()
        assert caught.value.code == "VERIFICATION_STALE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("verifier_identity", "untrusted"),
        ("verifier_version", "future-v999"),
        ("question_version_id", uuid4()),
        ("content_hash", "0" * 64),
        ("bundle_hash", "0" * 64),
        ("reference_hash", "0" * 64),
    ],
)
def test_all_identity_and_content_pins_are_checked(evidence, field, value):
    report, context, policy = evidence
    with pytest.raises(ContentError) as caught:
        validate_publication_artifact(
            report.model_copy(update={field: value}),
            context.immutable_snapshot,
            context,
            report.evaluator_policy_version_id,
            policy,
            report.created_at,
        )
    assert caught.value.code == "VERIFICATION_MISMATCH"


def test_unsupported_evaluator_configuration_cannot_use_approved_id(evidence):
    report, context, policy = evidence
    for changes in [
        {"protocol_version": 1},
        {"deadline_seconds": 300},
        {"runtime_image_hash": "3" * 64},
    ]:
        with pytest.raises(ContentError) as caught:
            validate_publication_artifact(
                report,
                context.immutable_snapshot,
                context,
                report.evaluator_policy_version_id,
                policy.model_copy(update=changes),
                report.created_at,
            )
        assert caught.value.code == "VERIFICATION_UNAVAILABLE"
