"""PostgreSQL release, privacy, retry and concurrent assistance acceptance."""

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
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal
from mastery_backend.infrastructure.database.assistance_models import AssistanceGrant
from mastery_backend.infrastructure.database.assistance_repository import AssistanceRepository
from mastery_backend.infrastructure.database.attempt_models import (
    Attempt,
    AttemptEvent,
    AttemptPhase,
)
from mastery_backend.infrastructure.database.content_models import Base

ADMIN = Principal(UUID(int=1), frozenset({"learner", "content_admin"}))
MARKERS = [
    "SECRET_DIRECTION",
    "SECRET_PATTERN",
    "SECRET_PSEUDOCODE",
    "SECRET_STEPS",
    "SECRET_FINAL",
    "PRIVATE_SOLUTION",
    "PRIVATE_TEST_INPUT",
    "PRIVATE_TEST_OUTPUT",
    "PRIVATE_RUBRIC",
]


@pytest.fixture
def complete_draft(complete_draft):
    draft = dict(complete_draft)
    draft["assistance_steps"] = [
        {"position": position, "kind": kind, "content": marker, "next_budget_seconds": 60}
        for position, (kind, marker) in enumerate(
            zip(
                ["directional", "pattern", "pseudocode", "partial_code", "full_solution"],
                MARKERS[:5],
                strict=True,
            ),
            1,
        )
    ]
    return draft


