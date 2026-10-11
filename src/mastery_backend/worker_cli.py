"""Dedicated local worker command. No learner source executes in this process."""

import argparse
import signal
import threading
from pathlib import Path

from mastery_backend.application.clock import SystemClock
from mastery_backend.application.evaluation_worker import EvaluationWorker
from mastery_backend.application.local_evaluation_runner import LocalIsolatedRunner
from mastery_backend.application.worker_authority import WorkerAuthority, provision_worker
from mastery_backend.domain.content import ContentError
from mastery_backend.infrastructure.database.session import (
    create_database_engine,
    create_session_factory,
)
from mastery_backend.infrastructure.observability.logging import configure_logging, logger
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox
from mastery_backend.infrastructure.runner.runtime_image import build_runtime
from mastery_backend.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail-closed local isolated evaluation worker")
    parser.add_argument("command", choices=["build-runtime", "probe", "provision", "once", "serve"])
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--credential", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "build-runtime":
        build_runtime(arguments.runtime)
        print("Curated runtime created; run probe before provisioning.")
        return
    sandbox = LocalSandbox(arguments.runtime)
    sandbox.startup_check()
    if arguments.command == "probe":
        print("Mandatory isolation controls verified.")
        return
    if arguments.credential is None:
        parser.error("--credential is required for authenticated worker commands")
    settings = Settings()
    configure_logging(settings.log_level)
    if settings.app_env != "development":
        parser.error("Local workers are available only in development")
    engine = create_database_engine(settings)
    factory, clock = create_session_factory(engine), SystemClock()
    authority: WorkerAuthority | None = None
    stopped = threading.Event()

    def stop(signum: int, frame: object) -> None:
        stopped.set()
        sandbox.cancel()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        if arguments.command == "provision":
            provision_worker(
                factory, clock, arguments.credential, sandbox.image_hash, sandbox.profile_hash
            )
            print("Worker provisioned; credential stored only in the owner-only file.")
            return
        authority = WorkerAuthority.from_file(factory, clock, arguments.credential)
        adapter = LocalIsolatedRunner(sandbox, authority)
        worker = EvaluationWorker(factory, clock, adapter, "development")
        while not stopped.is_set():
            sandbox.startup_check()
            authority.heartbeat(True)
            worker.recover()
            dispatched = worker.dispatch_once()
            if arguments.command == "once":
                print("One dispatch completed." if dispatched else "No eligible job.")
                break
            if not dispatched:
                stopped.wait(1)
    finally:
        sandbox.cancel()
        try:
            if authority is not None:
                try:
                    authority.heartbeat(False)
                except ContentError:
                    logger.warning("worker_readiness_withdrawal_denied")
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
