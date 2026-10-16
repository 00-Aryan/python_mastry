"""Real isolated reference checks and durable PostgreSQL artifacts; never publication bypass."""

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from mastery_backend.application.clock import SystemClock
from mastery_backend.application.content_service import ContentService
from mastery_backend.application.publication_artifact_service import PublicationArtifactService
from mastery_backend.application.publication_verification import UnavailableReferenceVerifier
from mastery_backend.domain.content import ContentError, DraftContent, content_snapshot
from mastery_backend.domain.identity import Principal
from mastery_backend.domain.publication_artifacts import bundle_bytes, digest
from mastery_backend.infrastructure.database.content_models import Base, QuestionVersion
from mastery_backend.infrastructure.database.publication_models import (
    PublicationVerificationArtifact,
)
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox

ADMIN = Principal(UUID("00000000-0000-0000-0000-000000000001"), frozenset({"content_admin"}))
FAMILY_ID = UUID("00000000-0000-0000-0000-000000000031")


def create_version(factory, complete_draft, source="def echo(word): return word"):
    content = DraftContent.model_validate(complete_draft)
    content = content.model_copy(
        update={
            "solution": content.solution.model_copy(update={"reference_code": source}),
            "test_cases": [
                content.test_cases[0].model_copy(update={"expected_output": "PRIVATE_TEST_INPUT"})
            ],
        }
    )
    service = ContentService(factory, UnavailableReferenceVerifier())
    response = service.create_question(ADMIN, "create", "VERIFY-01", FAMILY_ID, content)
    return UUID(response.body["id"]), content, service


def verifier(factory, runtime):
    return PublicationArtifactService(factory, SystemClock(), LocalSandbox(runtime))


@pytest.mark.parametrize(
    "source,outcome",
    [
        ("def echo(word): return word", "passed"),
        ("def echo(word): return None", "incorrect"),
        ("def echo(:", "syntax_error"),
        ("def echo(word): raise ValueError('PRIVATE_DIAGNOSTIC')", "runtime_error"),
    ],
)
def test_real_reference_artifact_pins_and_safe_bounded_results(
    seeded_storage, complete_draft, isolated_runtime, source, outcome
):
    version_id, content, service = create_version(seeded_storage, complete_draft, source)
    report = verifier(seeded_storage, isolated_runtime).verify(ADMIN, version_id, 1)
    assert report.result.outcome == outcome
    assert report.content_hash == digest(content_snapshot(content))
    assert report.bundle_hash == digest(bundle_bytes(content))
    assert report.reference_hash == digest(source.encode())
    assert report.verifier_identity == "local-reference-verifier"
    assert report.verifier_version == "reference-v1"
    assert 0 < report.result.checked_cases <= report.result.total_cases == 2
    payload = report.model_dump_json()
    assert len(payload) < 2048
    for marker in [source, "PRIVATE_TEST_INPUT", "PRIVATE_DIAGNOSTIC", "PRIVATE_HINT"]:
        assert marker not in payload
    with seeded_storage() as session:
        row = session.get(PublicationVerificationArtifact, report.id)
        assert row.snapshot_bytes == content_snapshot(content)
        assert row.result_json == report.result.model_dump()
        assert session.get(QuestionVersion, version_id).status == "draft"
    with seeded_storage() as session:
        stored = session.get(PublicationVerificationArtifact, report.id)
        values = {column.name: getattr(stored, column.name) for column in stored.__table__.columns}
    for changes in [
        {"content_hash": "0" * 64},
        {"result_json": {"outcome": None, "checked_cases": None, "total_cases": None}},
        {"result_json": {"outcome": "passed", "checked_cases": 0, "total_cases": 2}},
        {
            "result_json": {
                "outcome": "passed",
                "checked_cases": 2,
                "total_cases": 2,
                "diagnostic": "PRIVATE",
            }
        },
        {"verifier_identity": "untrusted"},
        {"evaluator_policy_version_id": uuid4()},
    ]:
        with pytest.raises(IntegrityError), seeded_storage.begin() as session:
            session.add(PublicationVerificationArtifact(**{**values, "id": uuid4(), **changes}))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with seeded_storage.kw["bind"].connect() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(DBAPIError, match="Cannot remove publication verification history"):
            command.downgrade(config, "0008_local_execution")
        connection.rollback()
    # Even a real passing artifact does not wire S013 or bypass the default 503 boundary.
    with pytest.raises(ContentError, match="unavailable"):
        service.publish_version(ADMIN, "publish", version_id, 1)
    with pytest.raises(ContentError, match="Referenced"):
        service.delete_draft(ADMIN, version_id, 1)
    for statement in [
        "UPDATE publication_verification_artifacts SET revision=2 WHERE id=:id",
        "DELETE FROM publication_verification_artifacts WHERE id=:id",
    ]:
        with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
            session.execute(text(statement), {"id": report.id})
        assert caught.value.orig.sqlstate == "23514"