def start(client, published, key=None):
    response = client.post(
        "/api/v1/attempts",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={
            "question_version_id": published["id"],
            "mode": "practice",
            "independent_budget_seconds": 60,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def grant(client, attempt, *, operation="next", trigger="learner_request", key=None, revision=None):
    body = {"expected_revision": attempt["revision"] if revision is None else revision}
    body.update({"confirmation": True} if operation == "solution" else {"trigger": trigger})
    return client.post(
        f"/api/v1/attempts/{attempt['id']}/assistance/{operation}",
        headers={"Idempotency-Key": key or str(uuid4())},
        json=body,
    )


def read(client, attempt):
    response = client.get(f"/api/v1/attempts/{attempt['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def mutate(client, attempt, action, **body):
    response = client.post(
        f"/api/v1/attempts/{attempt['id']}/{action}",
        headers={"Idempotency-Key": str(uuid4())},
        json={"expected_revision": attempt["revision"], **body},
    )
    assert response.status_code == 200, response.text
    return response.json()


def assert_no_secrets(response, allowed=()):
    for marker in MARKERS:
        if marker not in allowed:
            assert marker not in response.text


@pytest.mark.parametrize("elapsed", [59999, 60000, 60001])
def test_release_boundary_and_progressive_privacy(
    attempt_client, published_question, attempt_clock, elapsed
):
    client = attempt_client
    attempt = start(client, published_question)
    attempt_clock.advance(elapsed)
    response = grant(client, attempt, trigger="budget_expired")
    if elapsed < 60000:
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ASSISTANCE_NOT_READY"
        assert_no_secrets(response)
        return
    assert response.status_code == 200, response.text
    assert response.json()["grant"]["kind"] == "directional"
    assert response.json()["grant"]["reason"] == "budget_expired"
    attempt = response.json()["attempt"]
    assert attempt["timer"]["phase_number"] == 1
    assert attempt["timer"]["remaining_ms"] == 60000
    assert attempt["overdue_active_elapsed_ms"] == elapsed - 60000
    assert_no_secrets(response, allowed=("SECRET_DIRECTION",))
    for stage, marker in zip(["pattern", "pseudocode", "partial_code"], MARKERS[1:4], strict=True):
        attempt_clock.advance(59999)
        denied = grant(client, attempt)
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "ASSISTANCE_NOT_READY"
        assert_no_secrets(denied)
        attempt_clock.advance(1)
        response = grant(client, attempt)
        assert response.status_code == 200, response.text
        assert response.json()["grant"]["kind"] == stage
        assert_no_secrets(response, allowed=(marker,))
        attempt = response.json()["attempt"]
    attempt_clock.advance(60000)
    exhausted = grant(client, attempt)
    assert exhausted.status_code == 409
    assert exhausted.json()["error"]["code"] == "ASSISTANCE_EXHAUSTED"
    assert_no_secrets(exhausted)
    solution = grant(client, attempt, operation="solution")
    assert solution.status_code == 200, solution.text
    assert "PRIVATE_SOLUTION" in solution.json()["grant"]["solution"]["reference_code"]
    assert_no_secrets(solution, allowed=("SECRET_FINAL", "PRIVATE_SOLUTION"))


def test_pause_resume_extend_and_permanent_early_help(
    attempt_client, published_question, attempt_clock, seeded_storage
):
    client = attempt_client
    attempt = start(client, published_question)
    attempt_clock.advance(10000)
    first = grant(client, attempt)
    assert first.status_code == 200, first.text
    attempt = first.json()["attempt"]
    independent_end = attempt["independent_interval_ended_at"]
    assert attempt["independent_end_reason"] == "assistance_requested"
    attempt_clock.advance(10000)
    attempt = mutate(client, attempt, "pause")
    attempt_clock.advance(3600000)
    assert read(client, attempt)["timer"]["remaining_ms"] == 50000
    blocked = grant(client, attempt)
    assert blocked.status_code == 409
    attempt = mutate(client, attempt, "extend", additional_budget_seconds=60)
    assert attempt["assistance_level"] == "directional"
    assert attempt["independent_interval_ended_at"] == independent_end
    attempt = mutate(client, attempt, "resume")
    attempt_clock.advance(109999)
    restarted = AttemptService(seeded_storage, attempt_clock).read(ADMIN, UUID(attempt["id"]))
    assert restarted.timer.remaining_ms == 1
    assert grant(client, attempt).status_code == 409
    attempt_clock.advance(1)
    second = grant(client, attempt)
    assert second.status_code == 200, second.text
    assert second.json()["attempt"]["independent_interval_ended_at"] == independent_end
    assert second.json()["attempt"]["overdue_active_elapsed_ms"] == 0
    assert second.json()["attempt"]["total_active_elapsed_ms"] == 130000
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(AssistanceGrant)) == 2
        assert session.scalar(select(func.count()).select_from(AttemptPhase)) == 3


@pytest.mark.parametrize("paused", [False, True])
def test_immediate_solution_escape_closes_timer_without_ending_session(
    attempt_client, published_question, attempt_clock, paused
):
    client = attempt_client
    attempt = start(client, published_question)
    attempt_clock.advance(12000)
    if paused:
        attempt = mutate(client, attempt, "pause")
    response = grant(client, attempt, operation="solution", key="escape")
    assert response.status_code == 200, response.text
    assisted = response.json()["attempt"]
    assert assisted["lifecycle_state"] == ("paused" if paused else "active")
    assert assisted["assistance_level"] == "full_solution"
    assert assisted["timer"]["running_since"] is None
    assert not assisted["assistance_eligible"]
    assert_no_secrets(response, allowed=("SECRET_FINAL", "PRIVATE_SOLUTION"))
    attempt_clock.advance(60000)
    assert read(client, assisted)["timer"]["active_elapsed_ms"] == 12000
    for operation in ["next", "solution"]:
        denied = grant(client, assisted, operation=operation)
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "ASSISTANCE_EXHAUSTED"
    extended = client.post(
        f"/api/v1/attempts/{assisted['id']}/extend",
        headers={"Idempotency-Key": "extend-after-solution"},
        json={"expected_revision": assisted["revision"], "additional_budget_seconds": 60},
    )
    assert extended.status_code == 409


def test_exact_retry_lost_response_and_terminal_history(
    attempt_client, published_question, attempt_clock, seeded_storage
):
    client = attempt_client
    attempt = start(client, published_question)
    original = grant(client, attempt, key="lost-response")
    assert original.status_code == 200, original.text
    calls = attempt_clock.calls
    attempt_clock.advance(9 * 86400000)
    replay = grant(client, attempt, key="lost-response")
    assert replay.status_code == 200
    assert replay.json() == original.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert attempt_clock.calls == calls
    assert grant(client, attempt, key="lost-response", trigger="budget_expired").status_code == 409
    current = read(client, attempt)
    terminal = mutate(client, current, "abandon")
    assert grant(client, terminal).status_code == 409
    assert grant(client, attempt, key="lost-response").json() == original.json()
    history = client.get(f"/api/v1/attempts/{attempt['id']}/assistance")
    assert history.status_code == 200
    assert len(history.json()["grants"]) == 1
    assert_no_secrets(history, allowed=("SECRET_DIRECTION",))
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(AssistanceGrant)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AttemptEvent)
                .where(AttemptEvent.event_type == "assistance_granted")
            )
            == 1
        )


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_requests_cannot_advance_twice(
    attempt_client, published_question, attempt_clock, seeded_storage, same_key
):
    attempt = start(attempt_client, published_question)
    barrier = Barrier(2)

    def request(index):
        service = AssistanceService(seeded_storage, attempt_clock)
        barrier.wait(timeout=5)
        try:
            return service.grant(
                ADMIN,
                UUID(attempt["id"]),
                "same" if same_key else str(index),
                "next",
                1,
                "learner_request",
            )
        except ContentError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, range(2)))
    successes = [result for result in results if not isinstance(result, str)]
    if same_key:
        assert len(successes) == 2
        assert successes[0].body == successes[1].body
        assert sum(result.replayed for result in successes) == 1
    else:
        assert len(successes) == 1
        assert "STALE_REVISION" in results
    current = read(attempt_client, attempt)
    assert grant(attempt_client, current).json()["error"]["code"] == "ASSISTANCE_NOT_READY"
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(AssistanceGrant)) == 1
        assert session.scalar(select(func.count()).select_from(AttemptPhase)) == 2


