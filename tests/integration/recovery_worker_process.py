"""Trusted test worker process with scoped fault barriers, using production worker classes."""

import json
import os
import selectors
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from mastery_backend.application.clock import SystemClock
from mastery_backend.application.evaluation_worker import EvaluationWorker
from mastery_backend.application.local_evaluation_runner import LocalIsolatedRunner
from mastery_backend.application.worker_authority import WorkerAuthority
from mastery_backend.infrastructure.database.evaluation_models import EvaluationJob
from mastery_backend.infrastructure.database.worker_models import EvaluationRunProvenance
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    schema = config["schema"]
    assert schema.startswith("integration_") and schema.replace("_", "").isalnum()
    engine = create_engine(
        config["database_url"], connect_args={"sslmode": "disable", "gssencmode": "disable"}
    )

    @event.listens_for(engine, "connect")
    def set_schema(connection, record):
        with connection.cursor() as cursor:
            cursor.execute('SET search_path TO "' + schema + '"')
        connection.commit()

    factory, clock = sessionmaker(engine, expire_on_commit=False), SystemClock()
    sandbox = LocalSandbox(Path(config["runtime"]))
    sandbox.startup_check()
    authority = WorkerAuthority.from_file(factory, clock, Path(config["credential"]))
    adapter = LocalIsolatedRunner(sandbox, authority)
    mode, marker = config["mode"], Path(config["marker"])

    @event.listens_for(factory, "before_commit")
    def arm(session):
        provenance = any(isinstance(row, EvaluationRunProvenance) for row in session.new)
        terminal = any(
            isinstance(row, EvaluationJob) and row.status in {"passed", "failed"}
            for row in session.identity_map.values()
        )
        if (mode == "provenance" and provenance) or (mode == "terminal" and terminal):
            Path(config["arm"]).touch(mode=0o600)

    original = sandbox.send_payload

    def send(process, payload):
        original(process, payload)
        if mode == "running":
            with selectors.DefaultSelector() as selector:
                selector.register(process.stderr, selectors.EVENT_READ)
                assert selector.select(2)
                assert os.read(process.stderr.fileno(), 64) == b"RUNNING\n"
            marker.write_text(json.dumps({"unit": sandbox.active_unit, "phase": "running"}))
            while True:
                time.sleep(0.05)

    sandbox.send_payload = send
    worker = EvaluationWorker(factory, clock, adapter, "development")
    try:
        if mode in {"running", "completed"}:
            request = worker.claim()
            assert request is not None
            result = adapter.dispatch(request)
            marker.write_text(
                json.dumps({"phase": "completed", "result": result.model_dump(mode="json")})
            )
            while True:
                time.sleep(0.05)
        else:
            try:
                assert worker.dispatch_once()
                marker.write_text(json.dumps({"phase": "returned"}))
            except Exception as error:
                marker.write_text(json.dumps({"phase": "error", "type": type(error).__name__}))
    finally:
        sandbox.cancel()
        engine.dispose()


if __name__ == "__main__":
    main()