def test_snapshot_release_edit_revocation_and_unavailable_report(
    seeded_storage, complete_draft, isolated_runtime, monkeypatch
):
    version_id, content, service = create_version(seeded_storage, complete_draft)
    runner = verifier(seeded_storage, isolated_runtime)

    def unavailable():
        # Independent committed edit establishes that no authoring lock/session is held.
        service.patch_draft(ADMIN, version_id, 1, {"title": "Changed during verification"})
        raise RuntimeError("PRIVATE_STARTUP_DIAGNOSTIC")

    monkeypatch.setattr(runner.sandbox, "startup_check", unavailable)
    report = runner.verify(ADMIN, version_id, 1)
    assert report.result.outcome == "infrastructure_error"
    assert report.result.checked_cases == 0
    assert report.content_hash == digest(content_snapshot(content))
    assert "PRIVATE" not in report.model_dump_json()
    with seeded_storage() as session:
        assert session.get(QuestionVersion, version_id).revision == 2
    with pytest.raises(ContentError, match="changed"):
        verifier(seeded_storage, isolated_runtime).verify(ADMIN, version_id, 1)
    runner = verifier(seeded_storage, isolated_runtime)

    def revoked():
        with seeded_storage.begin() as session:
            session.execute(
                text("DELETE FROM user_roles WHERE user_id=:id AND role='content_admin'"),
                {"id": ADMIN.user_id},
            )
        raise RuntimeError("unavailable")

    monkeypatch.setattr(runner.sandbox, "startup_check", revoked)
    with pytest.raises(ContentError, match="administrator"):
        runner.verify(ADMIN, version_id, 2)
    with seeded_storage() as session:
        assert (
            session.scalar(select(func.count()).select_from(PublicationVerificationArtifact)) == 1
        )


def test_limits_unauthorized_and_rollback(
    seeded_storage, complete_draft, isolated_runtime, monkeypatch
):
    version_id, content, service = create_version(seeded_storage, complete_draft)
    runner = verifier(seeded_storage, isolated_runtime)
    with pytest.raises(ContentError, match="administrator"):
        runner.verify(Principal(ADMIN.user_id, frozenset()), version_id, 1)
    too_many = [content.test_cases[0].model_copy(update={"position": n}) for n in range(1, 65)]
    service.patch_draft(ADMIN, version_id, 1, {"test_cases": too_many})
    with pytest.raises(ContentError, match="at most 64"):
        runner.verify(ADMIN, version_id, 2)
    service.patch_draft(ADMIN, version_id, 2, {"test_cases": content.test_cases})
    from mastery_backend.application import publication_artifact_service

    original = publication_artifact_service.append_artifact

    def fail_after_flush(*args):
        original(*args)
        raise RuntimeError("simulated transaction failure")

    monkeypatch.setattr(publication_artifact_service, "append_artifact", fail_after_flush)
    with pytest.raises(RuntimeError, match="transaction failure"):
        runner.verify(ADMIN, version_id, 3)
    with seeded_storage() as session:
        assert (
            session.scalar(select(func.count()).select_from(PublicationVerificationArtifact)) == 0
        )
    monkeypatch.setattr(publication_artifact_service, "append_artifact", original)
    assert (
        verifier(seeded_storage, isolated_runtime).verify(ADMIN, version_id, 3).result.outcome
        == "passed"
    )


