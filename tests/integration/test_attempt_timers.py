"""Real PostgreSQL acceptance of server-owned attempt lifecycle and clocks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.attempt_service import AttemptService
from mastery_backend.application.content_seed_service import seed_development_identity
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal
from mastery_backend.infrastructure.database.attempt_models import (
    Attempt,
    AttemptEvent,
    AttemptPhase,
    LearningPolicyVersion,
    UserQuestionFamilyHistory,
)
from mastery_backend.infrastructure.database.attempt_repository import AttemptRepository
from mastery_backend.infrastructure.database.content_models import (
    Base,
    IdempotencyRecord,
    User,
    UserRole,
)

ADMIN = Principal(UUID(int=1), frozenset({"learner", "content_admin"}))


def start(
    client: TestClient,
    published: dict,
    *,
    budget: int = 60,
    mode: str = "practice",
    key: str | None = None,
) -> dict:
    response = client.post(
        "/api/v1/attempts",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={
            "question_version_id": published["id"],
            "mode": mode,
            "independent_budget_seconds": budget,
        },
    )
    assert response.status_code == 201, response.text
    assert response.headers["Location"] == f"/api/v1/attempts/{response.json()['id']}"
    return response.json()


def mutate(
    client: TestClient,
    attempt: dict,
    action: str,
    *,
    key: str | None = None,
    revision: int | None = None,
    **payload: object,
):
    return client.post(
        f"/api/v1/attempts/{attempt['id']}/{action}",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={
            "expected_revision": attempt["revision"] if revision is None else revision,
            **payload,
        },
    )


def get(client: TestClient, attempt: dict) -> dict:
    response = client.get(f"/api/v1/attempts/{attempt['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def assert_private_absent(response) -> None:
    for marker in [
        "PRIVATE_TEST_INPUT",
        "PRIVATE_TEST_OUTPUT",
        "PRIVATE_HINT",
        "PRIVATE_SOLUTION",
        "PRIVATE_RUBRIC",
        "test_cases",
        "assistance_steps",
        "reference_code",
    ]:
        assert marker not in response.text


def test_exact_expiry_reads_write_once_and_solving_continues(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    client = attempt_client
    attempt = start(client, published_question)
    assert attempt["timer"]["phase_number"] == 0 and attempt["timer"]["remaining_ms"] == 60000
    assert attempt["policy_version"] == "pilot-timer-1"
    attempt_clock.advance(59999)
    before = get(client, attempt)
    assert before["revision"] == 1 and before["timer"]["remaining_ms"] == 1
    assert before["assistance_eligible"] is False
    with seeded_storage() as session:
        phase = session.scalar(select(AttemptPhase))
        assert phase.active_elapsed_ms == 0 and phase.expired_at is None
        assert session.scalar(select(func.count()).select_from(AttemptEvent)) == 1
    attempt_clock.advance(1)
    expired = get(client, attempt)
    assert expired["revision"] == 2 and expired["lifecycle_state"] == "active"
    assert expired["assistance_eligible"] and expired["assistance_level"] == "none"
    assert expired["timer"]["remaining_ms"] == 0 and expired["timer"]["active_elapsed_ms"] == 60000
    assert expired["independent_interval_ended_at"] == expired["timer"]["expired_at"]
    assert expired["independent_end_reason"] == "expired" and expired["finished_at"] is None
    attempt_clock.advance(10000)
    later = get(client, attempt)
    assert later["total_active_elapsed_ms"] == 70000 and later["overdue_active_elapsed_ms"] == 10000
    assert later["timer"]["expired_at"] == expired["timer"]["expired_at"]
    assert later["revision"] == 2
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(AttemptEvent)) == 2
        stored = session.scalar(select(Attempt))
        assert stored.total_active_elapsed_ms == 60000  # later read is projection only
    assert_private_absent(client.get(f"/api/v1/attempts/{attempt['id']}"))


def test_pause_resume_restart_offline_accounting_and_end(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    client = attempt_client
    attempt = start(client, published_question)
    attempt_clock.advance(12500)
    paused_response = mutate(client, attempt, "pause")
    assert paused_response.status_code == 200
    paused = paused_response.json()
    assert paused["total_active_elapsed_ms"] == 12500 and paused["timer"]["remaining_ms"] == 47500
    assert paused["lifecycle_state"] == "paused" and paused["timer"]["running_since"] is None
    attempt_clock.advance(3600000)
    # New service/session represents process recreation; no countdown object is retained.
    restarted = AttemptService(seeded_storage, attempt_clock)
    persisted = restarted.read(ADMIN, UUID(attempt["id"])).model_dump(mode="json")
    assert persisted["timer"]["remaining_ms"] == 47500
    from mastery_backend.api.dependencies import server_clock
    from mastery_backend.main import create_app

    fresh_app = create_app(client.app.state.settings)
    fresh_app.dependency_overrides[server_clock] = lambda: attempt_clock
    with TestClient(fresh_app, base_url="http://localhost") as fresh_client:
        restored = fresh_client.get(f"/api/v1/attempts/{attempt['id']}")
        assert restored.status_code == 200
        assert restored.json()["timer"]["remaining_ms"] == 47500
    resumed_response = mutate(client, paused, "resume")
    assert resumed_response.status_code == 200
    resumed = resumed_response.json()
    attempt_clock.advance(50000)
    after_offline = get(client, resumed)
    assert after_offline["timer"]["expired_at"] == (
        attempt_clock.instant - timedelta(milliseconds=2500)
    ).isoformat().replace("+00:00", "Z")
    assert after_offline["overdue_active_elapsed_ms"] == 2500
    pause_expired = mutate(client, after_offline, "pause").json()
    attempt_clock.advance(5000)
    assert get(client, pause_expired)["total_active_elapsed_ms"] == 62500
    resume_expired = mutate(client, pause_expired, "resume").json()
    assert resume_expired["timer"]["running_since"] is None
    attempt_clock.advance(4000)
    ended = mutate(client, resume_expired, "defer", reason="Continue another day")
    assert ended.status_code == 200
    deferred = ended.json()
    assert deferred["lifecycle_state"] == "deferred" and deferred["finished_at"]
    assert deferred["total_active_elapsed_ms"] == 66500
    assert deferred["independent_end_reason"] == "expired"
    assert deferred["assistance_eligible"] is False
    attempt_clock.advance(100000)
    assert get(client, deferred)["total_active_elapsed_ms"] == 66500
    for action in ["pause", "resume", "defer", "abandon", "extend"]:
        payload = {"additional_budget_seconds": 1} if action == "extend" else {}
        rejected = mutate(client, deferred, action, **payload)
        assert (
            rejected.status_code == 409
            and rejected.json()["error"]["code"] == "INVALID_ATTEMPT_STATE"
        )


def test_extension_bounds_accommodation_and_expiry_cannot_reopen(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    client = attempt_client
    attempt = start(client, published_question, mode="assessment")
    attempt_clock.advance(59999)
    extended = mutate(
        client, attempt, "extend", additional_budget_seconds=60, reason="Accommodation"
    )
    assert extended.status_code == 200
    attempt = extended.json()
    assert attempt["timer"]["budget_seconds"] == 120 and attempt["timer"]["remaining_ms"] == 60001
    assert attempt["timing_accommodated"]
    paused = mutate(client, attempt, "pause").json()
    assert paused["timing_accommodated"]
    paused_extended = mutate(client, paused, "extend", additional_budget_seconds=1800)
    assert paused_extended.status_code == 200
    paused = paused_extended.json()
    assert paused["timer"]["budget_seconds"] == 1920
    for addition in [1801, 1800]:
        rejected = mutate(client, paused, "extend", additional_budget_seconds=addition)
        assert rejected.status_code == 422 and rejected.json()["error"]["code"] == "INVALID_BUDGET"
    resumed = mutate(client, paused, "resume").json()
    attempt_clock.advance(1920000 - 59999)
    rejected = mutate(client, resumed, "extend", additional_budget_seconds=1)
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "PHASE_EXPIRED"
    with seeded_storage() as session:
        assert (
            session.scalar(select(AttemptPhase)).expired_at is None
        )  # rejected command rolled back observation
    expired = get(client, resumed)
    assert expired["timing_accommodated"] and expired["timer"]["budget_seconds"] == 1920
    assert mutate(client, expired, "extend", additional_budget_seconds=1).status_code == 409
    assert get(client, expired)["timer"]["expired_at"] == expired["timer"]["expired_at"]


@pytest.mark.parametrize("budget", [0, -1, 59, 3601, True, 60.5, "60", None])
def test_start_budget_validation(
    attempt_client: TestClient, published_question: dict, budget
) -> None:
    response = attempt_client.post(
        "/api/v1/attempts",
        headers={"Idempotency-Key": "invalid-budget"},
        json={
            "question_version_id": published_question["id"],
            "mode": "practice",
            "independent_budget_seconds": budget,
        },
    )
    assert response.status_code == 422


def test_command_validation_states_replay_and_abandon(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    client = attempt_client
    attempt = start(client, published_question, budget=3600, key="start-once")
    attempt_clock.advance(5000)
    replay = client.post(
        "/api/v1/attempts",
        headers={"Idempotency-Key": "start-once"},
        json={
            "question_version_id": published_question["id"],
            "mode": "practice",
            "independent_budget_seconds": 3600,
        },
    )
    assert (
        replay.status_code == 201
        and replay.json() == attempt
        and replay.headers["Idempotency-Replayed"] == "true"
    )
    assert mutate(client, attempt, "resume").status_code == 409
    assert mutate(client, attempt, "extend", additional_budget_seconds=1).status_code == 422
    response = mutate(client, attempt, "pause", key="pause-once")
    assert response.status_code == 200
    paused = response.json()
    assert mutate(client, attempt, "pause", key="pause-once").json() == paused
    assert mutate(client, paused, "pause").json()["error"]["code"] == "INVALID_ATTEMPT_STATE"
    assert mutate(client, attempt, "abandon").json()["error"]["code"] == "STALE_REVISION"
    conflict = mutate(client, paused, "pause", key="pause-once")
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    )
    for body in [
        {"expected_revision": True},
        {"expected_revision": 2, "elapsed_ms": 0},
        {"expected_revision": 2, "lifecycle_state": "completed"},
    ]:
        assert (
            client.post(
                f"/api/v1/attempts/{attempt['id']}/resume",
                headers={"Idempotency-Key": "invalid"},
                json=body,
            ).status_code
            == 422
        )
    abandoned_response = mutate(client, paused, "abandon", reason="Stop voluntarily")
    assert abandoned_response.status_code == 200
    abandoned = abandoned_response.json()
    assert (
        abandoned["lifecycle_state"] == "abandoned"
        and abandoned["independent_end_reason"] == "abandoned"
    )
    assert abandoned["total_active_elapsed_ms"] == 5000 and abandoned["timer"]["expired_at"] is None
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(Attempt)) == 1
        events = list(session.scalars(select(AttemptEvent).order_by(AttemptEvent.sequence_number)))
        assert [event.event_type for event in events] == ["started", "paused", "abandoned"]


def test_clock_rollback_is_safe_and_no_per_tick_mutation(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    client = attempt_client
    attempt = start(client, published_question)
    attempt_clock.advance(10000)
    paused = mutate(client, attempt, "pause").json()
    attempt_clock.advance(-1)
    read = client.get(f"/api/v1/attempts/{attempt['id']}")
    assert read.status_code == 503 and read.json()["error"]["code"] == "CLOCK_UNAVAILABLE"
    assert mutate(client, paused, "resume").status_code == 503
    with seeded_storage() as session:
        assert session.scalar(select(Attempt)).revision == 2
        assert session.scalar(select(func.count()).select_from(AttemptEvent)) == 2
    attempt_clock.advance(1)
    resumed = mutate(client, paused, "resume").json()
    for _ in range(5):
        attempt_clock.advance(500)
        assert get(client, resumed)["revision"] == 3
    with seeded_storage() as session:
        stored = session.scalar(select(Attempt))
        assert stored.total_active_elapsed_ms == 10000 and stored.last_event_sequence == 3


def test_concurrent_commands_and_expiry_observation(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    attempt = start(attempt_client, published_question)
    service = AttemptService(seeded_storage, attempt_clock)
    barrier = Barrier(2)

    def action(command_name):
        barrier.wait(timeout=5)
        try:
            return service.command(ADMIN, str(uuid4()), UUID(attempt["id"]), command_name, 1)
        except ContentError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(action, "pause"), executor.submit(action, "abandon")]
        results = [future.result(timeout=10) for future in futures]
    errors = [result for result in results if isinstance(result, ContentError)]
    assert len(errors) == 1 and errors[0].code == "STALE_REVISION"
    with seeded_storage() as session:
        assert session.scalar(select(Attempt)).revision == 2
        assert session.scalar(select(func.count()).select_from(AttemptEvent)) == 2
    second = start(attempt_client, published_question)
    attempt_clock.advance(60000)

    def read():
        barrier.wait(timeout=5)
        return service.read(ADMIN, UUID(second["id"]))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: read(), range(2)))
    assert [result.revision for result in results] == [2, 2]
    with seeded_storage() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AttemptEvent)
                .where(
                    AttemptEvent.attempt_id == UUID(second["id"]),
                    AttemptEvent.event_type == "expired",
                )
            )
            == 1
        )


def test_concurrent_start_replay_and_family_snapshot(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    barrier = Barrier(2)
    service = AttemptService(seeded_storage, attempt_clock)

    def create():
        barrier.wait(timeout=5)
        return service.start(ADMIN, "simultaneous", UUID(published_question["id"]), "practice", 60)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create(), range(2)))
    assert results[0].body == results[1].body
    assert sorted(result.replayed for result in results) == [False, True]
    assert results[0].body["family_previously_attempted"] is False
    assert start(attempt_client, published_question)["family_previously_attempted"] is True
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(Attempt)) == 2
        assert session.scalar(select(func.count()).select_from(UserQuestionFamilyHistory)) == 1


def test_ownership_stored_learner_role_and_identity_guards(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    client = attempt_client
    attempt = start(client, published_question, key="owner-start")
    other = uuid4()
    seed_development_identity(seeded_storage, other, "Other learner", {"learner", "content_admin"})
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"development_user_id": other}
    )
    for path in [f"/api/v1/attempts/{attempt['id']}", f"/api/v1/attempts/{attempt['id']}/question"]:
        assert client.get(path).status_code == 404
    for action in ["pause", "resume", "defer", "abandon", "extend"]:
        payload = {"additional_budget_seconds": 1} if action == "extend" else {}
        assert mutate(client, attempt, action, **payload).status_code == 404
    assert client.get("/api/v1/attempts").json()["items"] == []
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"development_user_id": ADMIN.user_id}
    )
    with seeded_storage.begin() as session:
        session.delete(session.get(UserRole, (ADMIN.user_id, "learner")))
    assert (
        client.get(f"/api/v1/attempts/{attempt['id']}", headers={"X-Role": "learner"}).status_code
        == 403
    )
    assert mutate(client, attempt, "pause").status_code == 403
    assert (
        client.post(
            "/api/v1/attempts",
            headers={"Idempotency-Key": "owner-start"},
            json={
                "question_version_id": published_question["id"],
                "mode": "practice",
                "independent_budget_seconds": 60,
            },
        ).status_code
        == 403
    )
    with pytest.raises(ContentError) as revoked:
        AttemptService(seeded_storage, attempt_clock).read(ADMIN, UUID(attempt["id"]))
    assert revoked.value.code == "FORBIDDEN"
    with seeded_storage.begin() as session:
        session.get(User, ADMIN.user_id).status = "disabled"
    assert client.get("/api/v1/attempts").status_code == 401
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"development_user_id": None}
    )
    assert client.get("/api/v1/attempts").status_code == 401


def test_pin_published_version_and_archived_owner_access(
    attempt_client: TestClient,
    published_question: dict,
    complete_draft: dict[str, object],
) -> None:
    client = attempt_client
    attempt = start(client, published_question)
    later = client.post(
        f"/api/v1/admin/questions/{published_question['question_id']}/versions",
        headers={"Idempotency-Key": "later-version"},
        json={**complete_draft, "title": "New version title"},
    )
    assert later.status_code == 201
    assert (
        client.post(
            "/api/v1/attempts",
            headers={"Idempotency-Key": "draft-start"},
            json={
                "question_version_id": later.json()["id"],
                "mode": "practice",
                "independent_budget_seconds": 60,
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/admin/question-versions/{later.json()['id']}/publish",
            headers={"Idempotency-Key": "publish-later"},
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    pinned = client.get(f"/api/v1/attempts/{attempt['id']}/question")
    assert pinned.status_code == 200 and pinned.json()["id"] == published_question["id"]
    assert pinned.json()["title"] == complete_draft["title"]
    assert (
        client.get(f"/api/v1/questions/{published_question['question_id']}").json()["title"]
        == "New version title"
    )
    assert (
        client.post(
            f"/api/v1/admin/questions/{published_question['question_id']}/archive",
            headers={"Idempotency-Key": "archive-pinned"},
            json={"expected_revision": published_question["question_revision"]},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/questions/{published_question['question_id']}").status_code == 404
    assert client.get(f"/api/v1/question-versions/{published_question['id']}").status_code == 404
    historical = client.get(f"/api/v1/attempts/{attempt['id']}/question")
    assert historical.status_code == 200 and historical.json() == pinned.json()
    assert_private_absent(historical)
    assert mutate(client, attempt, "pause").status_code == 200
    assert (
        client.post(
            "/api/v1/attempts",
            headers={"Idempotency-Key": "archived-start"},
            json={
                "question_version_id": published_question["id"],
                "mode": "practice",
                "independent_budget_seconds": 60,
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/attempts",
            headers={"Idempotency-Key": "invalid-owner"},
            json={
                "question_version_id": published_question["id"],
                "mode": "practice",
                "independent_budget_seconds": 60,
                "user_id": str(ADMIN.user_id),
            },
        ).status_code
        == 422
    )


def test_failed_start_and_transition_roll_back_all_facts(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = attempt_client
    original = AttemptRepository.append_event

    def fail_after_flush(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.session.flush()
        raise RuntimeError("PRIVATE_TEST_INPUT failure")

    monkeypatch.setattr(AttemptRepository, "append_event", fail_after_flush)
    response = client.post(
        "/api/v1/attempts",
        headers={"Idempotency-Key": "failed-start"},
        json={
            "question_version_id": published_question["id"],
            "mode": "practice",
            "independent_budget_seconds": 60,
        },
    )
    assert response.status_code == 500
    assert_private_absent(response)
    with seeded_storage() as session:
        for model in [Attempt, AttemptPhase, AttemptEvent, UserQuestionFamilyHistory]:
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert (
            session.get(IdempotencyRecord, (ADMIN.user_id, "POST /api/v1/attempts", "failed-start"))
            is None
        )
    monkeypatch.setattr(AttemptRepository, "append_event", original)
    attempt = start(client, published_question)
    attempt_clock.advance(10000)
    monkeypatch.setattr(AttemptRepository, "append_event", fail_after_flush)
    assert mutate(client, attempt, "pause", key="failed-pause").status_code == 500
    monkeypatch.setattr(AttemptRepository, "append_event", original)
    assert get(client, attempt)["revision"] == 1
    with seeded_storage() as session:
        phase = session.scalar(select(AttemptPhase))
        stored = session.scalar(select(Attempt))
        assert stored.lifecycle_state == "active" and stored.total_active_elapsed_ms == 0
        assert phase.active_elapsed_ms == 0 and phase.running_since is not None
        assert session.scalar(select(func.count()).select_from(AttemptEvent)) == 1
    assert mutate(client, attempt, "pause", key="failed-pause").status_code == 200


def test_attempt_lists_bound_filters_cursors_and_expiry(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
) -> None:
    client = attempt_client
    first = start(client, published_question)
    attempt_clock.advance(1000)
    second = start(client, published_question, mode="assessment")
    attempt_clock.advance(1000)
    third = start(client, published_question)
    page = client.get("/api/v1/attempts", params={"limit": 1}).json()
    assert page["items"][0]["id"] == third["id"] and page["next_cursor"]
    next_page = client.get(
        "/api/v1/attempts", params={"limit": 1, "cursor": page["next_cursor"]}
    ).json()
    assert next_page["items"][0]["id"] == second["id"]
    assert (
        client.get("/api/v1/attempts", params={"mode": "assessment"}).json()["items"][0]["id"]
        == second["id"]
    )
    for query in [{"cursor": "invalid"}, {"cursor": page["next_cursor"], "mode": "practice"}]:
        assert client.get("/api/v1/attempts", params=query).status_code == 400
    for query in [{"limit": 101}, {"owner_id": str(ADMIN.user_id)}]:
        assert client.get("/api/v1/attempts", params=query).status_code == 422
    attempt_clock.advance(60000)
    response = client.get("/api/v1/attempts")
    assert response.status_code == 200
    assert all(
        item["revision"] == 2 and item["assistance_eligible"] for item in response.json()["items"]
    )
    assert_private_absent(response)
    assert get(client, first)["revision"] == 2


def test_policy_version_history_and_constraints_protect_against_sql(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    attempt = start(attempt_client, published_question, mode="assessment")
    paused = mutate(attempt_client, attempt, "pause").json()
    statements = [
        "UPDATE attempts SET user_id=:other WHERE id=:id",
        "UPDATE attempts SET policy_version_id=:other WHERE id=:id",
        "UPDATE attempts SET question_version_id=:other WHERE id=:id",
        "UPDATE attempts SET timing_accommodated=false WHERE id=:id",
        "DELETE FROM attempts WHERE id=:id",
        "UPDATE attempt_events SET event_type='abandoned' WHERE attempt_id=:id",
        "DELETE FROM attempt_events WHERE attempt_id=:id",
        "UPDATE learning_policy_versions SET version_code='changed'",
        "UPDATE learning_policy_versions SET configuration_json='{}'::jsonb",
        "DELETE FROM learning_policy_versions",
        "DELETE FROM user_question_family_history",
    ]
    for statement in statements:
        with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
            session.execute(text(statement), {"id": UUID(attempt["id"]), "other": uuid4()})
        assert caught.value.orig.sqlstate == "23514"
    resumed = mutate(attempt_client, paused, "resume").json()
    attempt_clock.advance(60000)
    expired = get(attempt_client, resumed)
    for statement in [
        "UPDATE attempt_phases SET expired_at=NULL,closed_at=NULL WHERE attempt_id=:id",
        "UPDATE attempt_phases SET budget_seconds=61 WHERE attempt_id=:id",
        "UPDATE attempts SET independent_interval_ended_at=NULL,independent_end_reason=NULL "
        "WHERE id=:id",
    ]:
        with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
            session.execute(text(statement), {"id": UUID(attempt["id"])})
        assert caught.value.orig.sqlstate == "23514"
    assert get(attempt_client, expired)["revision"] == expired["revision"]
    with pytest.raises(IntegrityError) as negative, seeded_storage.begin() as session:
        session.execute(
            text("UPDATE attempt_phases SET budget_seconds=0 WHERE attempt_id=:id"),
            {"id": UUID(attempt["id"])},
        )
    assert negative.value.orig.sqlstate == "23514"


def test_migration_upgrade_from_b2_existing_data(database_connection: Connection) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.upgrade(config, "0003_skill_graph")
    database_connection.execute(
        text("INSERT INTO curricula(id,code,title,graph_revision) VALUES (:id,'KEEP','Keep',7)"),
        {"id": uuid4()},
    )
    database_connection.commit()
    command.upgrade(config, "head")
    assert database_connection.scalar(text("SELECT graph_revision FROM curricula")) == 7
    assert (
        database_connection.scalar(text("SELECT version_code FROM learning_policy_versions"))
        == "pilot-timer-1"
    )
    assert compare_metadata(MigrationContext.configure(database_connection), Base.metadata) == []
    database_connection.commit()
    command.upgrade(config, "head")
    assert database_connection.scalar(text("SELECT count(*) FROM learning_policy_versions")) == 1
    database_connection.commit()
    command.downgrade(config, "0003_skill_graph")
    assert database_connection.scalar(text("SELECT graph_revision FROM curricula")) == 7
    database_connection.commit()
    command.upgrade(config, "head")
    database_connection.commit()


def test_expiry_reconciliation_in_command_and_early_defer(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    attempt = start(attempt_client, published_question)
    attempt_clock.advance(60000)
    paused = mutate(attempt_client, attempt, "pause")
    assert paused.status_code == 200
    assert paused.json()["revision"] == 3 and paused.json()["assistance_eligible"]
    with seeded_storage() as session:
        events = list(session.scalars(select(AttemptEvent).order_by(AttemptEvent.sequence_number)))
        assert [event.event_type for event in events] == ["started", "expired", "paused"]
        assert events[1].command_id == events[2].command_id
    another = start(attempt_client, published_question)
    attempt_clock.advance(500)
    early = mutate(attempt_client, another, "defer", reason="No conclusion")
    assert early.status_code == 200
    assert early.json()["independent_end_reason"] == "deferred"
    assert early.json()["timer"]["expired_at"] is None and not early.json()["assistance_eligible"]
    assert early.json()["total_active_elapsed_ms"] == 500


def test_expired_command_receipt_and_batched_owned_list(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import event

    first = start(attempt_client, published_question, key="receipt-expiry")
    with seeded_storage.begin() as session:
        session.get(
            IdempotencyRecord, (ADMIN.user_id, "POST /api/v1/attempts", "receipt-expiry")
        ).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    second = start(attempt_client, published_question, key="receipt-expiry")
    assert first["id"] != second["id"] and second["family_previously_attempted"]
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = seeded_storage.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    before_calls = attempt_clock.calls
    try:
        response = attempt_client.get("/api/v1/attempts")
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert response.status_code == 200 and len(response.json()["items"]) == 2
    assert attempt_clock.calls == before_calls + 1
    assert len([sql for sql in statements if "FROM learning_policy_versions" in sql]) == 1
    assert not any(sql.lstrip().startswith(("UPDATE", "INSERT", "DELETE")) for sql in statements)
    assert not any(
        table in sql
        for sql in statements
        for table in ["question_test_cases", "question_solutions", "question_assistance_steps"]
    )


def test_question_mode_policy_pinning_and_missing_inputs(
    attempt_client: TestClient,
    published_question: dict,
    complete_draft: dict[str, object],
    seeded_storage: sessionmaker[Session],
) -> None:
    client = attempt_client
    draft = client.post(
        f"/api/v1/admin/questions/{published_question['question_id']}/versions",
        headers={"Idempotency-Key": "practice-only"},
        json={**complete_draft, "supported_modes": ["practice"], "assessment_role": "practice"},
    )
    assert draft.status_code == 201
    assert (
        client.post(
            f"/api/v1/admin/question-versions/{draft.json()['id']}/publish",
            headers={"Idempotency-Key": "publish-practice"},
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    for mode in ["assessment", "transfer"]:
        denied = client.post(
            "/api/v1/attempts",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "question_version_id": draft.json()["id"],
                "mode": mode,
                "independent_budget_seconds": 60,
            },
        )
        assert denied.status_code == 422
    for body in [
        {"question_version_id": str(uuid4()), "mode": "practice", "independent_budget_seconds": 60},
        {
            "question_version_id": published_question["id"],
            "mode": "practice",
            "independent_budget_seconds": 60,
        },
    ]:
        response = client.post(
            "/api/v1/attempts",
            json=body,
            headers={"Idempotency-Key": "missing-version"}
            if body["question_version_id"] != published_question["id"]
            else {},
        )
        assert response.status_code in {404, 422}
    attempt = start(client, published_question, budget=2400)
    with seeded_storage.begin() as session:
        session.add(
            LearningPolicyVersion(
                version_code="future-smaller-policy",
                configuration_json={
                    "minimum_budget_seconds": 60,
                    "maximum_budget_seconds": 500,
                    "maximum_extension_seconds": 100,
                    "allowed_modes": ["practice"],
                },
                effective_at=session.get(
                    LearningPolicyVersion, UUID(attempt["policy_version_id"])
                ).effective_at,
            )
        )
    extended = mutate(client, attempt, "extend", additional_budget_seconds=1200)
    assert extended.status_code == 200 and extended.json()["timer"]["budget_seconds"] == 3600
    assert extended.json()["policy_version_id"] == attempt["policy_version_id"]
    assert extended.json()["policy_version"] == "pilot-timer-1"
    for path in ["assistance/next", "submissions", "draft"]:
        assert client.post(f"/api/v1/attempts/{attempt['id']}/{path}", json={}).status_code == 404


def test_closure_checks_closed_phase_freeze_and_relational_constraints(
    attempt_client: TestClient,
    published_question: dict,
    attempt_clock,
    seeded_storage: sessionmaker[Session],
) -> None:
    attempt = start(attempt_client, published_question)
    identifier = UUID(attempt["id"])
    for statement in [
        "UPDATE attempts SET independent_interval_ended_at=started_at WHERE id=:id",
        "UPDATE attempt_phases SET expired_at=started_at,closed_at=NULL,"
        "running_since=NULL,active_elapsed_ms=60000 WHERE attempt_id=:id",
    ]:
        with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
            session.execute(text(statement), {"id": identifier})
        assert caught.value.orig.sqlstate == "23514"
    with pytest.raises(IntegrityError) as duplicate, seeded_storage.begin() as session:
        session.add(
            AttemptPhase(
                attempt_id=identifier,
                started_at=attempt_clock.instant,
                budget_seconds=60,
                running_since=attempt_clock.instant,
            )
        )
        session.flush()
    assert duplicate.value.orig.sqlstate == "23505"
    with pytest.raises(IntegrityError) as missing, seeded_storage.begin() as session:
        session.add(
            AttemptPhase(
                attempt_id=uuid4(),
                started_at=attempt_clock.instant,
                budget_seconds=60,
                running_since=attempt_clock.instant,
            )
        )
        session.flush()
    assert missing.value.orig.sqlstate == "23503"
    with pytest.raises(IntegrityError) as sequence, seeded_storage.begin() as session:
        session.add(
            AttemptEvent(
                attempt_id=identifier,
                sequence_number=1,
                event_type="started",
                occurred_at=attempt_clock.instant,
                payload_json={},
                command_id=uuid4(),
            )
        )
        session.flush()
    assert sequence.value.orig.sqlstate == "23505"
    with pytest.raises(IntegrityError) as policy_fk, seeded_storage.begin() as session:
        session.add(
            Attempt(
                user_id=ADMIN.user_id,
                question_version_id=UUID(published_question["id"]),
                policy_version_id=uuid4(),
                mode="practice",
                lifecycle_state="active",
                started_at=attempt_clock.instant,
                total_running_since=attempt_clock.instant,
                last_reconciled_at=attempt_clock.instant,
                family_previously_attempted=True,
            )
        )
        session.flush()
    assert policy_fk.value.orig.sqlstate == "23503"
    assert mutate(attempt_client, attempt, "defer").status_code == 200
    with pytest.raises(IntegrityError) as closed, seeded_storage.begin() as session:
        session.execute(
            text("UPDATE attempt_phases SET budget_seconds=61 WHERE attempt_id=:id"),
            {"id": identifier},
        )
    assert closed.value.orig.sqlstate == "23514"