def test_post_flush_failure_rolls_back_then_same_key_retries(
    attempt_client, published_question, attempt_clock, seeded_storage, monkeypatch
):
    attempt = start(attempt_client, published_question)
    attempt_clock.advance(60000)
    original = AttemptService.snapshot

    def fail_snapshot(*args, **kwargs):
        raise RuntimeError("SECRET_PATTERN PRIVATE_SOLUTION")

    monkeypatch.setattr(AttemptService, "snapshot", fail_snapshot)
    failed = grant(attempt_client, attempt, key="retry")
    assert failed.status_code == 500
    assert_no_secrets(failed)
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(AssistanceGrant)) == 0
        stored = session.get(Attempt, UUID(attempt["id"]))
        assert stored.revision == 1
        assert stored.assistance_level == "none"
        assert stored.independent_interval_ended_at is None
        assert session.scalar(select(func.count()).select_from(AttemptPhase)) == 1
    monkeypatch.setattr(AttemptService, "snapshot", original)
    assert grant(attempt_client, attempt, key="retry").status_code == 200


def test_public_detail_lists_and_errors_never_leak(attempt_client, published_question):
    client = attempt_client
    attempt = start(client, published_question)
    assert grant(client, attempt).status_code == 200
    for path in [
        "/api/v1/attempts",
        f"/api/v1/attempts/{attempt['id']}",
        f"/api/v1/attempts/{attempt['id']}/question",
        "/api/v1/questions",
        f"/api/v1/questions/{published_question['question_id']}",
        f"/api/v1/question-versions/{published_question['id']}",
    ]:
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert_no_secrets(response)
        assert "reference_code" not in response.text
    invalid = client.post(
        f"/api/v1/attempts/{attempt['id']}/assistance/solution",
        headers={"Idempotency-Key": "invalid"},
        json={"expected_revision": 2, "confirmation": "PRIVATE_SOLUTION"},
    )
    assert invalid.status_code == 422
    assert_no_secrets(invalid)


@pytest.mark.parametrize("terminal", ["defer", "abandon"])
def test_terminal_and_authorization_restrictions(
    attempt_client, published_question, seeded_storage, terminal
):
    client = attempt_client
    attempt = start(client, published_question)
    ended = mutate(client, attempt, terminal)
    for operation in ["next", "solution"]:
        rejected = grant(client, ended, operation=operation)
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "INVALID_ATTEMPT_STATE"
        assert_no_secrets(rejected)
    with seeded_storage.begin() as session:
        session.execute(
            text("DELETE FROM user_roles WHERE user_id=:id AND role='learner'"),
            {"id": ADMIN.user_id},
        )
    assert grant(client, ended).status_code == 403
    assert client.get(f"/api/v1/attempts/{attempt['id']}/assistance").status_code == 403


