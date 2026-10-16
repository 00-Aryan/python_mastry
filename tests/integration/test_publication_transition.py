"""S013 real PostgreSQL transitions. Synthetic reports below certify plumbing only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from test_publication_artifacts import ADMIN, create_version, verifier

from mastery_backend.api.dependencies import server_clock
from mastery_backend.application import admin_commands
from mastery_backend.application.content_service import ContentService
from mastery_backend.application.publication_report_verifier import StoredReferenceVerifier
from mastery_backend.domain.content import ContentError, content_snapshot
from mastery_backend.domain.publication_artifacts import (
    VERIFIER_IDENTITY,
    VERIFIER_VERSION,
    bundle_bytes,
    digest,
    reference_evaluator_policy,
    reference_evaluator_policy_id,
)
from mastery_backend.domain.question_quality import QualityCheckResult
from mastery_backend.infrastructure.database.content_models import (
    IdempotencyRecord,
    QuestionVersion,
)
from mastery_backend.infrastructure.database.publication_models import (
    PublicationVerificationArtifact,
)
from mastery_backend.infrastructure.database.publication_repository import append_artifact


class ReportClock:
    def __init__(self):
        self.instant = datetime.now(UTC)

    def now(self):
        return self.instant


def controlled_report(factory, version_id, content, clock, **changes):
    """Database fixture only: never a production executable-verification bypass."""
    policy = reference_evaluator_policy("1" * 64, "2" * 64)
    identifier = reference_evaluator_policy_id(policy)
    count = len(content.examples) + len(content.test_cases)
    row = PublicationVerificationArtifact(
        id=uuid4(),
        question_version_id=version_id,
        requested_by=ADMIN.user_id,
        revision=1,
        snapshot_bytes=content_snapshot(content),
        content_hash=digest(content_snapshot(content)),
        bundle_hash=digest(bundle_bytes(content)),
        reference_hash=digest(content.solution.reference_code.encode()),
        evaluator_policy_version_id=identifier,
        verifier_identity=VERIFIER_IDENTITY,
        verifier_version=VERIFIER_VERSION,
        created_at=clock.now(),
        result_json={"outcome": "passed", "checked_cases": count, "total_cases": count},
    )
    for field, value in changes.items():
        setattr(row, field, value)
    with factory.begin() as session:
        quality = QualityCheckResult(
            reason_code="PASSED"
            if row.result_json["outcome"] == "passed"
            else (
                "INFRASTRUCTURE_ERROR"
                if row.result_json["outcome"] == "infrastructure_error"
                else "REFERENCE_FAILED"
            ),
            total_candidates=len(content.incorrect_solutions),
            killed_candidates=len(content.incorrect_solutions)
            if row.result_json["outcome"] == "passed"
            else 0,
            executions=6,
        )
        append_artifact(session, row, policy.model_dump(), quality)
    return row


def publication_service(factory, row, clock):
    return ContentService(
        factory, StoredReferenceVerifier(factory, clock, row.evaluator_policy_version_id)
    )


def publish_http(client, version_id, key="publish", revision=1):
    return client.post(
        f"/api/v1/admin/question-versions/{version_id}/publish",
        json={"expected_revision": revision},
        headers={"Idempotency-Key": key},
    )


def assert_unpublished(factory, version_id, key="publish"):
    with factory() as session:
        version = session.get(QuestionVersion, version_id)
        assert version.status == "draft" and version.verification_json is None
        assert (
            session.get(
                IdempotencyRecord,
                (ADMIN.user_id, f"POST /api/v1/admin/question-versions/{version_id}/publish", key),
            )
            is None
        )


@pytest.mark.parametrize("configured", [False, True])
def test_missing_configuration_or_evidence_keeps_503(
    seeded_storage, storage_client, complete_draft, configured
):
    version_id, content, _ = create_version(seeded_storage, complete_draft)
    if configured:
        storage_client.app.state.settings.publication_evaluator_policy_version_id = uuid4()
    response = publish_http(storage_client, version_id)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VERIFICATION_UNAVAILABLE"
    assert_unpublished(seeded_storage, version_id)


@pytest.mark.parametrize(
    "case,code,status",
    [
        ("failed", "VERIFICATION_FAILED", 409),
        ("infrastructure", "VERIFICATION_UNAVAILABLE", 503),
        ("expired", "VERIFICATION_STALE", 409),
        ("future", "VERIFICATION_STALE", 409),
        ("bundle", "VERIFICATION_MISMATCH", 409),
        ("reference", "VERIFICATION_MISMATCH", 409),
        ("count", "VERIFICATION_MISMATCH", 409),
        ("policy", "VERIFICATION_UNAVAILABLE", 503),
    ],
)
def test_reports_cannot_approve_invalid_publication(
    seeded_storage, storage_client, complete_draft, case, code, status
):
    version_id, content, _ = create_version(seeded_storage, complete_draft)
    clock, changes = ReportClock(), {}
    if case in {"failed", "infrastructure"}:
        changes["result_json"] = {
            "outcome": "incorrect" if case == "failed" else "infrastructure_error",
            "checked_cases": 0,
            "total_cases": 2,
        }
    if case == "expired":
        changes["created_at"] = clock.now() - timedelta(seconds=86400)
    if case == "future":
        changes["created_at"] = clock.now() + timedelta(microseconds=1)
    if case in {"bundle", "reference"}:
        changes[case + "_hash"] = "0" * 64
    if case == "count":
        changes["result_json"] = {"outcome": "passed", "checked_cases": 1, "total_cases": 1}
    report = controlled_report(seeded_storage, version_id, content, clock, **changes)
    storage_client.app.state.settings.publication_evaluator_policy_version_id = (
        uuid4() if case == "policy" else report.evaluator_policy_version_id
    )
    storage_client.app.dependency_overrides[server_clock] = lambda: clock
    response = publish_http(storage_client, version_id)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert "PRIVATE" not in response.text
    assert_unpublished(seeded_storage, version_id)


def test_current_revision_and_latest_failed_report_are_required(seeded_storage, complete_draft):
    version_id, content, drafts = create_version(seeded_storage, complete_draft)
    clock = ReportClock()
    report = controlled_report(seeded_storage, version_id, content, clock)
    service = publication_service(seeded_storage, report, clock)
    clock.instant += timedelta(seconds=1)
    controlled_report(
        seeded_storage,
        version_id,
        content,
        clock,
        result_json={"outcome": "incorrect", "checked_cases": 1, "total_cases": 2},
    )
    with pytest.raises(ContentError) as failed:
        service.publish_version(ADMIN, "publish", version_id, 1)
    assert failed.value.code == "VERIFICATION_FAILED"
    drafts.patch_draft(ADMIN, version_id, 1, {"title": "temporary"})
    drafts.patch_draft(ADMIN, version_id, 2, {"title": content.title})
    with pytest.raises(ContentError) as stale:
        service.publish_version(ADMIN, "publish", version_id, 3)
    assert stale.value.code == "VERIFICATION_STALE"
    assert_unpublished(seeded_storage, version_id)


@pytest.mark.parametrize(
    "mutation",
    ["revision", "hash", "archive", "expiry", "report", "role", "reference", "candidate_hash"],
)
def test_changes_during_verification_reject_after_relocking(
    seeded_storage, complete_draft, mutation
):
    version_id, content, drafts = create_version(seeded_storage, complete_draft)
    clock = ReportClock()
    report = controlled_report(seeded_storage, version_id, content, clock)
    entered, release = Event(), Event()

    class PausedVerifier(StoredReferenceVerifier):
        def verify(self, snapshot):
            assert seeded_storage.kw["bind"].pool.checkedout() == 0
            proof = super().verify(snapshot)
            entered.set()
            assert release.wait(10)
            return proof

    service = ContentService(
        seeded_storage, PausedVerifier(seeded_storage, clock, report.evaluator_policy_version_id)
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.publish_version, ADMIN, "publish", version_id, 1)
        try:
            assert entered.wait(10)
            if mutation == "revision":
                drafts.patch_draft(ADMIN, version_id, 1, {"title": "changed"})
            elif mutation == "hash":
                with seeded_storage.begin() as session:
                    session.execute(
                        text(
                            "UPDATE question_test_cases SET expected_json='null'::jsonb "
                            "WHERE version_id=:id"
                        ),
                        {"id": version_id},
                    )
            elif mutation == "candidate_hash":
                with seeded_storage.begin() as session:
                    session.execute(
                        text(
                            "UPDATE question_incorrect_solutions SET source_code='changed' "
                            "WHERE version_id=:id"
                        ),
                        {"id": version_id},
                    )
            elif mutation == "archive":
                with seeded_storage() as session:
                    question_id = session.get(QuestionVersion, version_id).question_id
                drafts.archive_question(ADMIN, "archive", question_id, 1)
            elif mutation == "expiry":
                clock.instant += timedelta(seconds=86400)
            elif mutation == "report":
                clock.instant += timedelta(seconds=1)
                controlled_report(seeded_storage, version_id, content, clock)
            elif mutation == "role":
                with seeded_storage.begin() as session:
                    session.execute(
                        text("DELETE FROM user_roles WHERE user_id=:id AND role='content_admin'"),
                        {"id": ADMIN.user_id},
                    )
            else:
                # A reference may become archived without changing the draft's own hash/revision.
                with seeded_storage.begin() as session:
                    session.execute(
                        text("UPDATE skills SET archived_at=now() WHERE id=:id"),
                        {"id": content.skill_mappings[0].skill_id},
                    )
        finally:
            release.set()
        with pytest.raises(ContentError) as caught:
            future.result(timeout=10)
    expected = {
        "revision": "STALE_REVISION",
        "hash": "STALE_REVISION",
        "candidate_hash": "STALE_REVISION",
        "archive": "QUESTION_ARCHIVED",
        "expiry": "VERIFICATION_STALE",
        "report": "VERIFICATION_STALE",
        "role": "FORBIDDEN",
        "reference": "INVALID_SKILL",
    }
    assert caught.value.code == expected[mutation]
    assert_unpublished(seeded_storage, version_id)


@pytest.mark.parametrize("same_key", [False, True])
def test_simultaneous_publication_serializes_and_replays(seeded_storage, complete_draft, same_key):
    version_id, content, _ = create_version(seeded_storage, complete_draft)
    clock, barrier = ReportClock(), Barrier(2)
    report = controlled_report(seeded_storage, version_id, content, clock)

    class ConcurrentVerifier(StoredReferenceVerifier):
        def verify(self, snapshot):
            proof = super().verify(snapshot)
            barrier.wait(timeout=10)
            return proof

    service = ContentService(
        seeded_storage,
        ConcurrentVerifier(seeded_storage, clock, report.evaluator_policy_version_id),
    )

    def publish(key):
        try:
            return service.publish_version(ADMIN, key, version_id, 1)
        except ContentError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, ["publish", "publish" if same_key else "other"]))
    if same_key:
        assert all(not isinstance(result, str) for result in results)
        assert sorted(result.replayed for result in results) == [False, True]
    else:
        assert sum(not isinstance(result, str) for result in results) == 1
        assert "PUBLISHED_IMMUTABLE" in results
    with seeded_storage() as session:
        version = session.get(QuestionVersion, version_id)
        assert version.revision == 2
        assert version.verification_json["verification_id"] == str(report.id)


def test_rollback_then_lost_response_retry_preserves_immutable_report(
    seeded_storage, complete_draft, monkeypatch
):
    version_id, content, _ = create_version(seeded_storage, complete_draft)
    clock = ReportClock()
    report = controlled_report(seeded_storage, version_id, content, clock)
    service = publication_service(seeded_storage, report, clock)
    original = admin_commands.record_command

    def fail(*args, **kwargs):
        raise RuntimeError("test-only failed command persistence")

    monkeypatch.setattr(admin_commands, "record_command", fail)
    with pytest.raises(RuntimeError):
        service.publish_version(ADMIN, "publish", version_id, 1)
    assert_unpublished(seeded_storage, version_id)
    monkeypatch.setattr(admin_commands, "record_command", original)
    accepted = service.publish_version(ADMIN, "publish", version_id, 1)
    clock.instant += timedelta(days=2)
    replay = service.publish_version(ADMIN, "publish", version_id, 1)
    assert replay.replayed and replay.body == accepted.body
    with seeded_storage() as session:
        assert (
            session.scalar(select(func.count()).select_from(PublicationVerificationArtifact)) == 1
        )
        assert session.get(
            PublicationVerificationArtifact, report.id
        ).snapshot_bytes == content_snapshot(content)
    with pytest.raises(ContentError) as conflict:
        service.publish_version(ADMIN, "publish", version_id, 2)
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    "source,successful",
    [
        ("def echo(word): return word", True),
        ("def echo(word): return None", False),
    ],
)
def test_real_isolated_report_enables_publication_without_api_execution(
    seeded_storage,
    storage_client,
    complete_draft,
    isolated_runtime,
    monkeypatch,
    source,
    successful,
):
    from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox

    version_id, content, _ = create_version(seeded_storage, complete_draft, source)
    report = verifier(seeded_storage, isolated_runtime).verify(ADMIN, version_id, 1)
    assert report.result.outcome == ("passed" if successful else "incorrect")
    storage_client.app.state.settings.publication_evaluator_policy_version_id = (
        report.evaluator_policy_version_id
    )

    def forbidden(*args):
        raise AssertionError("API must not execute reference code")

    monkeypatch.setattr(LocalSandbox, "execute", forbidden)
    response = publish_http(storage_client, version_id)
    if not successful:
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "VERIFICATION_FAILED"
        assert "PRIVATE" not in response.text
        assert_unpublished(seeded_storage, version_id)
        return
    assert response.status_code == 200, response.text
    public = storage_client.get(f"/api/v1/question-versions/{version_id}")
    assert public.status_code == 200
    for value in [public.text, storage_client.get("/api/v1/questions").text]:
        for marker in ["PRIVATE", content.solution.reference_code, str(report.id), "verification"]:
            assert marker not in value
    with seeded_storage() as session:
        from mastery_backend.infrastructure.database.content_repository import ContentRepository

        version = session.get(QuestionVersion, version_id)
        assert content_snapshot(ContentRepository(session).content(version)) == content_snapshot(
            content
        )
        assert version.verification_json["verification_id"] == str(report.id)
    # HTTP cannot nominate arbitrary receipts or outcomes.
    extra = storage_client.post(
        f"/api/v1/admin/question-versions/{version_id}/publish",
        json={"expected_revision": 1, "verification_id": str(report.id), "outcome": "passed"},
        headers={"Idempotency-Key": "untrusted"},
    )
    assert extra.status_code == 422


def test_unsupported_policy_and_authorization_deny_writes(
    seeded_storage, storage_client, complete_draft
):
    from mastery_backend.infrastructure.database.evaluation_models import EvaluationPolicyVersion

    version_id, content, _ = create_version(seeded_storage, complete_draft)
    clock = ReportClock()
    policy_id = uuid4()
    # Simulate an unsupported legacy/future trusted-database fact, not an executor.
    with seeded_storage.begin() as session:
        session.add(
            EvaluationPolicyVersion(
                id=policy_id,
                version_code="publication-v2-" + policy_id.hex,
                configuration_json={"protocol_version": 999},
            )
        )
    original = controlled_report(seeded_storage, version_id, content, clock)
    clock.instant += timedelta(seconds=1)
    with seeded_storage.begin() as session:
        values = {
            column.name: getattr(original, column.name) for column in original.__table__.columns
        }
        session.add(
            PublicationVerificationArtifact(
                **{
                    **values,
                    "id": uuid4(),
                    "created_at": clock.now(),
                    "evaluator_policy_version_id": policy_id,
                }
            )
        )
    storage_client.app.dependency_overrides[server_clock] = lambda: clock
    storage_client.app.state.settings.publication_evaluator_policy_version_id = policy_id
    response = publish_http(storage_client, version_id)
    assert response.status_code == 503
    assert "PRIVATE" not in response.text
    with seeded_storage.begin() as session:
        session.execute(
            text("DELETE FROM user_roles WHERE user_id=:id AND role='content_admin'"),
            {"id": ADMIN.user_id},
        )
    denied = publish_http(storage_client, version_id)
    assert denied.status_code == 403
    assert_unpublished(seeded_storage, version_id)
