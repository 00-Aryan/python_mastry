"""Real isolated execution connected to PostgreSQL jobs, authority and immutable evidence."""

import hashlib
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from test_evaluations import request_job, result_for
from test_submissions import assert_private_absent, start, submit

from mastery_backend.application.evaluation_worker import EvaluationWorker
from mastery_backend.application.local_evaluation_runner import LocalIsolatedRunner
from mastery_backend.application.worker_authority import (
    LocalRunnerAdmission,
    WorkerAuthority,
    provision_worker,
)
from mastery_backend.domain.content import ContentError
from mastery_backend.infrastructure.database.evaluation_models import (
    EvaluationJob,
    EvaluationPolicyVersion,
)
from mastery_backend.infrastructure.database.worker_models import (
    EvaluationRunProvenance,
    ExecutionWorkerIdentity,
)
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox


@pytest.fixture
def complete_draft(complete_draft):
    draft = dict(complete_draft)
    draft["test_cases"] = [
        {
            "position": 1,
            "visibility": "private",
            "input": ["PRIVATE_TEST_INPUT"],
            "expected_output": "PRIVATE_TEST_INPUT",
            "critical": True,
        }
    ]
    return draft


@pytest.fixture
def real_binding(seeded_storage, attempt_clock, isolated_runtime, tmp_path, attempt_client):
    sandbox = LocalSandbox(isolated_runtime)
    sandbox.startup_check()
    key = tmp_path / "worker-credential.json"
    authority = provision_worker(
        seeded_storage, attempt_clock, key, sandbox.image_hash, sandbox.profile_hash
    )
    binding = LocalIsolatedRunner(sandbox, authority)
    authority.heartbeat(True)
    binding.credential_file = key
    attempt_client.app.state.settings.local_runner_enabled = True
    yield binding
    sandbox.cancel()


@pytest.mark.parametrize(
    "source,category,state",
    [
        ("def echo(word): return word", "passed", "passed"),
        ('def echo(word): return "wrong"', "incorrect", "failed"),
        ("def echo(:", "syntax_error", "failed"),
        ('def echo(word): raise RuntimeError("PRIVATE_DIAGNOSTIC")', "runtime_error", "failed"),
    ],
)
def test_real_job_results_pins_authenticity_and_safe_status(
    attempt_client,
    published_question,
    real_binding,
    seeded_storage,
    attempt_clock,
    source,
    category,
    state,
):
    attempt = start(attempt_client, published_question)
    receipt = submit(attempt_client, attempt, source=source).json()
    response = request_job(attempt_client, receipt, key="real-evaluation")
    assert response.status_code == 202, response.text
    identifier = UUID(response.json()["id"])
    worker = EvaluationWorker(seeded_storage, attempt_clock, real_binding, "development")
    request = worker.claim()
    assert request.protocol_version == 2
    assert request.evaluator_policy_version_id == real_binding.evaluator_policy_id
    # No source-derived correctness inference; unsigned fabricated results are rejected.
    assert worker.apply_result(result_for(request)) is False
    result = real_binding.dispatch(request)
    assert result.outcome == category
    assert real_binding.dispatch(request) == result  # durable duplicate delivery, no second run
    assert worker.apply_result(result) is True
    assert worker.apply_result(result) is False
    status = attempt_client.get(f"/api/v1/evaluations/{identifier}")
    assert status.json()["status"] == state
    assert status.json()["category"] == category
    assert_private_absent(status)
    assert source not in status.text and "PRIVATE_DIAGNOSTIC" not in status.text
    replay = request_job(attempt_client, receipt, key="real-evaluation")
    assert replay.json() == response.json()
    with seeded_storage() as session:
        provenance = session.get(EvaluationRunProvenance, (identifier, 1))
        assert provenance.record_json["source_hash"] == hashlib.sha256(source.encode()).hexdigest()
        assert provenance.record_json["runtime_image_hash"] == real_binding.sandbox.image_hash
        assert real_binding.authority.verify(provenance.record_json, provenance.signature)
        policy = session.get(EvaluationPolicyVersion, real_binding.evaluator_policy_id)
        assert policy.configuration_json["protocol_version"] == 2
        assert "PRIVATE_TEST_INPUT" not in str(provenance.record_json)
    with seeded_storage.begin() as session, pytest.raises(IntegrityError):
        session.execute(text("UPDATE evaluation_run_provenance SET signature = repeat('0',64)"))