def test_other_owner_missing_identity_and_explicit_confirmation(
    attempt_client, published_question, seeded_storage
):
    from mastery_backend.api.dependencies import current_principal
    from mastery_backend.application.content_seed_service import seed_development_identity

    client = attempt_client
    attempt = start(client, published_question)
    for confirmation in [False, 1, "true", None]:
        response = client.post(
            f"/api/v1/attempts/{attempt['id']}/assistance/solution",
            headers={"Idempotency-Key": "bad-confirm"},
            json={"expected_revision": 1, "confirmation": confirmation},
        )
        assert response.status_code == 422
    assert grant(client, {**attempt, "id": str(uuid4())}).status_code == 404
    other = UUID(int=2)
    seed_development_identity(seeded_storage, other, "Other learner", {"learner", "content_admin"})
    client.app.dependency_overrides[current_principal] = lambda: Principal(
        other, frozenset({"learner", "content_admin"})
    )
    for operation in ["next", "solution"]:
        rejected = grant(client, attempt, operation=operation)
        assert rejected.status_code == 404
        assert_no_secrets(rejected)
    assert client.get(f"/api/v1/attempts/{attempt['id']}/assistance").status_code == 404
    client.app.dependency_overrides.pop(current_principal)
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"development_user_id": None}
    )
    assert grant(client, attempt).status_code == 401


@pytest.mark.parametrize("operation", ["next", "solution"])
def test_missing_assets_roll_back_and_retry(
    attempt_client, published_question, attempt_clock, seeded_storage, operation
):
    client = attempt_client
    attempt = start(client, published_question)
    attempt_clock.advance(60000)
    table = "question_assistance_steps" if operation == "next" else "question_solutions"
    # Corrupt only this disposable fixture to exercise recovery from missing assets.
    with seeded_storage.begin() as session:
        session.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        records = (
            session.execute(
                text(f"SELECT * FROM {table} WHERE version_id=:id"),
                {"id": UUID(published_question["id"])},
            )
            .mappings()
            .all()
        )
        session.execute(
            text(f"DELETE FROM {table} WHERE version_id=:id"),
            {"id": UUID(published_question["id"])},
        )
        session.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
    missing = grant(client, attempt, operation=operation, key="missing")
    assert missing.status_code == 503, missing.text
    assert missing.json()["error"]["code"] == "ASSISTANCE_UNAVAILABLE"
    assert_no_secrets(missing)
    with seeded_storage.begin() as session:
        stored = session.get(Attempt, UUID(attempt["id"]))
        assert stored.revision == 1 and stored.independent_interval_ended_at is None
        assert session.scalar(select(func.count()).select_from(AssistanceGrant)) == 0
        session.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        for record in records:
            names = list(record)
            session.execute(
                text(
                    f"INSERT INTO {table} ({','.join(names)}) "
                    f"VALUES ({','.join(':' + name for name in names)})"
                ),
                dict(record),
            )
        session.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
    assert grant(client, attempt, operation=operation, key="missing").status_code == 200


def test_archived_pinned_assets_and_grant_database_guards(
    attempt_client, published_question, seeded_storage
):
    client = attempt_client
    attempt = start(client, published_question)
    archived = client.post(
        f"/api/v1/admin/questions/{published_question['question_id']}/archive",
        headers={"Idempotency-Key": "archive"},
        json={"expected_revision": 1},
    )
    assert archived.status_code == 200
    response = grant(client, attempt)
    assert response.status_code == 200, response.text
    assisted = response.json()["attempt"]
    for sql in [
        "UPDATE assistance_grants SET reason='budget_expired' WHERE attempt_id=:id",
        "DELETE FROM assistance_grants WHERE attempt_id=:id",
        "UPDATE attempts SET assistance_level='none' WHERE id=:id",
        "UPDATE attempts SET independent_interval_ended_at=NULL, "
        "independent_end_reason=NULL WHERE id=:id",
    ]:
        with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
            session.execute(text(sql), {"id": UUID(attempt["id"])})
        assert caught.value.orig.sqlstate == "23514"
    second = start_other_published_version(client, published_question)
    assert grant(client, second).status_code == 200
    with seeded_storage() as session:
        existing = session.scalar(
            select(AssistanceGrant).where(AssistanceGrant.attempt_id == UUID(attempt["id"]))
        )
        row = {
            name: getattr(existing, name)
            for name in [
                "step_id",
                "granted_at",
                "reason",
                "command_id",
                "operation",
                "request_key",
                "request_hash",
                "response_json",
            ]
        }
    with pytest.raises(IntegrityError), seeded_storage.begin() as session:
        session.add(AssistanceGrant(id=uuid4(), attempt_id=UUID(second["id"]), **row))
    escape = grant(client, assisted, operation="solution")
    assert escape.status_code == 200
    history = client.get(f"/api/v1/attempts/{attempt['id']}/assistance").json()["grants"]
    assert [item["kind"] for item in history] == ["directional", "full_solution"]