def test_upgrade_from_existing_baseline(database_connection):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.upgrade(config, "0008_local_execution")
    database_connection.commit()
    # Preserve an existing immutable evaluator policy across the upgrade.
    database_connection.execute(
        text(
            "INSERT INTO evaluator_policy_versions VALUES "
            "('00000000-0000-0000-0000-000000000999','preserved',:config)"
        ),
        {"config": json.dumps({"protocol_version": 1})},
    )
    database_connection.commit()
    command.upgrade(config, "head")
    database_connection.commit()
    assert compare_metadata(MigrationContext.configure(database_connection), Base.metadata) == []
    assert (
        database_connection.scalar(
            text(
                "SELECT version_code FROM evaluator_policy_versions WHERE version_code='preserved'"
            )
        )
        == "preserved"
    )
    database_connection.commit()
    command.downgrade(config, "0008_local_execution")
    database_connection.commit()
    command.upgrade(config, "head")
    database_connection.commit()


def test_separate_local_cli_and_public_exclusion(
    seeded_storage, storage_client, complete_draft, isolated_runtime, monkeypatch, capsys
):
    import sys

    from mastery_backend import content_cli
    from mastery_backend.settings import Settings

    version_id, content, service = create_version(seeded_storage, complete_draft)
    monkeypatch.setattr(
        content_cli,
        "Settings",
        lambda: Settings(
            _env_file=None,
            app_env="development",
            development_user_id=ADMIN.user_id,
            database_url="postgresql://localhost/mastery_test",
        ),
    )
    # Keep the real CLI/service/sandbox, routing its database to the disposable schema.
    monkeypatch.setattr(
        content_cli, "create_database_engine", lambda settings: seeded_storage.kw["bind"]
    )
    monkeypatch.setattr(content_cli, "create_session_factory", lambda engine: seeded_storage)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mastery-content",
            "verify-reference",
            "--version-id",
            str(version_id),
            "--expected-revision",
            "1",
            "--runtime",
            str(isolated_runtime),
        ],
    )
    content_cli.main()
    captured = capsys.readouterr().out
    report = json.loads(captured.splitlines()[-1])
    assert report["result"]["outcome"] == "passed"
    assert storage_client.get(f"/api/v1/question-versions/{version_id}").status_code == 404
    assert storage_client.get("/api/v1/questions").json()["items"] == []
    response = storage_client.post(
        f"/api/v1/admin/question-versions/{version_id}/publish",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": "no-bypass"},
    )
    assert response.status_code == 503
    deletion = storage_client.delete(
        f"/api/v1/admin/question-versions/{version_id}", params={"expected_revision": 1}
    )
    assert deletion.status_code == 409
    assert deletion.json()["error"]["code"] == "VERSION_REFERENCED"
    for value in [captured, response.text, storage_client.get("/api/v1/questions").text]:
        for marker in ["PRIVATE_TEST_INPUT", "PRIVATE_HINT", content.solution.reference_code]:
            assert marker not in value


def test_delete_during_verification_cannot_leave_partial_history(
    seeded_storage, complete_draft, isolated_runtime, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    version_id, content, service = create_version(seeded_storage, complete_draft)
    runner = verifier(seeded_storage, isolated_runtime)
    captured, deleted = Event(), Event()

    def pause_before_execution():
        captured.set()
        assert deleted.wait(10)
        raise RuntimeError("test-only unavailable control boundary")

    monkeypatch.setattr(runner.sandbox, "startup_check", pause_before_execution)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner.verify, ADMIN, version_id, 1)
        try:
            assert captured.wait(10)
            service.delete_draft(ADMIN, version_id, 1)
        finally:
            deleted.set()
        with pytest.raises(ContentError) as caught:
            future.result(timeout=10)
        assert caught.value.code == "NOT_FOUND"
    with seeded_storage() as session:
        assert session.get(QuestionVersion, version_id) is None
        assert (
            session.scalar(select(func.count()).select_from(PublicationVerificationArtifact)) == 0
        )
