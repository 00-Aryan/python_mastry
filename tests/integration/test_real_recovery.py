"""Real lost PostgreSQL acknowledgements and elapsed-time leases, never accelerated clocks."""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from recovery_wire import CommitReplyLoss
from sqlalchemy import func, select, text
from test_evaluations import request_job
from test_local_runner import complete_draft as complete_draft
from test_submissions import assert_private_absent, start, submit

from mastery_backend.application.clock import SystemClock
from mastery_backend.application.evaluation_worker import EvaluationWorker
from mastery_backend.application.local_evaluation_runner import LocalIsolatedRunner
from mastery_backend.application.worker_authority import LocalRunnerAdmission, provision_worker
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.evaluations import RunnerResult
from mastery_backend.infrastructure.database.evaluation_models import EvaluationEvent, EvaluationJob
from mastery_backend.infrastructure.database.worker_models import (
    EvaluationRunProvenance,
    ExecutionWorkerIdentity,
)
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox


@pytest.fixture
def attempt_clock():
    return SystemClock()


@pytest.fixture
def recovery_binding(seeded_storage, attempt_clock, isolated_runtime, tmp_path, attempt_client):
    sandbox = LocalSandbox(isolated_runtime)
    sandbox.startup_check()
    key = tmp_path / "worker.json"
    authority = provision_worker(
        seeded_storage, attempt_clock, key, sandbox.image_hash, sandbox.profile_hash
    )
    binding = LocalIsolatedRunner(sandbox, authority)
    authority.heartbeat(True)
    attempt_client.app.state.settings.local_runner_enabled = True
    yield binding, key
    sandbox.cancel()


def configuration(factory, binding, key, tmp_path, mode, port=None):
    with factory() as session:
        url = session.get_bind().url
        schema = session.scalar(text("SELECT current_schema()"))
    if port is not None:
        url = url.set(host="127.0.0.1", port=port)
    assert url.database.endswith("_test") and url.host in {"localhost", "127.0.0.1"}
    payload = dict(
        database_url=url.render_as_string(hide_password=False),
        schema=schema,
        runtime=str(binding.sandbox.directory),
        credential=str(key),
        mode=mode,
        marker=str(tmp_path / "worker-marker.json"),
        arm=str(tmp_path / "arm"),
    )
    path = tmp_path / "configuration.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(payload, output)
    return path, Path(payload["marker"])