def start_other_published_version(client, published):
    preview = client.get(f"/api/v1/admin/question-versions/{published['id']}").json()
    draft_fields = [
        "title",
        "statement",
        "track",
        "difficulty",
        "assessment_role",
        "supported_modes",
        "suggested_budget_seconds",
        "contract",
        "skill_mappings",
        "pattern_ids",
        "examples",
        "test_cases",
        "assistance_steps",
        "solution",
        "revision_links",
    ]
    draft = {key: preview[key] for key in draft_fields}
    for step in draft["assistance_steps"]:
        step["content"] = "NEW_VERSION_SECRET"
    created = client.post(
        "/api/v1/admin/questions",
        headers={"Idempotency-Key": "other-question"},
        json={
            "code": "OTHER-ASSISTANCE",
            "family_id": "00000000-0000-0000-0000-000000000031",
            "draft": draft,
        },
    )
    assert created.status_code == 201, created.text
    published = client.post(
        f"/api/v1/admin/question-versions/{created.json()['id']}/publish",
        headers={"Idempotency-Key": "other-publish"},
        json={"expected_revision": 1},
    )
    assert published.status_code == 200, published.text
    return start(client, published.json())


def test_migration_preserves_b3_policy(database_connection):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.upgrade(config, "0004_attempt_timers")
    old_policy = (
        database_connection.execute(text("SELECT * FROM learning_policy_versions")).mappings().one()
    )
    database_connection.commit()
    command.upgrade(config, "head")
    assert dict(
        database_connection.execute(
            text("SELECT * FROM learning_policy_versions WHERE id=:id"), {"id": old_policy["id"]}
        )
        .mappings()
        .one()
    ) == dict(old_policy)
    assert compare_metadata(MigrationContext.configure(database_connection), Base.metadata) == []
    database_connection.commit()
    command.downgrade(config, "0004_attempt_timers")
    assert database_connection.scalar(text("SELECT count(*) FROM learning_policy_versions")) == 1
    database_connection.commit()
    command.upgrade(config, "head")
    database_connection.commit()


def test_legacy_pinned_policy_denies_assistance_without_changing_timers(
    attempt_client, published_question, attempt_clock, seeded_storage, monkeypatch
):
    from mastery_backend.infrastructure.database import attempt_repository

    monkeypatch.setattr(attempt_repository, "PILOT_TIMER_POLICY_CODE", "pilot-timer-1")
    attempt = start(attempt_client, published_question)
    assert attempt["policy_version"] == "pilot-timer-1"
    attempt_clock.advance(60000)
    rejected = grant(attempt_client, attempt)
    assert rejected.status_code == 503
    assert rejected.json()["error"]["code"] == "POLICY_UNAVAILABLE"
    with seeded_storage() as session:
        assert session.get(Attempt, UUID(attempt["id"])).revision == 1
    current = read(attempt_client, attempt)
    assert current["timer"]["expired_at"] is not None
    assert current["assistance_level"] == "none"


