"""Trusted grading outside isolation, authenticated immutable run provenance."""

import hashlib
from typing import Any

from mastery_backend.application.worker_authority import WorkerAuthority
from mastery_backend.domain.evaluations import RunnerCorrelation, RunnerRequest, RunnerResult
from mastery_backend.infrastructure.database.worker_models import EvaluationRunProvenance
from mastery_backend.infrastructure.runner.local_runner import grade_request
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox


class LocalIsolatedRunner:
    def __init__(self, sandbox: LocalSandbox, authority: WorkerAuthority) -> None:
        if not sandbox.checked:
            raise RuntimeError("Mandatory startup controls have not passed")
        self.sandbox, self.authority = sandbox, authority
        self.identity, self.evaluator_policy_id = authority.authenticate()
        from mastery_backend.application.evaluation_service import evaluation_policy

        with authority.factory() as session:
            policy = evaluation_policy(session, self.evaluator_policy_id)
        if (
            policy.protocol_version != 2
            or policy.runtime_image_hash != sandbox.image_hash
            or policy.isolation_profile_hash != sandbox.profile_hash
        ):
            raise RuntimeError("Worker runtime differs from its immutable policy")

    def authenticate(self) -> None:
        if self.authority.authenticate() != (self.identity, self.evaluator_policy_id):
            raise RuntimeError("Worker identity changed")

    def dispatch(self, request: RunnerRequest) -> RunnerResult:
        self.authenticate()
        if (
            request.protocol_version != 2
            or request.runner_identity != self.identity
            or request.evaluator_policy_version_id != self.evaluator_policy_id
            or hashlib.sha256(request.source_code.encode()).hexdigest() != request.source_hash
        ):
            raise RuntimeError("Runner request does not match authenticated pins")
        with self.authority.factory() as session:
            previous = session.get(EvaluationRunProvenance, (request.job_id, request.generation))
            if previous is not None:
                result = RunnerResult.model_validate(
                    {key: previous.record_json[key] for key in RunnerResult.model_fields}
                )
                if result.model_dump(
                    include=set(RunnerCorrelation.model_fields)
                ) != request.model_dump(
                    include=set(RunnerCorrelation.model_fields)
                ) or not self.authority.verify(previous.record_json, previous.signature):
                    raise RuntimeError("Conflicting dispatch provenance")
                return result
        try:
            outcome = grade_request(self.sandbox, request, self.authority.clock.now)
        except Exception:
            from mastery_backend.infrastructure.observability.logging import logger

            logger.exception(
                "isolated_runner_infrastructure", extra={"job_id": str(request.job_id)}
            )
            outcome = "infrastructure_error"
        correlation = request.model_dump(include=set(RunnerCorrelation.model_fields))
        result = RunnerResult(**correlation, outcome=outcome)
        record: dict[str, Any] = {
            **result.model_dump(mode="json"),
            "worker_id": str(self.authority.worker_id),
            "runtime_image_hash": self.sandbox.image_hash,
            "isolation_profile_hash": self.sandbox.profile_hash,
            "finished_at": self.authority.clock.now().isoformat(),
        }
        signature = self.authority.sign(record)
        with self.authority.factory.begin() as session:
            session.add(
                EvaluationRunProvenance(
                    job_id=request.job_id,
                    generation=request.generation,
                    worker_id=self.authority.worker_id,
                    record_json=record,
                    signature=signature,
                )
            )
        return result

    def verify_result(self, result: RunnerResult) -> bool:
        self.authenticate()
        with self.authority.factory() as session:
            row = session.get(EvaluationRunProvenance, (result.job_id, result.generation))
            if row is None or row.worker_id != self.authority.worker_id:
                return False
            expected = result.model_dump(mode="json")
            return all(
                row.record_json.get(key) == value for key, value in expected.items()
            ) and self.authority.verify(row.record_json, row.signature)