def test_worker_credentials_readiness_revocation_and_learner_separation(
    real_binding,
    seeded_storage,
    attempt_clock,
    attempt_client,
    published_question,
):
    authority = real_binding.authority
    forged = WorkerAuthority(seeded_storage, attempt_clock, UUID(int=1), authority.credential)
    with pytest.raises(ContentError):
        forged.authenticate()
    forged = WorkerAuthority(seeded_storage, attempt_clock, authority.worker_id, "learner-token")
    with pytest.raises(ContentError):
        forged.authenticate()
    admission = LocalRunnerAdmission(seeded_storage, attempt_clock)
    assert admission.identity == real_binding.identity
    attempt_clock.advance(15000)
    receipt = submit(attempt_client, start(attempt_client, published_question)).json()
    response = request_job(attempt_client, receipt)
    assert response.status_code == 503
    with seeded_storage() as session:
        assert session.scalar(select(EvaluationJob.id)) is None
    authority.heartbeat(True)
    with seeded_storage.begin() as session:
        session.get(ExecutionWorkerIdentity, authority.worker_id).revoked = True
    with pytest.raises(ContentError):
        EvaluationWorker(seeded_storage, attempt_clock, real_binding, "development").claim()
    assert request_job(attempt_client, receipt).status_code == 503


def test_real_abandoned_lease_recovery_and_stale_signed_result(
    real_binding,
    seeded_storage,
    attempt_clock,
    attempt_client,
    published_question,
):
    receipt = submit(
        attempt_client,
        start(attempt_client, published_question),
        source="def echo(word): return word",
    ).json()
    job = request_job(attempt_client, receipt).json()
    worker = EvaluationWorker(seeded_storage, attempt_clock, real_binding, "development")
    old = worker.claim()
    old_result = real_binding.dispatch(old)
    # Deliberately abandon an actual claimed/completed dispatch without applying its result.
    # Clock-controlled lease recovery is NOT a claim of process-crash verification.
    attempt_clock.advance(30000)
    assert worker.recover() == 1
    assert worker.apply_result(old_result) is False
    attempt_clock.advance(5000)
    fresh = worker.claim()
    assert fresh.generation == 2 and fresh.lease_token != old.lease_token
    fresh_result = real_binding.dispatch(fresh)
    assert worker.apply_result(fresh_result) is True
    assert worker.apply_result(old_result) is False
    assert worker.recover() == 0
    with seeded_storage() as session:
        assert session.get(EvaluationJob, UUID(job["id"])).status == "passed"
        assert len(session.scalars(select(EvaluationRunProvenance)).all()) == 2


def test_backend_failure_retry_and_atomic_rollback(
    real_binding,
    seeded_storage,
    attempt_clock,
    attempt_client,
    published_question,
    monkeypatch,
):
    receipt = submit(attempt_client, start(attempt_client, published_question)).json()
    assert request_job(attempt_client, receipt).status_code == 202
    worker = EvaluationWorker(seeded_storage, attempt_clock, real_binding, "development")

    def fail(*arguments):
        raise RuntimeError("private infrastructure details")

    monkeypatch.setattr(real_binding.sandbox, "execute", fail)
    assert worker.dispatch_once()
    with seeded_storage() as session:
        job = session.scalar(select(EvaluationJob))
        assert job.status == "pending" and job.category is None
        assert (
            session.get(EvaluationRunProvenance, (job.id, 1)).record_json["outcome"]
            == "infrastructure_error"
        )
    assert worker.recover() == 0


