"""Actual private quality verification and immutable storage on PostgreSQL/isolation."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_publication_artifacts import ADMIN, create_version, verifier
from test_publication_transition import ReportClock, controlled_report, publish_http

from mastery_backend.domain.content import content_snapshot
from mastery_backend.domain.publication_artifacts import digest
from mastery_backend.infrastructure.database.content_models import Base, QuestionVersion
from mastery_backend.infrastructure.database.content_repository import ContentRepository
from mastery_backend.infrastructure.database.publication_models import (
    PublicationQualityEvidence,
    PublicationVerificationArtifact,
)


@pytest.mark.parametrize(
    "case,reason",
    [
        ("good", "PASSED"),
        ("broken", "REFERENCE_FAILED"),
        ("weak", "WEAK_SUITE"),
        ("missing", "INVALID_CANDIDATES"),
        ("implausible", "INVALID_CANDIDATES"),
        ("syntax", "INVALID_CANDIDATES"),
        ("contract", "INVALID_CONTRACT"),
        ("invalid_policy_broken", "REFERENCE_FAILED"),
        ("invalid_policy_good", "PASSED"),
        ("candidate_resource", "RESOURCE_LIMIT"),
    ],
)
def test_real_quality_acceptance_and_publication_gate(
    seeded_storage, storage_client, complete_draft, isolated_runtime, case, reason
):
    source = "def echo(word): return None" if case == "broken" else "def echo(word): return word"
    if case == "invalid_policy_good":
        source = (
            'def echo(word):\n if not isinstance(word,str): raise ValueError("PRIVATE_ERROR")\n'
            " return word"
        )
    version_id, content, service = create_version(seeded_storage, complete_draft, source)
    changes = {}
    if case == "weak":
        changes["test_cases"] = [
            content.test_cases[0].model_copy(
                update={"input": ["hello"], "expected_output": "hello"}
            )
        ]
    if case == "missing":
        changes["incorrect_solutions"] = []
    if case in {"implausible", "syntax", "candidate_resource"}:
        bad = {
            "implausible": "def echo(word): return None",
            "syntax": "def echo(:",
            "candidate_resource": (
                'def echo(word):\n if word == "hello": return word\n while True: pass'
            ),
        }[case]
        changes["incorrect_solutions"] = [
            content.incorrect_solutions[0].model_copy(update={"source_code": bad}),
            content.incorrect_solutions[1],
        ]
    if case == "contract":
        changes["contract"] = {**content.contract.model_dump(), "output": {"type": "integer"}}
    if case.startswith("invalid_policy"):
        changes["contract"] = content.contract.model_copy(
            update={"invalid_input_policy": "raise_value_error"}
        )
    if changes:
        updated = service.patch_draft(ADMIN, version_id, 1, changes)
        content = service.read_admin_version(ADMIN, version_id)
        revision = updated.revision
    else:
        revision = 1
    report = verifier(seeded_storage, isolated_runtime).verify(ADMIN, version_id, revision)
    assert report.quality.reason_code == reason
    assert report.result.outcome == (
        "passed"
        if reason == "PASSED"
        else "resource_limit"
        if reason == "RESOURCE_LIMIT"
        else "incorrect"
    )
    assert 0 <= report.quality.executions <= 256
    assert "PRIVATE" not in report.model_dump_json()
    storage_client.app.state.settings.publication_evaluator_policy_version_id = (
        report.evaluator_policy_version_id
    )
    response = publish_http(storage_client, version_id, revision=revision)
    assert response.status_code == (200 if reason == "PASSED" else 409), response.text
    with seeded_storage() as session:
        quality = session.get(PublicationQualityEvidence, report.id)
        assert quality.reason_code == reason
        artifact = session.get(PublicationVerificationArtifact, report.id)
        stored = ContentRepository(session).content(session.get(QuestionVersion, version_id))
        assert artifact.snapshot_bytes == content_snapshot(stored)
        assert artifact.content_hash == report.content_hash
    for path in [f"/api/v1/question-versions/{version_id}", "/api/v1/questions"]:
        payload = storage_client.get(path).text
        assert all(
            marker not in payload
            for marker in ["PRIVATE", "incorrect_solutions", "source_code", "quality-v2"]
        )


def test_candidate_crud_constraints_and_published_immutability(
    seeded_storage, storage_client, complete_draft
):
    version_id, content, service = create_version(seeded_storage, complete_draft)
    assert len(service.read_admin_version(ADMIN, version_id).incorrect_solutions) == 2
    changed = service.patch_draft(ADMIN, version_id, 1, {"incorrect_solutions": []})
    assert changed.incorrect_solutions == []
    service.patch_draft(ADMIN, version_id, 2, {"incorrect_solutions": content.incorrect_solutions})
    report = controlled_report(seeded_storage, version_id, content, ReportClock(), revision=3)
    storage_client.app.state.settings.publication_evaluator_policy_version_id = (
        report.evaluator_policy_version_id
    )
    assert publish_http(storage_client, version_id, revision=3).status_code == 200
    statements = [
        "UPDATE question_incorrect_solutions SET source_code='changed' WHERE version_id=:id",
        "DELETE FROM question_incorrect_solutions WHERE version_id=:id",
        "INSERT INTO question_incorrect_solutions "
        "VALUES (:new,:id,3,'NEW_BAD','def echo(word): return 0')",
        "UPDATE publication_quality_evidence SET executions=0 WHERE artifact_id=:artifact",
        "DELETE FROM publication_quality_evidence WHERE artifact_id=:artifact",
    ]
    for sql in statements:
        with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
            session.execute(text(sql), {"id": version_id, "new": uuid4(), "artifact": report.id})
        assert caught.value.orig.sqlstate == "23514"


def test_upgrade_preserves_legacy_reports_and_rejects_new_publication(
    seeded_storage, complete_draft, database_connection, storage_client
):
    from mastery_backend.application.content_service import ContentService
    from mastery_backend.application.publication_verification import UnavailableReferenceVerifier
    from mastery_backend.domain.content import DraftContent
    from mastery_backend.infrastructure.database.evaluation_models import EvaluationPolicyVersion

    legacy = DraftContent.model_validate(complete_draft)
    service = ContentService(seeded_storage, UnavailableReferenceVerifier())
    created = service.create_question(
        ADMIN, "legacy", "LEGACY-01", UUID("00000000-0000-0000-0000-000000000031"), legacy
    )
    version_id, artifact_id, policy_id = UUID(created.body["id"]), uuid4(), uuid4()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.downgrade(config, "0009_publication_artifacts")
    database_connection.commit()
    # Old immutable bytes lack the new authoring field; retain them exactly.
    import json

    payload = legacy.model_dump(mode="json", exclude={"incorrect_solutions"})
    old_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with seeded_storage.begin() as session:
        session.add(
            EvaluationPolicyVersion(
                id=policy_id,
                version_code="legacy-reference-policy",
                configuration_json={"protocol_version": 1},
            )
        )
        session.flush()
        session.add(
            PublicationVerificationArtifact(
                id=artifact_id,
                question_version_id=version_id,
                requested_by=ADMIN.user_id,
                revision=1,
                snapshot_bytes=old_bytes,
                content_hash=digest(old_bytes),
                bundle_hash="0" * 64,
                reference_hash="0" * 64,
                evaluator_policy_version_id=policy_id,
                verifier_identity="local-reference-verifier",
                verifier_version="reference-v1",
                created_at=ReportClock().now(),
                result_json={"outcome": "passed", "checked_cases": 2, "total_cases": 2},
            )
        )
    command.upgrade(config, "head")
    database_connection.commit()
    assert compare_metadata(MigrationContext.configure(database_connection), Base.metadata) == []
    with seeded_storage() as session:
        assert session.get(PublicationVerificationArtifact, artifact_id).snapshot_bytes == old_bytes
    storage_client.app.state.settings.publication_evaluator_policy_version_id = policy_id
    response = publish_http(storage_client, version_id)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VERIFICATION_UNAVAILABLE"


def test_assistance_authorization_does_not_disclose_quality_assets(
    seeded_storage, storage_client, complete_draft
):
    from test_attempt_timers import start

    from mastery_backend.application.content_seed_service import seed_development_identity

    version_id, content, _ = create_version(seeded_storage, complete_draft)
    report = controlled_report(seeded_storage, version_id, content, ReportClock())
    storage_client.app.state.settings.publication_evaluator_policy_version_id = (
        report.evaluator_policy_version_id
    )
    assert publish_http(storage_client, version_id).status_code == 200
    attempt = start(storage_client, {"id": str(version_id)})
    for path in [
        f"/api/v1/attempts/{attempt['id']}/question",
        f"/api/v1/attempts/{attempt['id']}/assistance",
    ]:
        payload = storage_client.get(path).text
        assert "PRIVATE" not in payload and "incorrect_solutions" not in payload
    other = uuid4()
    seed_development_identity(seeded_storage, other, "Other learner", {"learner"})
    storage_client.app.state.settings.development_user_id = other
    denied = storage_client.post(
        f"/api/v1/attempts/{attempt['id']}/assistance/solution",
        json={"expected_revision": attempt["revision"], "confirmation": True},
        headers={"Idempotency-Key": "denied"},
    )
    assert denied.status_code == 404 and "PRIVATE" not in denied.text
    storage_client.app.state.settings.development_user_id = ADMIN.user_id
    allowed = storage_client.post(
        f"/api/v1/attempts/{attempt['id']}/assistance/solution",
        json={"expected_revision": attempt["revision"], "confirmation": True},
        headers={"Idempotency-Key": "allowed"},
    )
    assert allowed.status_code == 200
    assert "reference_code" in allowed.text and "PRIVATE_HINT" in allowed.text
    assert "PRIVATE_INCORRECT" not in allowed.text and "incorrect_solutions" not in allowed.text


def test_candidate_constraints_and_quality_history_downgrade(seeded_storage, complete_draft):
    from mastery_backend.infrastructure.database.content_models import QuestionIncorrectSolution

    version_id, content, _ = create_version(seeded_storage, complete_draft)
    for changes in [
        {"position": 1, "label": "NEW_LABEL"},
        {"position": 3, "label": "CONSTANT_OUTPUT"},
        {"position": 0, "label": "NEW_LABEL"},
        {"position": 3, "label": "lowercase"},
        {"position": 3, "label": "NEW_LABEL", "version_id": uuid4()},
    ]:
        with pytest.raises(IntegrityError), seeded_storage.begin() as session:
            session.add(
                QuestionIncorrectSolution(
                    id=uuid4(),
                    **{
                        "version_id": version_id,
                        "source_code": "def echo(word): return 0",
                        **changes,
                    },
                )
            )
    controlled_report(seeded_storage, version_id, content, ReportClock())
    with seeded_storage.kw["bind"].connect() as connection:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.attributes["connection"] = connection
        with pytest.raises(DBAPIError, match="Cannot remove question quality history"):
            command.downgrade(config, "0009_publication_artifacts")
        connection.rollback()