def test_grant_when_paused_after_expiry_and_no_countdown_writes(
    attempt_client, published_question, attempt_clock, seeded_storage
):
    from sqlalchemy import event

    client = attempt_client
    attempt = start(client, published_question)
    attempt_clock.advance(60000)
    attempt = mutate(client, attempt, "pause")
    granted = grant(client, attempt, trigger="budget_expired")
    assert granted.status_code == 200, granted.text
    attempt = granted.json()["attempt"]
    assert attempt["lifecycle_state"] == "paused"
    assert attempt["timer"]["running_since"] is None
    attempt_clock.advance(600000)
    assert read(client, attempt)["timer"]["remaining_ms"] == 60000
    attempt = mutate(client, attempt, "resume")
    writes = []

    def observe(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = seeded_storage.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        for _ in range(3):
            attempt_clock.advance(1000)
            assert read(client, attempt)["timer"]["phase_number"] == 1
            listed = client.get("/api/v1/attempts")
            assert listed.status_code == 200
            assert listed.json()["items"][0]["timer"]["phase_number"] == 1
            assert_no_secrets(listed)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert writes == []


@pytest.mark.parametrize("budget", [59, 86401])
def test_invalid_published_wait_bound_rolls_back(
    attempt_client, published_question, seeded_storage, budget
):
    with seeded_storage.begin() as session:
        session.execute(text("ALTER TABLE question_assistance_steps DISABLE TRIGGER USER"))
        session.execute(
            text(
                "UPDATE question_assistance_steps SET next_budget_seconds=:budget "
                "WHERE version_id=:id AND position=1"
            ),
            {"budget": budget, "id": UUID(published_question["id"])},
        )
        session.execute(text("ALTER TABLE question_assistance_steps ENABLE TRIGGER USER"))
    attempt = start(attempt_client, published_question)
    rejected = grant(attempt_client, attempt)
    assert rejected.status_code == 503
    assert rejected.json()["error"]["code"] == "ASSISTANCE_UNAVAILABLE"
    assert read(attempt_client, attempt)["revision"] == 1
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(AssistanceGrant)) == 0


def test_real_upgrade_with_existing_b3_attempt_and_refused_history_downgrade(
    attempt_client,
    published_question,
    attempt_clock,
    seeded_storage,
    database_connection,
    monkeypatch,
):
    from mastery_backend.infrastructure.database import attempt_repository

    monkeypatch.setattr(attempt_repository, "PILOT_TIMER_POLICY_CODE", "pilot-timer-1")
    attempt = start(attempt_client, published_question)
    attempt_clock.advance(12000)
    attempt = mutate(attempt_client, attempt, "pause")
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.downgrade(config, "0004_attempt_timers")
    original = dict(
        database_connection.execute(
            text("SELECT * FROM attempts WHERE id=:id"), {"id": UUID(attempt["id"])}
        )
        .mappings()
        .one()
    )
    original_phase = dict(
        database_connection.execute(
            text("SELECT * FROM attempt_phases WHERE attempt_id=:id"), {"id": UUID(attempt["id"])}
        )
        .mappings()
        .one()
    )
    database_connection.commit()
    command.upgrade(config, "head")
    upgraded = dict(
        database_connection.execute(
            text("SELECT * FROM attempts WHERE id=:id"), {"id": UUID(attempt["id"])}
        )
        .mappings()
        .one()
    )
    assert upgraded.pop("prior_phase_elapsed_ms") == 0
    assert upgraded == original
    assert (
        dict(
            database_connection.execute(
                text("SELECT * FROM attempt_phases WHERE attempt_id=:id"),
                {"id": UUID(attempt["id"])},
            )
            .mappings()
            .one()
        )
        == original_phase
    )
    database_connection.commit()
    assert read(attempt_client, attempt)["timer"]["remaining_ms"] == 48000
    assert grant(attempt_client, attempt).status_code == 503
    monkeypatch.setattr(attempt_repository, "PILOT_TIMER_POLICY_CODE", "pilot-assistance-1")
    new_attempt = start(attempt_client, published_question)
    assert grant(attempt_client, new_attempt).status_code == 200
    with pytest.raises(IntegrityError) as caught:
        command.downgrade(config, "0004_attempt_timers")
    assert caught.value.orig.sqlstate == "23514"
    database_connection.rollback()
    assert (
        database_connection.scalar(text("SELECT version_num FROM alembic_version"))
        == "0009_publication_artifacts"
    )
    database_connection.commit()


