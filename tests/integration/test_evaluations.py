"""Real PostgreSQL orchestration tests. The adapter below never interprets source."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from test_submissions import (
    ADMIN,
    SOURCE,
    assert_private_absent,
    current,
    help_request,
    mutate,
    start,
    submit,
)

from mastery_backend.api.dependencies import runner_adapter
from mastery_backend.application.evaluation_service import EvaluationService
from mastery_backend.application.evaluation_worker import EvaluationWorker
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.evaluations import RunnerCorrelation, RunnerResult
from mastery_backend.infrastructure.database.attempt_models import Attempt
from mastery_backend.infrastructure.database.evaluation_models import (
    EvaluationDispatchIntent,
    EvaluationEvent,
    EvaluationJob,
)
from mastery_backend.infrastructure.database.evaluation_models import (
    TestBundleMember as BundleMember,
)


@pytest.fixture
def complete_draft(complete_draft):
    draft = dict(complete_draft)
    draft["test_cases"] = [
        *draft["test_cases"],
        {
            "position": 2,
            "visibility": "public",
            "input": ["hello"],
            "expected_output": "hello",
            "critical": False,
        },
    ]
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


class FixtureAdapter:
    identity = "test-only-orchestration"

    def __init__(self):
        self.requests = []
        self.outcome = "passed"
        self.failure = None
        self.during_dispatch = None

    def dispatch(self, request):
        self.requests.append(request)
        if self.during_dispatch:
            self.during_dispatch(request)
        if self.failure:
            raise self.failure
        return result_for(request, self.outcome)


def result_for(request, outcome="passed", **changes):
    return RunnerResult(
        **{
            **request.model_dump(include=set(RunnerCorrelation.model_fields)),
            "outcome": outcome,
            **changes,
        }
    )


@pytest.fixture
def adapter(attempt_client):
    binding = FixtureAdapter()
    attempt_client.app.dependency_overrides[runner_adapter] = lambda: binding
    return binding


@pytest.fixture
def receipt(attempt_client, published_question):
    attempt = start(attempt_client, published_question)
    response = submit(attempt_client, attempt)
    assert response.status_code == 201
    return response.json()


def request_job(client, receipt, *, key=None, revision=None):
    return client.post(
        f"/api/v1/submissions/{receipt['id']}/evaluations",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"expected_revision": revision or receipt["attempt_revision"]},
    )


def worker(factory, clock, adapter):
    return EvaluationWorker(factory, clock, adapter, "test")


def test_unavailable_is_atomic_and_adapter_cannot_enable_development(
    attempt_client,
    receipt,
    seeded_storage,
    attempt_clock,
):
    before = current(attempt_client, {"id": receipt["attempt_id"]})
    attempt_clock.advance(60000)
    response = request_job(attempt_client, receipt)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EVALUATION_UNAVAILABLE"
    assert_private_absent(response)
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationJob)) == 0
        assert session.get(Attempt, UUID(receipt["attempt_id"])).revision == before["revision"]
    for environment in ["development", "production"]:
        service = EvaluationService(seeded_storage, attempt_clock, FixtureAdapter(), environment)
        with pytest.raises(ContentError, match="supported isolated evaluator"):
            service.request(ADMIN, UUID(receipt["id"]), "denied", receipt["attempt_revision"])
        with pytest.raises(ContentError):
            EvaluationWorker(seeded_storage, attempt_clock, FixtureAdapter(), environment).claim()


def test_atomic_pins_retry_and_pending_rules(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
):
    response = request_job(attempt_client, receipt, key="stable")
    assert response.status_code == 202, response.text
    detail = response.json()
    assert detail["status"] == "pending" and detail["category"] is None
    assert detail["question_version_id"] == receipt["question_version_id"]
    assert detail["policy_version_id"] == receipt["policy_version_id"]
    assert detail["submission_id"] == receipt["id"]
    assert len(detail["transitions"]) == 1
    assert_private_absent(response)
    assert SOURCE not in response.text and "lease_token" not in response.text
    with seeded_storage() as session:
        assert session.get(EvaluationDispatchIntent, UUID(detail["id"])) is not None
        assert session.scalar(select(func.count()).select_from(BundleMember)) == 2
    replay = request_job(attempt_client, receipt, key="stable")
    assert replay.json() == detail and replay.headers["Idempotency-Replayed"] == "true"
    assert request_job(attempt_client, receipt, key="stable", revision=99).status_code == 409
    assert request_job(attempt_client, receipt).json()["error"]["code"] == "EVALUATION_EXISTS"
    latest = current(attempt_client, {"id": receipt["attempt_id"]})
    assert help_request(attempt_client, latest).json()["error"]["code"] == "EVALUATION_PENDING"
    assert submit(attempt_client, latest).json()["error"]["code"] == "EVALUATION_PENDING"
    assert submit(attempt_client, latest, purpose="public_run").status_code == 201
    latest = current(attempt_client, latest)
    escaped = attempt_client.post(
        f"/api/v1/attempts/{latest['id']}/assistance/solution",
        headers={"Idempotency-Key": "escape"},
        json={"expected_revision": latest["revision"], "confirmation": True},
    )
    assert escaped.status_code == 409
    ended = mutate(attempt_client, latest, "abandon")
    assert ended["lifecycle_state"] == "abandoned"
    execution = worker(seeded_storage, attempt_clock, adapter)
    assert execution.dispatch_once()
    assert attempt_client.get(response.headers["Location"]).json()["status"] == "passed"
    assert current(attempt_client, ended)["lifecycle_state"] == "abandoned"
    attempt_client.app.dependency_overrides.pop(runner_adapter)
    assert request_job(attempt_client, receipt, key="stable").json() == detail
    assert attempt_client.get(f"/api/v1/submissions/{receipt['id']}").json() == receipt


@pytest.mark.parametrize(
    "outcome,status",
    [
        ("passed", "passed"),
        ("incorrect", "failed"),
        ("syntax_error", "failed"),
        ("resource_limit", "failed"),
    ],
)
def test_results_duplicate_terminal_and_safe_categories(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    outcome,
    status,
):
    admitted = request_job(attempt_client, receipt).json()
    execution = worker(seeded_storage, attempt_clock, adapter)
    request = execution.claim()
    assert request.source_code == SOURCE
    assert request.source_hash == receipt["code_hash"]
    assert len(request.tests) == 2
    result = result_for(request, outcome)
    assert execution.apply_result(result)
    assert not execution.apply_result(result)
    assert not execution.apply_result(result_for(request, "incorrect"))
    response = attempt_client.get(f"/api/v1/evaluations/{admitted['id']}")
    detail = response.json()
    assert detail["status"] == status and detail["category"] == outcome
    assert len(detail["transitions"]) == 3
    assert_private_absent(response)
    assert "tests" not in response.text and SOURCE not in response.text
    with seeded_storage.begin() as session:
        with pytest.raises(IntegrityError) as error:
            session.execute(
                text("UPDATE evaluation_jobs SET status='pending' WHERE id=:id"),
                {"id": admitted["id"]},
            )
        assert error.value.orig.sqlstate == "23514"


@pytest.mark.parametrize(
    "change",
    [
        {"runner_identity": "forged"},
        {"submission_id": UUID(int=999)},
        {"question_version_id": UUID(int=999)},
        {"policy_version_id": UUID(int=999)},
        {"test_bundle_id": UUID(int=999)},
        {"evaluator_policy_version_id": UUID(int=999)},
        {"source_hash": "a" * 64},
        {"bundle_hash": "b" * 64},
        {"lease_token": UUID(int=999)},
    ],
)
def test_mismatched_results_are_ignored(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    change,
):
    admitted = request_job(attempt_client, receipt).json()
    execution = worker(seeded_storage, attempt_clock, adapter)
    request = execution.claim()
    assert not execution.apply_result(result_for(request, **change))
    assert attempt_client.get(f"/api/v1/evaluations/{admitted['id']}").json()["status"] == "running"
    assert execution.apply_result(result_for(request))


@pytest.mark.parametrize("offset", [29999, 30000, 30001])
def test_lease_boundary_recovery_and_stale_generation(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    offset,
):
    request_job(attempt_client, receipt)
    execution = worker(seeded_storage, attempt_clock, adapter)
    old = execution.claim()
    attempt_clock.advance(offset)
    if offset < 30000:
        assert execution.apply_result(result_for(old))
        assert execution.recover() == 0
    else:
        assert not execution.apply_result(result_for(old))
        assert execution.recover() == 1
        assert execution.recover() == 0
        assert execution.claim() is None
        attempt_clock.advance(5000)
        new = worker(seeded_storage, attempt_clock, adapter).claim()
        assert new.generation == 2 and new.lease_token != old.lease_token
        assert not execution.apply_result(result_for(old))
        assert execution.apply_result(result_for(new))


@pytest.mark.parametrize(
    "failure", [RuntimeError("PRIVATE_SOLUTION"), TimeoutError("PRIVATE_TEST_INPUT")]
)
def test_dispatch_failure_bounded_retries(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    failure,
):
    admitted = request_job(attempt_client, receipt).json()
    adapter.failure = failure
    execution = worker(seeded_storage, attempt_clock, adapter)
    for backoff in [5000, 10000, 0]:
        assert execution.dispatch_once()
        attempt_clock.advance(backoff)
    response = attempt_client.get(f"/api/v1/evaluations/{admitted['id']}")
    assert response.json()["status"] == "infrastructure_error"
    assert response.json()["category"] == "infrastructure_error"
    assert len(response.json()["transitions"]) == 7
    assert_private_absent(response)
    assert not execution.dispatch_once()


def test_overall_deadline_recovery_and_dispatch_outside_transaction(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
):
    response = request_job(attempt_client, receipt)
    admitted = response.json()
    adapter.during_dispatch = lambda request: current(attempt_client, {"id": receipt["attempt_id"]})

    # A separate DB transaction can acquire the job lock during the adapter call.
    def acquire_lock(request):
        from mastery_backend.infrastructure.observability.logging import request_id_context

        assert request.request_id == response.headers["X-Request-ID"]
        assert request_id_context.get() == request.request_id
        with seeded_storage.begin() as session:
            session.execute(text("SET LOCAL lock_timeout='250ms'"))
            session.execute(
                select(EvaluationJob).where(EvaluationJob.id == request.job_id).with_for_update()
            )
        attempt_clock.advance(300000)

    adapter.during_dispatch = acquire_lock
    execution = worker(seeded_storage, attempt_clock, adapter)
    assert execution.dispatch_once()
    response = attempt_client.get(f"/api/v1/evaluations/{admitted['id']}")
    assert response.json()["status"] == "infrastructure_error"
    assert not execution.apply_result(result_for(adapter.requests[0]))


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_admission_creates_one_job(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    same_key,
):
    barrier = Barrier(2)

    def admit(index):
        service = EvaluationService(seeded_storage, attempt_clock, adapter, "test")
        barrier.wait()
        try:
            return service.request(
                ADMIN,
                UUID(receipt["id"]),
                "shared" if same_key else str(index),
                receipt["attempt_revision"],
            )
        except ContentError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit, [0, 1]))
    successful = [result for result in results if not isinstance(result, str)]
    assert len(successful) == (2 if same_key else 1)
    if same_key:
        assert successful[0].body == successful[1].body
        assert sum(result.replayed for result in successful) == 1
    else:
        assert "EVALUATION_EXISTS" in results
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationJob)) == 1
        assert session.scalar(select(func.count()).select_from(EvaluationDispatchIntent)) == 1
        assert session.scalar(select(func.count()).select_from(EvaluationEvent)) == 1


def test_concurrent_help_and_evaluation_ordering(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
):
    from mastery_backend.application.assistance_service import AssistanceService

    barrier = Barrier(2)

    def run(operation):
        barrier.wait()
        try:
            if operation == "help":
                return AssistanceService(seeded_storage, attempt_clock).grant(
                    ADMIN,
                    UUID(receipt["attempt_id"]),
                    "help",
                    "next",
                    receipt["attempt_revision"],
                    "learner_request",
                )
            return EvaluationService(seeded_storage, attempt_clock, adapter, "test").request(
                ADMIN, UUID(receipt["id"]), "job", receipt["attempt_revision"]
            )
        except ContentError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ["help", "evaluation"]))
    assert sum(not isinstance(result, str) for result in results) == 1
    assert "STALE_REVISION" in results
    assert attempt_client.get(f"/api/v1/submissions/{receipt['id']}").json() == receipt
    latest = current(attempt_client, {"id": receipt["attempt_id"]})
    if results[0] == "STALE_REVISION":
        assert help_request(attempt_client, latest).json()["error"]["code"] == "EVALUATION_PENDING"
    else:
        # Saved pre-help evidence stays immutable even if evaluation is requested later.
        assert request_job(attempt_client, receipt, revision=latest["revision"]).status_code == 202


def test_concurrent_result_and_recovery_no_terminal_overwrite(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
):
    request_job(attempt_client, receipt)
    execution = worker(seeded_storage, attempt_clock, adapter)
    request = execution.claim()
    barrier = Barrier(2)

    def finish(index):
        barrier.wait()
        return worker(seeded_storage, attempt_clock, adapter).apply_result(
            result_for(request, "passed" if index else "incorrect")
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(finish, [0, 1])) == [False, True]
    assert execution.recover() == 0
    assert not execution.dispatch_failed(request)


def test_ownership_roles_and_no_public_callbacks(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
):
    from mastery_backend.application.content_seed_service import seed_development_identity
    from mastery_backend.infrastructure.database.content_models import UserRole

    admitted = request_job(attempt_client, receipt, key="owner")
    paths = [admitted.headers["Location"], f"/api/v1/attempts/{receipt['attempt_id']}/evaluations"]
    for roles in [{"learner"}, {"content_admin", "learner"}]:
        other = uuid4()
        seed_development_identity(seeded_storage, other, "Other learner", roles)
        attempt_client.app.state.settings = attempt_client.app.state.settings.model_copy(
            update={"development_user_id": other}
        )
        for path in paths:
            response = attempt_client.get(path)
            assert response.status_code == 404
            assert_private_absent(response)
        assert request_job(attempt_client, receipt, key="owner").status_code == 404
    attempt_client.app.state.settings = attempt_client.app.state.settings.model_copy(
        update={"development_user_id": UUID(int=1)}
    )
    with seeded_storage.begin() as session:
        session.delete(session.get(UserRole, (UUID(int=1), "learner")))
    for path in paths:
        assert attempt_client.get(path).status_code == 403
    assert request_job(attempt_client, receipt, key="owner").status_code == 403
    attempt_client.app.state.settings = attempt_client.app.state.settings.model_copy(
        update={"development_user_id": None}
    )
    assert request_job(attempt_client, receipt).status_code == 401
    assert (
        attempt_client.post(
            f"/api/v1/evaluations/{admitted.json()['id']}/result", json={"status": "passed"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("action", ["defer", "abandon"])
def test_invalid_admission_lifecycle(attempt_client, receipt, adapter, action):
    attempt = current(attempt_client, {"id": receipt["attempt_id"]})
    ended = mutate(attempt_client, attempt, action)
    response = request_job(attempt_client, receipt, revision=ended["revision"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_ATTEMPT_STATE"


def test_admission_rollback_and_retry_after_lost_response(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    monkeypatch,
):
    from mastery_backend.infrastructure.database.evaluation_repository import EvaluationRepository

    original = EvaluationRepository.transitions

    def fail_after_flush(repo, identifier):
        original(repo, identifier)
        raise RuntimeError("PRIVATE_SOLUTION")

    monkeypatch.setattr(EvaluationRepository, "transitions", fail_after_flush)
    attempt_clock.advance(60000)
    response = request_job(attempt_client, receipt, key="recover")
    assert response.status_code == 500
    assert_private_absent(response)
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationJob)) == 0
        assert session.scalar(select(func.count()).select_from(EvaluationDispatchIntent)) == 0
        attempt = session.get(Attempt, UUID(receipt["attempt_id"]))
        assert attempt.revision == receipt["attempt_revision"]
        assert attempt.independent_interval_ended_at is None
    monkeypatch.setattr(EvaluationRepository, "transitions", original)
    response = request_job(attempt_client, receipt, key="recover")
    assert response.status_code == 202, response.text
    assert request_job(attempt_client, receipt, key="recover").json() == response.json()


def test_result_rollback_retry_and_history_guards(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    monkeypatch,
):
    admitted = request_job(attempt_client, receipt).json()
    execution = worker(seeded_storage, attempt_clock, adapter)
    request = execution.claim()
    original = EvaluationWorker.transition

    def failing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("post-result failure")

    monkeypatch.setattr(EvaluationWorker, "transition", staticmethod(failing))
    with pytest.raises(RuntimeError):
        execution.apply_result(result_for(request))
    with seeded_storage() as session:
        assert session.get(EvaluationJob, request.job_id).status == "running"
        assert session.scalar(select(func.count()).select_from(EvaluationEvent)) == 2
    monkeypatch.setattr(EvaluationWorker, "transition", staticmethod(original))
    assert execution.apply_result(result_for(request))
    statements = [
        "DELETE FROM evaluation_jobs",
        "UPDATE evaluation_jobs SET question_version_id=:id",
        "UPDATE evaluation_events SET reason_code='changed'",
        "DELETE FROM evaluation_events",
        "UPDATE evaluation_dispatch_intents SET request_id='changed'",
        "UPDATE evaluation_request_receipts SET request_key='changed'",
        "UPDATE evaluator_policy_versions SET version_code='changed'",
        "UPDATE evaluation_test_bundles SET content_hash='changed'",
        "DELETE FROM evaluation_test_bundle_members",
    ]
    for statement in statements:
        with pytest.raises(IntegrityError) as error, seeded_storage.begin() as session:
            session.execute(text(statement), {"id": uuid4()})
        assert error.value.orig.sqlstate == "23514"
    assert attempt_client.get(f"/api/v1/evaluations/{admitted['id']}").json()["status"] == "passed"


def test_public_bundle_bounded_pagination_and_archived_version_pins(
    attempt_client,
    published_question,
    complete_draft,
    adapter,
    seeded_storage,
    attempt_clock,
):
    import json
    from base64 import urlsafe_b64decode, urlsafe_b64encode
    from datetime import UTC, datetime, timedelta

    client = attempt_client
    attempt = start(client, published_question)
    jobs = []
    for _index in range(4):
        response = submit(client, attempt, purpose="public_run")
        received = response.json()
        response = request_job(client, received)
        assert response.status_code == 202, response.text
        jobs.append(response.json())
        attempt = current(client, attempt)
    path = f"/api/v1/attempts/{attempt['id']}/evaluations"
    first = client.get(path, params={"limit": 2})
    assert [item["id"] for item in first.json()["items"]] == [jobs[3]["id"], jobs[2]["id"]]
    original_cursor = first.json()["next_cursor"]
    # Equal timestamps still have strictly ordered acceptance event sequences.
    later_receipt = submit(client, attempt, purpose="public_run").json()
    assert request_job(client, later_receipt).status_code == 202
    seen = [item["id"] for item in first.json()["items"]]
    cursor = original_cursor
    while cursor:
        page = client.get(path, params={"limit": 2, "cursor": cursor})
        assert page.status_code == 200
        assert_private_absent(page)
        seen.extend(item["id"] for item in page.json()["items"])
        cursor = page.json()["next_cursor"]
    assert seen == [job["id"] for job in reversed(jobs)]
    for params in [{"limit": 0}, {"limit": 101}, {"unknown": "PRIVATE_SOLUTION"}]:
        assert client.get(path, params=params).status_code == 422
    assert client.get(path, params={"cursor": "bad"}).status_code == 400
    decoded = json.loads(urlsafe_b64decode(original_cursor))
    decoded["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert (
        client.get(
            path, params={"cursor": urlsafe_b64encode(json.dumps(decoded).encode()).decode()}
        ).status_code
        == 400
    )
    other = start(client, published_question)
    assert (
        client.get(
            f"/api/v1/attempts/{other['id']}/evaluations", params={"cursor": original_cursor}
        ).status_code
        == 400
    )
    client.app.state.settings = client.app.state.settings.model_copy(update={"max_page_size": 1})
    assert client.get(path, params={"limit": 2}).status_code == 422
    created = client.post(
        f"/api/v1/admin/questions/{published_question['question_id']}/versions",
        headers={"Idempotency-Key": "next-version"},
        json={**complete_draft, "statement": "New question"},
    )
    assert created.status_code == 201
    assert (
        client.post(
            f"/api/v1/admin/question-versions/{created.json()['id']}/publish",
            headers={"Idempotency-Key": "publish-next"},
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/admin/questions/{published_question['question_id']}/archive",
            headers={"Idempotency-Key": "archive"},
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    execution = worker(seeded_storage, attempt_clock, adapter)
    request = execution.claim()
    assert len(request.tests) == 1 and request.tests[0].visibility == "public"
    assert request.question_version_id == UUID(published_question["id"])
    assert execution.apply_result(result_for(request))
    assert_private_absent(client.get(f"/api/v1/evaluations/{request.job_id}"))
    # A new request for an owned historical receipt is also allowed after archival.
    archived = submit(client, current(client, attempt), purpose="public_run").json()
    assert request_job(client, archived).status_code == 202


def test_real_b5_upgrade_preserves_receipts_and_refuses_history_downgrade(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    database_connection,
):
    from pathlib import Path

    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext

    from mastery_backend.infrastructure.database.content_models import Base

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.downgrade(config, "0006_immutable_submissions")
    database_connection.commit()
    before = [
        dict(row)
        for row in database_connection.execute(text("SELECT * FROM submissions")).mappings()
    ]
    database_connection.commit()
    command.upgrade(config, "head")
    database_connection.commit()
    assert [
        dict(row)
        for row in database_connection.execute(text("SELECT * FROM submissions")).mappings()
    ] == before
    assert compare_metadata(MigrationContext.configure(database_connection), Base.metadata) == []
    database_connection.commit()
    response = request_job(attempt_client, receipt)
    assert response.status_code == 202, response.text
    with pytest.raises(IntegrityError) as error:
        command.downgrade(config, "0006_immutable_submissions")
    assert error.value.orig.sqlstate == "23514"
    database_connection.rollback()
    assert (
        database_connection.scalar(text("SELECT version_num FROM alembic_version"))
        == "0007_evaluation_lifecycle"
    )
    database_connection.commit()
    assert attempt_client.get(response.headers["Location"]).status_code == 200


@pytest.mark.parametrize("offset", [299999, 300000, 300001])
def test_help_deadline_recovers_without_worker(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    offset,
):
    admitted = request_job(attempt_client, receipt).json()
    attempt_clock.advance(offset)
    latest = current(attempt_client, {"id": receipt["attempt_id"]})
    response = help_request(attempt_client, latest)
    if offset < 300000:
        assert (
            response.status_code == 409 and response.json()["error"]["code"] == "EVALUATION_PENDING"
        )
        assert (
            attempt_client.get(f"/api/v1/evaluations/{admitted['id']}").json()["status"]
            == "pending"
        )
    else:
        assert response.status_code == 200, response.text
        detail = attempt_client.get(f"/api/v1/evaluations/{admitted['id']}").json()
        assert detail["status"] == "infrastructure_error"
        assert detail["transitions"][-1]["reason_code"] == "DEADLINE_EXCEEDED"
        assert worker(seeded_storage, attempt_clock, adapter).recover() == 0


def test_pending_expiry_rolls_back_with_failed_help(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    monkeypatch,
):
    from mastery_backend.infrastructure.database.assistance_repository import AssistanceRepository

    admitted = request_job(attempt_client, receipt).json()
    attempt_clock.advance(300000)
    latest = current(attempt_client, {"id": receipt["attempt_id"]})
    monkeypatch.setattr(AssistanceRepository, "next_step", lambda *args: None)
    assert help_request(attempt_client, latest).status_code == 500
    assert attempt_client.get(f"/api/v1/evaluations/{admitted['id']}").json()["status"] == "pending"
    assert worker(seeded_storage, attempt_clock, adapter).recover() == 1


def test_runner_infrastructure_result_backoff_and_protocol_privacy(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
):
    from pydantic import ValidationError

    request_job(attempt_client, receipt)
    execution = worker(seeded_storage, attempt_clock, adapter)
    request = execution.claim()
    for changes in [
        {"protocol_version": 2},
        {"outcome": "made_up"},
        {"diagnostics": "PRIVATE_SOLUTION"},
        {"stdout": SOURCE},
    ]:
        with pytest.raises(ValidationError):
            result_for(request, **changes)
    assert execution.apply_result(result_for(request, "infrastructure_error"))
    assert execution.claim() is None
    attempt_clock.advance(5000)
    request2 = execution.claim()
    assert request2.generation == 2
    assert execution.apply_result(result_for(request2, "syntax_error"))


def test_concurrent_claims_and_backward_clock(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
):
    request_job(attempt_client, receipt)
    barrier = Barrier(2)

    def claim(_index):
        barrier.wait()
        return worker(seeded_storage, attempt_clock, adapter).claim()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, [0, 1]))
    request = next(item for item in claims if item is not None)
    assert sum(item is not None for item in claims) == 1
    attempt_clock.advance(-1)
    with pytest.raises(ContentError) as error:
        worker(seeded_storage, attempt_clock, adapter).apply_result(result_for(request))
    assert error.value.code == "CLOCK_UNAVAILABLE"
    attempt_clock.advance(1)
    assert worker(seeded_storage, attempt_clock, adapter).apply_result(result_for(request))


def test_validation_and_pending_public_run_request(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
):
    client = attempt_client
    public = submit(
        client, current(client, {"id": receipt["attempt_id"]}), purpose="public_run"
    ).json()
    latest = current(client, {"id": receipt["attempt_id"]})
    path = f"/api/v1/submissions/{receipt['id']}/evaluations"
    for extra in [
        {"owner_id": str(uuid4())},
        {"status": "passed"},
        {"source_code": "PRIVATE_SOLUTION"},
        {"question_version_id": str(uuid4())},
        {"expected_revision": 0},
    ]:
        response = client.post(
            path,
            headers={"Idempotency-Key": str(uuid4())},
            json={"expected_revision": latest["revision"], **extra},
        )
        assert response.status_code == 422
        assert_private_absent(response)
    assert request_job(client, receipt, revision=999).json()["error"]["code"] == "STALE_REVISION"
    assert request_job(client, receipt, revision=latest["revision"]).status_code == 202
    latest = current(client, latest)
    blocked = request_job(client, public, revision=latest["revision"])
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "EVALUATION_PENDING"
    assert worker(seeded_storage, attempt_clock, adapter).dispatch_once()
    assert request_job(client, public, revision=latest["revision"]).status_code == 202
    assert client.get(f"/api/v1/evaluations/{uuid4()}").status_code == 404


@pytest.mark.parametrize("kind", ["malformed", "wrong_identity", "late"])
def test_invalid_dispatch_results_are_infrastructure_faults(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    monkeypatch,
    kind,
):
    admitted = request_job(attempt_client, receipt).json()

    def dispatch(request):
        if kind == "late":
            attempt_clock.advance(30000)
            return result_for(request)
        if kind == "wrong_identity":
            return result_for(request, runner_identity="forged")
        return {"outcome": "passed", "diagnostics": "PRIVATE_SOLUTION"}

    monkeypatch.setattr(adapter, "dispatch", dispatch)
    assert worker(seeded_storage, attempt_clock, adapter).dispatch_once()
    response = attempt_client.get(f"/api/v1/evaluations/{admitted['id']}")
    assert response.json()["status"] == "pending"
    assert response.json()["category"] is None
    assert response.json()["transitions"][-1]["reason_code"] == (
        "RUNNER_TIMEOUT" if kind == "late" else "INVALID_RESULT"
    )
    assert_private_absent(response)


def test_policy_version_pins_missing_policy_and_log_privacy(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    monkeypatch,
    caplog,
):
    from mastery_backend.application import evaluation_service
    from mastery_backend.domain.evaluations import POLICY_CONFIG
    from mastery_backend.infrastructure.database.evaluation_models import EvaluationPolicyVersion
    from mastery_backend.infrastructure.observability.logging import JsonLogFormatter

    missing = uuid4()
    monkeypatch.setattr(evaluation_service, "POLICY_ID", missing)
    assert request_job(attempt_client, receipt).status_code == 503
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationJob)) == 0
    monkeypatch.undo()
    admitted = request_job(attempt_client, receipt).json()
    with seeded_storage.begin() as session:
        session.add(
            EvaluationPolicyVersion(
                id=uuid4(),
                version_code="future-policy",
                configuration_json={**POLICY_CONFIG, "maximum_dispatches": 1},
            )
        )
    execution = worker(seeded_storage, attempt_clock, adapter)
    request = execution.claim()
    assert str(request.evaluator_policy_version_id) == admitted["evaluator_policy_version_id"]
    wrong_binding = FixtureAdapter()
    wrong_binding.identity = "other-runner"
    assert not worker(seeded_storage, attempt_clock, wrong_binding).apply_result(
        result_for(request)
    )
    assert execution.apply_result(result_for(request))
    formatter = JsonLogFormatter()
    records = [record for record in caplog.records if record.getMessage() == "evaluation_requested"]
    assert len(records) == 1
    log = formatter.format(records[0])
    assert admitted["id"] in log
    assert SOURCE not in log
    assert "lease_token" not in log and "PRIVATE_" not in log
    attempt_clock.advance(9 * 86400000)
    calls = attempt_clock.calls
    # Find the permanent receipt's original key and recover the initial response unchanged.
    from mastery_backend.infrastructure.database.evaluation_models import EvaluationRequestReceipt

    with seeded_storage() as session:
        key = session.scalar(select(EvaluationRequestReceipt.request_key))
    assert request_job(attempt_client, receipt, key=key).json() == admitted
    assert attempt_clock.calls == calls


def test_detail_projection_and_history_share_job_lock(
    attempt_client,
    receipt,
    adapter,
    seeded_storage,
    attempt_clock,
    monkeypatch,
):
    from mastery_backend.infrastructure.database.evaluation_repository import EvaluationRepository

    admitted = request_job(attempt_client, receipt).json()
    original = EvaluationRepository.transitions

    def read_while_claiming(repo, identifier):
        # The reader holds the job projection lock before its second SELECT.
        assert worker(seeded_storage, attempt_clock, adapter).claim() is None
        return original(repo, identifier)

    monkeypatch.setattr(EvaluationRepository, "transitions", read_while_claiming)
    response = attempt_client.get(f"/api/v1/evaluations/{admitted['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == response.json()["transitions"][-1]["state"] == "pending"
    monkeypatch.setattr(EvaluationRepository, "transitions", original)
    assert worker(seeded_storage, attempt_clock, adapter).claim() is not None
