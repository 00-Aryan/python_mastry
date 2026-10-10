"""Real PostgreSQL immutable receipt, ownership and acceptance-order checks."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from mastery_backend.application.assistance_service import AssistanceService
from mastery_backend.application.attempt_service import AttemptService
from mastery_backend.application.submission_service import SubmissionService
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal
from mastery_backend.infrastructure.database.attempt_models import Attempt, AttemptEvent
from mastery_backend.infrastructure.database.content_models import Base
from mastery_backend.infrastructure.database.submission_models import Submission
from mastery_backend.infrastructure.database.submission_repository import SubmissionRepository

ADMIN = Principal(UUID(int=1), frozenset({"learner", "content_admin"}))
SOURCE = "def echo(word):\r\n    return word # LEARNER_SOURCE_SECRET\r\n"
PRIVATE = [
    "PRIVATE_TEST_INPUT",
    "PRIVATE_TEST_OUTPUT",
    "PRIVATE_HINT",
    "PRIVATE_SOLUTION",
    "PRIVATE_RUBRIC",
]


@pytest.fixture
def complete_draft(complete_draft):
    draft = dict(complete_draft)
    draft["assistance_steps"] = [
        {
            "position": 1,
            "kind": "directional",
            "content": "PRIVATE_HINT",
            "next_budget_seconds": 60,
        },
        {
            "position": 2,
            "kind": "full_solution",
            "content": "PRIVATE_FINAL",
            "next_budget_seconds": 60,
        },
    ]
    return draft


def start(client, published):
    response = client.post(
        "/api/v1/attempts",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "question_version_id": published["id"],
            "mode": "assessment",
            "independent_budget_seconds": 60,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def submit(client, attempt, *, source=SOURCE, purpose="assessment", key=None, revision=None):
    return client.post(
        f"/api/v1/attempts/{attempt['id']}/submissions",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={
            "expected_revision": attempt["revision"] if revision is None else revision,
            "source_code": source,
            "purpose": purpose,
        },
    )


def current(client, attempt):
    response = client.get(f"/api/v1/attempts/{attempt['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def help_request(client, attempt):
    return client.post(
        f"/api/v1/attempts/{attempt['id']}/assistance/next",
        headers={"Idempotency-Key": str(uuid4())},
        json={"expected_revision": attempt["revision"], "trigger": "learner_request"},
    )


def mutate(client, attempt, action, **fields):
    response = client.post(
        f"/api/v1/attempts/{attempt['id']}/{action}",
        headers={"Idempotency-Key": str(uuid4())},
        json={"expected_revision": attempt["revision"], **fields},
    )
    assert response.status_code == 200, response.text
    return response.json()


def assert_private_absent(response):
    for marker in PRIVATE:
        assert marker not in response.text
    assert "PRIVATE_FINAL" not in response.text
    assert "reference_code" not in response.text


def test_receipt_source_evidence_and_later_assistance_are_immutable(
    attempt_client, published_question, attempt_clock, seeded_storage
):
    client = attempt_client
    attempt = start(client, published_question)
    attempt_clock.advance(12345)
    received = submit(client, attempt)
    assert received.status_code == 201, received.text
    detail = received.json()
    assert detail["status"] == "received" and detail["evaluation"] == "not_requested"
    assert detail["source_code"] == SOURCE
    assert detail["code_hash"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert detail["source_bytes"] == len(SOURCE.encode())
    assert detail["accepted_event_sequence"] == 2
    assert detail["evidence"]["attempt"]["timer"]["active_elapsed_ms"] == 12345
    assert detail["evidence"]["assistance_grant_ids"] == []
    assert detail["evidence"]["attempt"]["assistance_level"] == "none"
    assert_private_absent(received)
    assisted = help_request(client, detail["evidence"]["attempt"])
    assert assisted.status_code == 200, assisted.text
    assert client.get(received.headers["Location"]).json() == detail
    after = submit(client, assisted.json()["attempt"], purpose="public_run")
    assert after.status_code == 201
    assert after.json()["evidence"]["assistance_grant_ids"] == [assisted.json()["grant"]["id"]]
    assert after.json()["evidence"]["attempt"]["assistance_level"] == "directional"
    assert_private_absent(after)
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(Submission)) == 2


@pytest.mark.parametrize("elapsed", [59999, 60000, 60001])
def test_exact_expiry_reconciles_before_receipt(
    attempt_client, published_question, attempt_clock, elapsed
):
    attempt = start(attempt_client, published_question)
    attempt_clock.advance(elapsed)
    response = submit(attempt_client, attempt)
    assert response.status_code == 201, response.text
    receipt = response.json()
    timer = receipt["evidence"]["attempt"]["timer"]
    assert timer["remaining_ms"] == max(0, 60000 - elapsed)
    assert (timer["expired_at"] is None) == (elapsed < 60000)
    assert receipt["accepted_event_sequence"] == (2 if elapsed < 60000 else 3)
    assert receipt["evidence"]["attempt"]["assistance_level"] == "none"
    assert receipt["evidence"]["assistance_grant_ids"] == []
    assert receipt["evidence"]["attempt"]["lifecycle_state"] == "active"


@pytest.mark.parametrize(
    "source", ["def broken(:", "import os; os._exit(99)", "return definitely_wrong"]
)
def test_syntax_errors_and_incorrect_code_are_received_not_executed(
    attempt_client, published_question, source
):
    attempt = start(attempt_client, published_question)
    response = submit(attempt_client, attempt, source=source)
    assert response.status_code == 201, response.text
    assert response.json()["source_code"] == source
    assert response.json()["evaluation"] == "not_requested"


def test_payload_limits_utf8_invalid_fields_and_body_guard(attempt_client, published_question):
    client = attempt_client
    client.app.state.settings = client.app.state.settings.model_copy(update={"max_code_bytes": 4})
    attempt = start(client, published_question)
    exact = submit(client, attempt, source="ππ")
    assert exact.status_code == 201, exact.text
    attempt = exact.json()["evidence"]["attempt"]
    for source, status in [("ππx", 413), ("", 422), (" \r\n", 422), ("x\x00", 422)]:
        rejected = submit(client, attempt, source=source)
        assert rejected.status_code == status, rejected.text
        assert_private_absent(rejected)
    path = f"/api/v1/attempts/{attempt['id']}/submissions"
    for change in [
        {"source_code": 3},
        {"purpose": "wrong"},
        {"expected_revision": True},
        {"user_id": str(uuid4())},
        {"assistance_level": "none"},
    ]:
        invalid = client.post(
            path,
            headers={"Idempotency-Key": "invalid"},
            json={
                "source_code": "x",
                "purpose": "assessment",
                "expected_revision": attempt["revision"],
                **change,
            },
        )
        assert invalid.status_code == 422
    surrogate = client.post(
        path,
        headers={"Idempotency-Key": "surrogate", "Content-Type": "application/json"},
        content=json.dumps(
            {
                "source_code": "\ud800",
                "purpose": "assessment",
                "expected_revision": attempt["revision"],
            }
        ),
    )
    assert surrogate.status_code == 422
    too_big = submit(client, attempt, source="x" * 262144)
    assert too_big.status_code == 413
    assert current(client, attempt)["revision"] == attempt["revision"]


def test_replay_indefinite_conflicts_terminal_and_limit_changes(
    attempt_client, published_question, attempt_clock, seeded_storage
):
    client = attempt_client
    attempt = start(client, published_question)
    received = submit(client, attempt, key="lost")
    assert received.status_code == 201, received.text
    attempt_clock.advance(9 * 86400000)
    calls = attempt_clock.calls
    client.app.state.settings = client.app.state.settings.model_copy(update={"max_code_bytes": 1})
    replay = submit(client, attempt, key="lost")
    assert replay.status_code == 201 and replay.json() == received.json()
    assert replay.headers["Location"] == received.headers["Location"]
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert attempt_clock.calls == calls
    for change in [{"source": "different"}, {"purpose": "public_run"}, {"revision": 2}]:
        conflict = submit(client, attempt, key="lost", **change)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    terminal = mutate(client, current(client, attempt), "abandon")
    assert submit(client, terminal, source="x").status_code == 409
    assert submit(client, attempt, key="lost").json() == received.json()
    assert client.get(received.headers["Location"]).status_code == 200
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(Submission)) == 1


@pytest.mark.parametrize("action", ["pause", "defer", "abandon"])
def test_lifecycle_rules_and_paused_clock(
    attempt_client, published_question, attempt_clock, action
):
    attempt = start(attempt_client, published_question)
    attempt_clock.advance(10000)
    changed = mutate(attempt_client, attempt, action)
    attempt_clock.advance(500000)
    received = submit(attempt_client, changed)
    if action == "pause":
        assert received.status_code == 201, received.text
        assert received.json()["evidence"]["attempt"]["timer"]["active_elapsed_ms"] == 10000
        assert received.json()["evidence"]["attempt"]["lifecycle_state"] == "paused"
    else:
        assert received.status_code == 409
        assert received.json()["error"]["code"] == "INVALID_ATTEMPT_STATE"


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_submissions_have_one_identity_or_stale_conflict(
    attempt_client, published_question, attempt_clock, seeded_storage, same_key
):
    attempt = start(attempt_client, published_question)
    barrier = Barrier(2)

    def accept(index):
        service = SubmissionService(seeded_storage, attempt_clock, 65536)
        barrier.wait(timeout=5)
        try:
            return service.accept(
                ADMIN,
                UUID(attempt["id"]),
                "same" if same_key else str(index),
                SOURCE,
                "assessment",
                1,
            )
        except ContentError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept, range(2)))
    successful = [value for value in results if not isinstance(value, str)]
    if same_key:
        assert len(successful) == 2 and successful[0].body == successful[1].body
        assert sum(item.replayed for item in successful) == 1
    else:
        assert len(successful) == 1 and "STALE_REVISION" in results
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(Submission)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AttemptEvent)
                .where(AttemptEvent.event_type == "submission_received")
            )
            == 1
        )


@pytest.mark.parametrize("other_command", ["help", "pause", "extend", "abandon"])
def test_concurrent_help_and_timer_commands_use_same_order(
    attempt_client, published_question, attempt_clock, seeded_storage, other_command
):
    client = attempt_client
    attempt = start(client, published_question)
    barrier = Barrier(2)

    def request(kind):
        barrier.wait(timeout=5)
        try:
            if kind == "submit":
                return SubmissionService(seeded_storage, attempt_clock, 65536).accept(
                    ADMIN, UUID(attempt["id"]), "parallel", SOURCE, "assessment", 1
                )
            if other_command == "help":
                return AssistanceService(seeded_storage, attempt_clock).grant(
                    ADMIN, UUID(attempt["id"]), "help", "next", 1, "learner_request"
                )
            return AttemptService(seeded_storage, attempt_clock).command(
                ADMIN,
                "timer",
                UUID(attempt["id"]),
                other_command,
                1,
                additional_seconds=60 if other_command == "extend" else None,
            )
        except ContentError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, ["submit", "other"]))
    assert sum(not isinstance(value, str) for value in results) == 1
    assert "STALE_REVISION" in results
    now = current(client, attempt)
    if not isinstance(results[0], str):
        receipt = results[0].body
        assert receipt["evidence"]["attempt"]["assistance_level"] == "none"
        if other_command == "help":
            assert help_request(client, now).status_code == 200
            assert client.get(f"/api/v1/submissions/{receipt['id']}").json() == receipt
    elif other_command != "abandon":
        retried = submit(client, now)
        assert retried.status_code == 201, retried.text
        if other_command == "help":
            assert retried.json()["evidence"]["attempt"]["assistance_level"] == "directional"
            assert len(retried.json()["evidence"]["assistance_grant_ids"]) == 1


def test_owned_reads_replay_and_stored_authorization(
    attempt_client, published_question, seeded_storage
):
    from mastery_backend.api.dependencies import current_principal
    from mastery_backend.application.content_seed_service import seed_development_identity

    client = attempt_client
    attempt = start(client, published_question)
    received = submit(client, attempt, key="owned")
    assert received.status_code == 201
    path = received.headers["Location"]
    other = UUID(int=2)
    seed_development_identity(
        seeded_storage, other, "Other admin learner", {"learner", "content_admin"}
    )
    client.app.dependency_overrides[current_principal] = lambda: Principal(
        other, frozenset({"learner", "content_admin"})
    )
    for response in [
        client.get(path),
        client.get(f"/api/v1/attempts/{attempt['id']}/submissions"),
        submit(client, attempt, key="owned"),
    ]:
        assert response.status_code == 404
        assert_private_absent(response)
        assert "LEARNER_SOURCE_SECRET" not in response.text
    client.app.dependency_overrides.pop(current_principal)
    assert client.get(f"/api/v1/submissions/{uuid4()}").status_code == 404
    assert submit(client, {**attempt, "id": str(uuid4())}).status_code == 404
    with seeded_storage.begin() as session:
        session.execute(
            text("DELETE FROM user_roles WHERE user_id=:id AND role='learner'"),
            {"id": ADMIN.user_id},
        )
    for response in [
        submit(client, attempt, key="owned"),
        client.get(path),
        client.get(f"/api/v1/attempts/{attempt['id']}/submissions"),
    ]:
        assert response.status_code == 403
    with seeded_storage.begin() as session:
        session.execute(
            text("UPDATE users SET status='disabled' WHERE id=:id"), {"id": ADMIN.user_id}
        )
    assert submit(client, attempt, key="owned").status_code == 401
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"development_user_id": None}
    )
    assert submit(client, attempt).status_code == 401


def test_rollback_after_receipt_flush_and_retry(
    attempt_client, published_question, attempt_clock, seeded_storage, monkeypatch
):
    client = attempt_client
    attempt = start(client, published_question)
    attempt_clock.advance(60000)
    original = SubmissionRepository.insert

    def fail_after_insert(self, submission):
        original(self, submission)
        raise RuntimeError(SOURCE + " PRIVATE_SOLUTION")

    monkeypatch.setattr(SubmissionRepository, "insert", fail_after_insert)
    response = submit(client, attempt, key="retry")
    assert response.status_code == 500
    assert_private_absent(response)
    assert "LEARNER_SOURCE_SECRET" not in response.text
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(Submission)) == 0
        stored = session.get(Attempt, UUID(attempt["id"]))
        assert stored.revision == 1
        assert stored.last_event_sequence == 1
        assert stored.independent_interval_ended_at is None
        assert stored.total_active_elapsed_ms == 0
    monkeypatch.setattr(SubmissionRepository, "insert", original)
    retried = submit(client, attempt, key="retry")
    assert retried.status_code == 201, retried.text
    assert retried.json()["accepted_event_sequence"] == 3


def test_immutable_database_source_and_all_evidence(
    attempt_client, published_question, seeded_storage
):
    attempt = start(attempt_client, published_question)
    response = submit(attempt_client, attempt)
    assert response.status_code == 201
    identifier = UUID(response.json()["id"])
    for sql in [
        "UPDATE submissions SET source_code='new' WHERE id=:id",
        "UPDATE submissions SET code_hash=repeat('0',64) WHERE id=:id",
        "UPDATE submissions SET evidence_json='{}'::jsonb WHERE id=:id",
        "UPDATE submissions SET question_version_id=:other WHERE id=:id",
        "UPDATE submissions SET accepted_at=accepted_at + interval '1 second' WHERE id=:id",
        "UPDATE submissions SET request_key='different' WHERE id=:id",
        "DELETE FROM submissions WHERE id=:id",
    ]:
        with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
            session.execute(text(sql), {"id": identifier, "other": uuid4()})
        assert caught.value.orig.sqlstate == "23514"
    assert attempt_client.get(response.headers["Location"]).json() == response.json()


@pytest.mark.parametrize("corruption", ["hash", "bytes", "policy", "grants"])
def test_insert_constraints_and_rollbacks(
    attempt_client, published_question, seeded_storage, monkeypatch, corruption
):
    attempt = start(attempt_client, published_question)
    original = SubmissionRepository.insert

    def corrupt(self, submission):
        if corruption == "hash":
            submission.code_hash = "0" * 64
        elif corruption == "bytes":
            submission.source_bytes += 1
        elif corruption == "policy":
            submission.policy_version_id = UUID(int=100)
        else:
            submission.evidence_json = {
                **submission.evidence_json,
                "assistance_grant_ids": [str(uuid4())],
            }
        original(self, submission)

    monkeypatch.setattr(SubmissionRepository, "insert", corrupt)
    response = submit(attempt_client, attempt)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "SUBMISSION_CONFLICT"
    assert_private_absent(response)
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(Submission)) == 0
        assert session.get(Attempt, UUID(attempt["id"])).revision == 1


def test_duplicate_request_constraint_rolls_back_new_acceptance(
    attempt_client, published_question, seeded_storage, monkeypatch
):
    attempt = start(attempt_client, published_question)
    original = submit(attempt_client, attempt, key="same")
    assert original.status_code == 201
    changed = original.json()["evidence"]["attempt"]
    monkeypatch.setattr(SubmissionRepository, "replay", lambda *args: None)
    conflicted = submit(attempt_client, changed, key="same")
    assert conflicted.status_code == 409
    assert conflicted.json()["error"]["code"] == "SUBMISSION_CONFLICT"
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(Submission)) == 1
        assert session.get(Attempt, UUID(attempt["id"])).revision == changed["revision"]


def test_stable_bounded_pagination_filters_and_summary_privacy(
    attempt_client, published_question, attempt_clock, seeded_storage
):
    from base64 import urlsafe_b64decode, urlsafe_b64encode
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import event

    client = attempt_client
    attempt = start(client, published_question)
    details = []
    for index in range(5):
        response = submit(client, attempt, purpose="assessment" if index % 2 else "public_run")
        assert response.status_code == 201
        details.append(response.json())
        attempt = response.json()["evidence"]["attempt"]
    path = f"/api/v1/attempts/{attempt['id']}/submissions"
    selects = []
    writes = []

    def observe(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT") and "submissions" in statement:
            selects.append(statement)
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = seeded_storage.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    calls = attempt_clock.calls
    try:
        first = client.get(path, params={"limit": 2})
        assert first.status_code == 200, first.text
        assert [item["id"] for item in first.json()["items"]] == [
            details[4]["id"],
            details[3]["id"],
        ]
        assert "source_code" not in first.text and "evidence" not in first.text
        assert "LEARNER_SOURCE_SECRET" not in first.text
        assert_private_absent(first)
        assert client.get(f"/api/v1/submissions/{details[0]['id']}").json() == details[0]
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert writes == [] and attempt_clock.calls == calls
    assert len(selects) == 2
    assert "source_code" not in selects[0] and "evidence_json" not in selects[0]
    inserted_later = submit(client, attempt)
    assert inserted_later.status_code == 201
    seen = [item["id"] for item in first.json()["items"]]
    cursor = first.json()["next_cursor"]
    original_cursor = cursor
    while cursor:
        page = client.get(path, params={"limit": 2, "cursor": cursor})
        assert page.status_code == 200, page.text
        seen.extend(item["id"] for item in page.json()["items"])
        cursor = page.json()["next_cursor"]
    assert seen == [detail["id"] for detail in reversed(details)]
    filtered = client.get(path, params={"purpose": "public_run"})
    assert len(filtered.json()["items"]) == 3
    assert all(item["purpose"] == "public_run" for item in filtered.json()["items"])
    for params in [
        {"limit": 0},
        {"limit": 101},
        {"unknown": "PRIVATE_SOLUTION"},
        {"purpose": "invalid"},
    ]:
        invalid = client.get(path, params=params)
        assert invalid.status_code == 422
        assert_private_absent(invalid)
    assert client.get(path, params={"cursor": "bad"}).status_code == 400
    assert (
        client.get(path, params={"cursor": original_cursor, "purpose": "public_run"}).status_code
        == 400
    )
    decoded = json.loads(urlsafe_b64decode(original_cursor))
    decoded["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    expired = urlsafe_b64encode(json.dumps(decoded).encode()).decode()
    assert client.get(path, params={"cursor": expired}).status_code == 400
    other = start(client, published_question)
    assert (
        client.get(
            f"/api/v1/attempts/{other['id']}/submissions", params={"cursor": original_cursor}
        ).status_code
        == 400
    )
    client.app.state.settings = client.app.state.settings.model_copy(update={"max_page_size": 1})
    assert client.get(path, params={"limit": 2}).status_code == 422


def test_pinned_archived_versions_policies_and_public_log_privacy(
    attempt_client, published_question, complete_draft, seeded_storage, caplog
):
    from datetime import UTC, datetime

    from mastery_backend.infrastructure.database.attempt_models import LearningPolicyVersion
    from mastery_backend.infrastructure.observability.logging import JsonLogFormatter

    client = attempt_client
    attempt = start(client, published_question)
    receipt = submit(client, attempt)
    assert receipt.status_code == 201
    created = client.post(
        f"/api/v1/admin/questions/{published_question['question_id']}/versions",
        headers={"Idempotency-Key": "version"},
        json={**complete_draft, "statement": "New statement"},
    )
    assert created.status_code == 201
    assert (
        client.post(
            f"/api/v1/admin/question-versions/{created.json()['id']}/publish",
            headers={"Idempotency-Key": "publish-version"},
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    with seeded_storage.begin() as session:
        session.add(
            LearningPolicyVersion(
                version_code="future-test",
                configuration_json={
                    "minimum_budget_seconds": 1,
                    "maximum_budget_seconds": 2,
                    "maximum_extension_seconds": 1,
                    "allowed_modes": ["practice"],
                },
                effective_at=datetime.now(UTC),
            )
        )
    assert (
        client.post(
            f"/api/v1/admin/questions/{published_question['question_id']}/archive",
            headers={"Idempotency-Key": "archive"},
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    after = submit(client, receipt.json()["evidence"]["attempt"])
    assert after.status_code == 201
    assert after.json()["question_version_id"] == published_question["id"]
    assert after.json()["policy_version_id"] == attempt["policy_version_id"]
    assert after.json()["id"] != receipt.json()["id"]
    assert client.get(receipt.headers["Location"]).json() == receipt.json()
    for path in [
        "/api/v1/questions",
        "/api/v1/attempts",
        f"/api/v1/attempts/{attempt['id']}",
        f"/api/v1/attempts/{attempt['id']}/question",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert_private_absent(response)
        assert "LEARNER_SOURCE_SECRET" not in response.text
    entries = [record for record in caplog.records if record.getMessage() == "submission_received"]
    assert entries
    for record in entries:
        encoded = JsonLogFormatter().format(record)
        assert "LEARNER_SOURCE_SECRET" not in encoded
        assert not any(marker in encoded for marker in PRIVATE)
        assert json.loads(encoded)["submission_id"]


def test_real_migration_preserves_b4_and_refuses_submission_erasure(
    attempt_client, published_question, attempt_clock, seeded_storage, database_connection
):
    attempt = start(attempt_client, published_question)
    assisted = help_request(attempt_client, attempt)
    assert assisted.status_code == 200
    attempt_clock.advance(12345)
    paused = mutate(attempt_client, assisted.json()["attempt"], "pause")
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.downgrade(config, "0005_progressive_assistance")
    before_attempt = dict(
        database_connection.execute(
            text("SELECT * FROM attempts WHERE id=:id"), {"id": UUID(attempt["id"])}
        )
        .mappings()
        .one()
    )
    before_grants = [
        dict(row)
        for row in database_connection.execute(text("SELECT * FROM assistance_grants")).mappings()
    ]
    before_phases = [
        dict(row)
        for row in database_connection.execute(
            text("SELECT * FROM attempt_phases ORDER BY phase_number")
        ).mappings()
    ]
    database_connection.commit()
    command.upgrade(config, "head")
    assert (
        dict(
            database_connection.execute(
                text("SELECT * FROM attempts WHERE id=:id"), {"id": UUID(attempt["id"])}
            )
            .mappings()
            .one()
        )
        == before_attempt
    )
    assert [
        dict(row)
        for row in database_connection.execute(text("SELECT * FROM assistance_grants")).mappings()
    ] == before_grants
    assert [
        dict(row)
        for row in database_connection.execute(
            text("SELECT * FROM attempt_phases ORDER BY phase_number")
        ).mappings()
    ] == before_phases
    assert compare_metadata(MigrationContext.configure(database_connection), Base.metadata) == []
    database_connection.commit()
    command.upgrade(config, "head")
    database_connection.commit()
    receipt = submit(attempt_client, paused)
    assert receipt.status_code == 201, receipt.text
    with pytest.raises(IntegrityError) as caught:
        command.downgrade(config, "0005_progressive_assistance")
    assert caught.value.orig.sqlstate == "23514"
    database_connection.rollback()
    assert (
        database_connection.scalar(text("SELECT version_num FROM alembic_version"))
        == "0007_evaluation_lifecycle"
    )
    assert database_connection.scalar(text("SELECT count(*) FROM submissions")) == 1
    database_connection.commit()
    assert attempt_client.get(receipt.headers["Location"]).json() == receipt.json()


def test_default_byte_limit_and_full_solution_intake(attempt_client, published_question):
    client = attempt_client
    attempt = start(client, published_question)
    response = submit(client, attempt, source="x" * 65536, purpose="public_run")
    assert response.status_code == 201, response.text
    attempt = response.json()["evidence"]["attempt"]
    rejected = submit(client, attempt, source="x" * 65537)
    assert rejected.status_code == 413
    escaped = client.post(
        f"/api/v1/attempts/{attempt['id']}/assistance/solution",
        headers={"Idempotency-Key": "solution"},
        json={"expected_revision": attempt["revision"], "confirmation": True},
    )
    assert escaped.status_code == 200
    after = submit(client, escaped.json()["attempt"])
    assert after.status_code == 201
    assert after.json()["evidence"]["attempt"]["assistance_level"] == "full_solution"
    assert len(after.json()["evidence"]["assistance_grant_ids"]) == 1
    assert after.json()["evidence"]["attempt"]["independent_end_reason"] == "assistance_requested"
    assert_private_absent(after)


def test_acceptance_clock_anchor_and_read_receipts_without_clock(
    attempt_client, published_question, attempt_clock, seeded_storage
):
    client = attempt_client
    attempt = start(client, published_question)
    attempt_clock.advance(10000)
    receipt = submit(client, attempt)
    assert receipt.status_code == 201
    calls = attempt_clock.calls
    attempt_clock.advance(-1)
    failed = submit(client, receipt.json()["evidence"]["attempt"], key="backward")
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "CLOCK_UNAVAILABLE"
    calls += 1
    assert client.get(receipt.headers["Location"]).json() == receipt.json()
    assert client.get(f"/api/v1/attempts/{attempt['id']}/submissions").status_code == 200
    assert attempt_clock.calls == calls
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(Submission)) == 1
    attempt_clock.advance(1)
    retried = submit(client, receipt.json()["evidence"]["attempt"], key="backward")
    assert retried.status_code == 201