def test_actual_worker_crash_leaves_lease_then_recovers(
    real_binding,
    seeded_storage,
    attempt_clock,
    attempt_client,
    published_question,
    tmp_path,
):
    import os
    import signal
    import subprocess
    import sys
    import time

    receipt = submit(
        attempt_client,
        start(attempt_client, published_question),
        source="def echo(word):\n while True: pass",
    ).json()
    job = request_job(attempt_client, receipt).json()
    marker = tmp_path / "actual-worker-unit"
    with seeded_storage() as session:
        url = session.get_bind().url.render_as_string(hide_password=False)
        schema = session.scalar(text("SELECT current_schema()"))
    # URL is a disposable local test DB, never the IDE .env or its credentials.
    script = """import sys
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from mastery_backend.application.worker_authority import WorkerAuthority
from mastery_backend.application.evaluation_worker import EvaluationWorker
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox
from mastery_backend.application.local_evaluation_runner import LocalIsolatedRunner
engine=create_engine(sys.argv[1])
@event.listens_for(engine, 'connect')
def schema(dbapi, record):
 with dbapi.cursor() as cursor: cursor.execute('SET search_path TO "' + sys.argv[2] + '"')
 dbapi.commit()
class Clock:
 def now(self): return datetime.fromisoformat(sys.argv[6])
factory=sessionmaker(engine,expire_on_commit=False)
sandbox=LocalSandbox(Path(sys.argv[3]))
sandbox.startup_check()
authority=WorkerAuthority.from_file(factory,Clock(),Path(sys.argv[4]))
adapter=LocalIsolatedRunner(sandbox,authority)
original=sandbox.verify_controls
def controls(unit,process):
 original(unit,process)
 Path(sys.argv[5]).write_text(unit)
sandbox.verify_controls=controls
EvaluationWorker(factory,Clock(),adapter,'development').dispatch_once()
"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            url,
            schema,
            str(real_binding.sandbox.directory),
            str(real_binding.credential_file),
            str(marker),
            attempt_clock.now().isoformat(),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 6
        while not marker.exists() and time.monotonic() < deadline:
            assert process.poll() is None, "Actual evaluation worker exited before execution"
            time.sleep(0.02)
        assert marker.exists()
        unit = marker.read_text()
        time.sleep(0.2)  # Allow the trusted handshake/source write to reach the running workload.
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
        assert process.returncode == -signal.SIGKILL
        with seeded_storage() as session:
            assert session.get(EvaluationJob, UUID(job["id"])).status == "running"
            assert session.get(EvaluationRunProvenance, (UUID(job["id"]), 1)) is None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = subprocess.run(
                ["/usr/bin/systemctl", "--user", "is-active", unit],
                capture_output=True,
                text=True,
                check=False,
            )
            if state.stdout.strip() != "active":
                break
            time.sleep(0.05)
        assert state.stdout.strip() != "active"
        worker = EvaluationWorker(seeded_storage, attempt_clock, real_binding, "development")
        attempt_clock.advance(30000)
        assert worker.recover() == 1
        attempt_clock.advance(5000)
        assert worker.dispatch_once()
        with seeded_storage() as session:
            current = session.get(EvaluationJob, UUID(job["id"]))
            assert current.generation == 2 and current.category == "resource_limit"
            assert current.status == "failed"
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        if marker.exists():
            subprocess.run(
                ["/usr/bin/systemctl", "--user", "stop", marker.read_text()],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            subprocess.run(
                ["/usr/bin/systemctl", "--user", "reset-failed", marker.read_text()],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def test_b6a_upgrade_preserves_live_job_and_version_one_policy(
    attempt_client,
    published_question,
    seeded_storage,
    database_connection,
    attempt_clock,
):
    from pathlib import Path

    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from test_evaluations import FixtureAdapter

    from mastery_backend.api.dependencies import runner_adapter
    from mastery_backend.domain.evaluations import POLICY_CONFIG, POLICY_ID
    from mastery_backend.infrastructure.database.content_models import Base

    attempt_client.app.dependency_overrides[runner_adapter] = lambda: FixtureAdapter()
    receipt = submit(attempt_client, start(attempt_client, published_question)).json()
    response = request_job(attempt_client, receipt)
    assert response.status_code == 202
    identifier = UUID(response.json()["id"])
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.downgrade(config, "0007_evaluation_lifecycle")
    database_connection.commit()
    with seeded_storage() as session:
        before = session.get(EvaluationJob, identifier)
        assert before.status == "pending" and before.evaluator_policy_version_id == POLICY_ID
        assert session.get(EvaluationPolicyVersion, POLICY_ID).configuration_json == POLICY_CONFIG
    command.upgrade(config, "head")
    database_connection.commit()
    assert compare_metadata(MigrationContext.configure(database_connection), Base.metadata) == []
    with seeded_storage() as session:
        after = session.get(EvaluationJob, identifier)
        assert after.status == "pending" and after.evaluator_policy_version_id == POLICY_ID
        assert after.submission_id == UUID(receipt["id"])
        assert session.get(EvaluationPolicyVersion, POLICY_ID).configuration_json == POLICY_CONFIG
