"""Operator-provisioned worker credentials, readiness and result authenticity."""

import hashlib
import hmac
import json
import os
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.clock import Clock
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.evaluations import EvaluationPolicy, RunnerRequest, RunnerResult
from mastery_backend.infrastructure.database.evaluation_models import EvaluationPolicyVersion
from mastery_backend.infrastructure.database.worker_models import ExecutionWorkerIdentity


def unavailable() -> ContentError:
    return ContentError(
        "EVALUATION_UNAVAILABLE", "An authenticated isolated worker is unavailable."
    )


class WorkerAuthority:
    def __init__(
        self, factory: sessionmaker[Session], clock: Clock, worker_id: UUID, credential: str
    ) -> None:
        self.factory, self.clock, self.worker_id, self.credential = (
            factory,
            clock,
            worker_id,
            credential,
        )

    @classmethod
    def from_file(
        cls, factory: sessionmaker[Session], clock: Clock, path: Path
    ) -> "WorkerAuthority":
        metadata = path.lstat()
        if path.is_symlink() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise unavailable()
        payload = json.loads(path.read_text())
        return cls(factory, clock, UUID(payload["worker_id"]), payload["credential"])

    def authenticate(self) -> tuple[str, UUID]:
        with self.factory() as session:
            row = session.get(ExecutionWorkerIdentity, self.worker_id)
            digest = hashlib.sha256(self.credential.encode()).hexdigest()
            if row is None or row.revoked or not hmac.compare_digest(row.credential_hash, digest):
                raise unavailable()
            return row.runner_identity, row.evaluator_policy_version_id

    def heartbeat(self, ready: bool) -> None:
        self.authenticate()
        with self.factory.begin() as session:
            row = session.get(ExecutionWorkerIdentity, self.worker_id, with_for_update=True)
            assert row is not None
            if row.revoked:
                raise unavailable()
            row.ready_until = self.clock.now() + timedelta(seconds=15) if ready else None

    def sign(self, record: dict[str, Any]) -> str:
        self.authenticate()
        return hmac.new(
            self.credential.encode(), canonical_record(record), hashlib.sha256
        ).hexdigest()

    def verify(self, record: dict[str, Any], signature: str) -> bool:
        return hmac.compare_digest(self.sign(record), signature)


def canonical_record(record: dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def provision_worker(
    factory: sessionmaker[Session],
    clock: Clock,
    credential_file: Path,
    image_hash: str,
    profile_hash: str,
) -> WorkerAuthority:
    if credential_file.exists():
        raise ValueError("Credential file already exists")
    worker_id, policy_id = uuid4(), uuid4()
    credential = secrets.token_hex(32)
    policy = EvaluationPolicy(
        protocol_version=2,
        runtime_image_hash=image_hash,
        isolation_profile_hash=profile_hash,
        maximum_dispatches=3,
        lease_seconds=30,
        deadline_seconds=300,
        backoff_seconds=5,
    )
    # File creation is exclusive and owner-only. Remove it if the DB transaction fails.
    descriptor = os.open(credential_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump({"worker_id": str(worker_id), "credential": credential}, output)
        with factory.begin() as session:
            session.add(
                EvaluationPolicyVersion(
                    id=policy_id,
                    version_code="local-v2-" + worker_id.hex,
                    configuration_json=policy.model_dump(),
                )
            )
            session.flush()
            session.add(
                ExecutionWorkerIdentity(
                    id=worker_id,
                    credential_hash=hashlib.sha256(credential.encode()).hexdigest(),
                    runner_identity="local-bwrap-v2-" + worker_id.hex,
                    evaluator_policy_version_id=policy_id,
                    revoked=False,
                )
            )
    except BaseException:
        credential_file.unlink(missing_ok=True)
        raise
    return WorkerAuthority(factory, clock, worker_id, credential)


class LocalRunnerAdmission:
    """API descriptor only. A fresh authenticated worker heartbeat gates requests."""

    def __init__(self, factory: sessionmaker[Session], clock: Clock) -> None:
        self.factory, self.clock = factory, clock
        self.identity, self.evaluator_policy_id = self.check()

    def check(self) -> tuple[str, UUID]:
        with self.factory() as session:
            row = session.scalar(
                select(ExecutionWorkerIdentity)
                .where(
                    ExecutionWorkerIdentity.revoked.is_(False),
                    ExecutionWorkerIdentity.ready_until > self.clock.now(),
                )
                .order_by(ExecutionWorkerIdentity.runner_identity)
                .limit(1)
            )
            if row is None:
                raise unavailable()
            return row.runner_identity, row.evaluator_policy_version_id

    def dispatch(self, request: RunnerRequest) -> RunnerResult:
        raise RuntimeError("API admission descriptors cannot execute jobs")