def launch(config):
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("recovery_worker_process.py")), str(config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop(process):
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def wait_marker(process, marker):
    deadline = time.monotonic() + 12
    while not marker.exists() and time.monotonic() < deadline:
        assert process.poll() is None, "Worker exited before the controlled fault boundary"
        time.sleep(0.02)
    assert marker.exists(), "Worker did not reach the controlled fault boundary"
    # A write can be observed before its descriptor is closed; read until complete JSON.
    while time.monotonic() < deadline:
        try:
            return json.loads(marker.read_text())
        except json.JSONDecodeError:
            time.sleep(0.01)
    pytest.fail("Incomplete worker marker")


def wait_until(target):
    started = time.monotonic()
    remaining = (target - datetime.now(UTC)).total_seconds()
    assert remaining < 40, "Unexpected policy wait; never shorten policy for the test"
    while datetime.now(UTC) < target:
        time.sleep(min(0.1, max(0.001, (target - datetime.now(UTC)).total_seconds())))
    return time.monotonic() - started


def recorded_result(factory, job_id, generation=1):
    with factory() as session:
        record = session.get(EvaluationRunProvenance, (job_id, generation)).record_json
        return RunnerResult.model_validate({key: record[key] for key in RunnerResult.model_fields})


def terminal_count(factory, job_id):
    with factory() as session:
        return session.scalar(
            select(func.count())
            .select_from(EvaluationEvent)
            .where(
                EvaluationEvent.job_id == job_id,
                EvaluationEvent.state.in_(["passed", "failed", "infrastructure_error"]),
            )
        )


@pytest.mark.parametrize("mode", ["provenance", "terminal"])
def test_actual_postgres_commit_reply_loss(
    recovery_binding,
    seeded_storage,
    attempt_clock,
    attempt_client,
    published_question,
    tmp_path,
    mode,
    record_property,
):
    binding, key = recovery_binding
    receipt = submit(
        attempt_client,
        start(attempt_client, published_question),
        source="def echo(word): return word",
    ).json()
    response = request_job(attempt_client, receipt)
    assert response.status_code == 202
    job_id = UUID(response.json()["id"])
    with seeded_storage() as session:
        target = session.get_bind().url
    with CommitReplyLoss(target.host, target.port or 5432, tmp_path / "arm") as proxy:
        config, marker = configuration(seeded_storage, binding, key, tmp_path, mode, proxy.port)
        child = launch(config)
        try:
            observed = wait_marker(child, marker)
            child.wait(timeout=5)
            assert proxy.dropped.is_set(), "No real COMMIT acknowledgement was dropped"
            assert observed["phase"] == ("returned" if mode == "provenance" else "error")
        finally:
            stop(child)
    record_property("wire_commit_reply_dropped", mode)
    worker = EvaluationWorker(seeded_storage, attempt_clock, binding, "development")
    old = recorded_result(seeded_storage, job_id)
    assert binding.verify_result(old)  # Real signed durable row, not a fabricated outcome.
    assert worker.apply_result(old) is False
    with seeded_storage() as session:
        job = session.get(EvaluationJob, job_id)
        assert job.generation == 1
        assert job.status == ("pending" if mode == "provenance" else "passed")
        retry_at = job.next_retry_at
    if mode == "provenance":
        assert terminal_count(seeded_storage, job_id) == 0
        assert worker.claim() is None
        elapsed = wait_until(retry_at)
        record_property("actual_backoff_wait_seconds", elapsed)
        fresh = worker.claim()
        assert fresh.generation == 2 and fresh.lease_token != old.lease_token
        assert worker.apply_result(old) is False
        result = binding.dispatch(fresh)
        assert worker.apply_result(result) is True
    else:
        assert worker.recover() == 0 and worker.claim() is None
    assert worker.apply_result(old) is False
    assert terminal_count(seeded_storage, job_id) == 1
    status = attempt_client.get(f"/api/v1/evaluations/{job_id}")
    assert status.json()["status"] == "passed"
    assert_private_absent(status)


@pytest.mark.parametrize("phase", ["completed", "running"])
def test_real_sigkill_wall_clock_lease_recovery(
    recovery_binding,
    seeded_storage,
    attempt_clock,
    attempt_client,
    published_question,
    tmp_path,
    phase,
    record_property,
):
    binding, key = recovery_binding
    source = (
        "def echo(word):\n import os\n os.write(2,b'RUNNING\\n')\n while True: pass"
        if phase == "running"
        else "def echo(word): return word"
    )
    receipt = submit(
        attempt_client, start(attempt_client, published_question), source=source
    ).json()
    response = request_job(attempt_client, receipt)
    assert response.status_code == 202
    job_id = UUID(response.json()["id"])
    config, marker = configuration(seeded_storage, binding, key, tmp_path, phase)
    child, started = launch(config), time.monotonic()
    unit = None
    try:
        observed = wait_marker(child, marker)
        unit = observed.get("unit")
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=5)
        assert child.returncode == -signal.SIGKILL
        with seeded_storage() as session:
            job = session.get(EvaluationJob, job_id)
            assert job.status == "running" and job.generation == 1
            lease_until = job.lease_until
            leased_at = session.scalar(
                select(EvaluationEvent.occurred_at).where(
                    EvaluationEvent.job_id == job_id,
                    EvaluationEvent.generation == 1,
                    EvaluationEvent.state == "running",
                )
            )
            assert (lease_until - leased_at).total_seconds() == 30
        if unit:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                state = subprocess.run(
                    ["/usr/bin/systemctl", "--user", "is-active", unit],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=2,
                )
                if state.stdout.strip() not in {"active", "activating", "deactivating"}:
                    break
                time.sleep(0.05)
            assert state.stdout.strip() not in {"active", "activating", "deactivating"}
            group = subprocess.run(
                [
                    "/usr/bin/systemctl",
                    "--user",
                    "show",
                    unit,
                    "--property=ControlGroup",
                    "--value",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            ).stdout.strip()
            procs = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
            assert not group or not procs.exists() or not procs.read_text().strip()
        worker = EvaluationWorker(seeded_storage, attempt_clock, binding, "development")
        assert worker.recover() == 0
        wait_until(lease_until)
        assert time.monotonic() - started >= 29, "Lease was not observed in real elapsed time"
        if phase == "completed":
            old = recorded_result(seeded_storage, job_id)
            assert binding.verify_result(old)
            assert worker.apply_result(old) is False  # Expired but authentic lease result.
        with pytest.raises(ContentError):
            LocalRunnerAdmission(seeded_storage, attempt_clock)  # Real 15-second heartbeat expired.
        recovery_started = time.monotonic()
        assert worker.recover() == 1
        assert worker.recover() == 0
        assert worker.claim() is None
        with seeded_storage() as session:
            job = session.get(EvaluationJob, job_id)
            assert job.status == "pending" and job.category is None
            retry_at = job.next_retry_at
        waited = wait_until(retry_at)
        assert time.monotonic() - recovery_started >= 5
        record_property("actual_backoff_wait_seconds", waited)
        fresh = worker.claim()
        assert fresh.generation == 2
        if phase == "completed":
            assert fresh.lease_token != old.lease_token and worker.apply_result(old) is False
        result = binding.dispatch(fresh)
        assert result.outcome == ("resource_limit" if phase == "running" else "passed")
        assert binding.dispatch(fresh) == result
        assert worker.apply_result(result) is True
        assert worker.apply_result(result) is False
        assert terminal_count(seeded_storage, job_id) == 1
        assert worker.recover() == 0
        with seeded_storage.begin() as session:
            session.get(ExecutionWorkerIdentity, binding.authority.worker_id).revoked = True
        with pytest.raises(ContentError):
            worker.apply_result(result)
        assert terminal_count(seeded_storage, job_id) == 1
        record_property("actual_total_elapsed_seconds", time.monotonic() - started)
    finally:
        stop(child)
        if unit:
            subprocess.run(
                ["/usr/bin/systemctl", "--user", "stop", unit],
                check=False,
                capture_output=True,
                timeout=5,
            )
            subprocess.run(
                ["/usr/bin/systemctl", "--user", "reset-failed", unit],
                check=False,
                capture_output=True,
                timeout=5,
            )