def test_grants_stay_on_original_question_version(
    attempt_client, published_question, complete_draft
):
    client = attempt_client
    attempt = start(client, published_question)
    changed = dict(complete_draft)
    changed["assistance_steps"] = [
        {**step, "content": "NEW_VERSION_SECRET"} for step in changed["assistance_steps"]
    ]
    created = client.post(
        f"/api/v1/admin/questions/{published_question['question_id']}/versions",
        headers={"Idempotency-Key": "new-version"},
        json=changed,
    )
    assert created.status_code == 201
    publication = client.post(
        f"/api/v1/admin/question-versions/{created.json()['id']}/publish",
        headers={"Idempotency-Key": "publish-new-version"},
        json={"expected_revision": 1},
    )
    assert publication.status_code == 200
    old = grant(client, attempt)
    assert old.status_code == 200
    assert old.json()["grant"]["content"] == "SECRET_DIRECTION"
    assert "NEW_VERSION_SECRET" not in old.text
    new = grant(client, start(client, publication.json()))
    assert new.status_code == 200
    assert new.json()["grant"]["content"] == "NEW_VERSION_SECRET"


def test_duplicate_grant_constraint_and_safe_service_conflict(
    attempt_client, published_question, seeded_storage, attempt_clock, monkeypatch
):
    client = attempt_client
    attempt = start(client, published_question)
    response = grant(client, attempt)
    assert response.status_code == 200
    with seeded_storage() as session:
        existing = session.scalar(select(AssistanceGrant))
        fields = {
            column.name: getattr(existing, column.name)
            for column in AssistanceGrant.__table__.columns
        }
    fields.update(id=uuid4(), request_key="new-key")
    with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
        session.add(AssistanceGrant(**fields))
    assert caught.value.orig.sqlstate == "23505"
    assert caught.value.orig.diag.constraint_name == "uq_assistance_grant_step"
    current = response.json()["attempt"]
    attempt_clock.advance(60000)

    def duplicate_step(self, attempt_id, version_id, solution):
        from mastery_backend.infrastructure.database.content_models import QuestionAssistanceStep

        return self.session.get(QuestionAssistanceStep, existing.step_id)

    monkeypatch.setattr(AssistanceRepository, "next_step", duplicate_step)
    conflict = grant(client, current)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "ATTEMPT_CONFLICT"
    assert_no_secrets(conflict)
    with seeded_storage() as session:
        stored = session.get(Attempt, UUID(attempt["id"]))
        assert stored.revision == current["revision"]
        assert session.scalar(select(func.count()).select_from(AssistanceGrant)) == 1


def test_malformed_pinned_policy_fails_safely(
    attempt_client, published_question, seeded_storage, monkeypatch
):
    from datetime import UTC, datetime

    from mastery_backend.infrastructure.database import attempt_repository
    from mastery_backend.infrastructure.database.attempt_models import LearningPolicyVersion

    with seeded_storage.begin() as session:
        session.add(
            LearningPolicyVersion(
                id=uuid4(),
                version_code="broken-test-policy",
                configuration_json={"private": "PRIVATE_SOLUTION"},
                effective_at=datetime.now(UTC),
            )
        )
    monkeypatch.setattr(attempt_repository, "PILOT_TIMER_POLICY_CODE", "broken-test-policy")
    response = attempt_client.post(
        "/api/v1/attempts",
        headers={"Idempotency-Key": "broken"},
        json={
            "question_version_id": published_question["id"],
            "mode": "practice",
            "independent_budget_seconds": 60,
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "POLICY_UNAVAILABLE"
    assert_no_secrets(response)


def test_revoked_identity_denies_grant_replay_and_history(
    attempt_client, published_question, seeded_storage
):
    attempt = start(attempt_client, published_question)
    response = grant(attempt_client, attempt, key="previous-grant")
    assert response.status_code == 200
    with seeded_storage.begin() as session:
        session.execute(
            text("DELETE FROM user_roles WHERE user_id=:id AND role='learner'"),
            {"id": ADMIN.user_id},
        )
    assert grant(attempt_client, attempt, key="previous-grant").status_code == 403
    assert attempt_client.get(f"/api/v1/attempts/{attempt['id']}/assistance").status_code == 403
    with seeded_storage.begin() as session:
        session.execute(
            text("UPDATE users SET status='disabled' WHERE id=:id"), {"id": ADMIN.user_id}
        )
    assert grant(attempt_client, attempt, key="previous-grant").status_code == 401
