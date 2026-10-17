"""One authored question, real publication and loopback learner/worker lifecycle."""

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

import httpx2 as httpx
import pytest
from sqlalchemy import func, select, text

from mastery_backend.application.clock import SystemClock
from mastery_backend.application.identity_service import read_development_principal
from mastery_backend.application.publication_artifact_service import PublicationArtifactService
from mastery_backend.domain.content import DraftContent, content_snapshot, validate_publication
from mastery_backend.domain.content_seed import ReferenceCatalogSeed
from mastery_backend.domain.question_quality import validate_quality_inputs
from mastery_backend.infrastructure.database.content_models import QuestionVersion
from mastery_backend.infrastructure.database.evaluation_models import EvaluationJob
from mastery_backend.infrastructure.database.publication_models import (
    PublicationVerificationArtifact,
)
from mastery_backend.infrastructure.database.submission_models import Submission
from mastery_backend.infrastructure.database.worker_models import (
    EvaluationRunProvenance,
    ExecutionWorkerIdentity,
)
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "content/dictionaries/s015_lookup.private.json"
REFERENCES = ROOT / "content/dictionaries/s015_references.json"
ADMIN = UUID("15000000-0000-0000-0000-000000000001")
LEARNER = UUID("15000000-0000-0000-0000-000000000002")
OTHER = UUID("15000000-0000-0000-0000-000000000003")


def test_first_question_authoring_contract():
    content = DraftContent.model_validate(json.loads(CONTENT.read_text())["draft"])
    references = ReferenceCatalogSeed.model_validate_json(REFERENCES.read_bytes())
    validate_publication(content)
    validate_quality_inputs(content)
    assert len(references.skills) == 1
    assert content.skill_mappings[0].skill_id == references.skills[0].id
    assert [step.kind for step in content.assistance_steps] == [
        "directional",
        "pattern",
        "pseudocode",
        "partial_code",
        "full_solution",
    ]


class QuestionProcesses:
    """Bounded test-local processes; all jobs/identities live in the fixture schema."""

    def __init__(self, factory, directory):
        with factory() as session:
            self.configuration = {
                "database_url": session.get_bind().url.render_as_string(hide_password=False),
                "schema": session.scalar(text("SELECT current_schema()")),
            }
        self.directory = directory
        self.sequence = 0

    def launch(self, component, user=ADMIN, **options):
        self.sequence += 1
        path = self.directory / f"process-{self.sequence}.json"
        payload = {**self.configuration, "component": component, "user_id": str(user), **options}
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(payload, output)
        log = self.directory / f"process-{self.sequence}.log"
        with log.open("wb") as output:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("first_question_process.py")),
                    str(path),
                ],
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        return process, log

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        process.wait(timeout=5)

    def command(self, component, arguments, timeout=45):
        process, log = self.launch(component, arguments=[str(arg) for arg in arguments])
        try:
            assert process.wait(timeout=timeout) == 0, f"{component} failed; inspect {log.name}"
            return log.read_text()
        finally:
            self.stop(process)

    @contextmanager
    def api(self, user, approved_policy_id=None):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        process, log = self.launch("api", user, port=port, approved_policy_id=approved_policy_id)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    assert process.poll() is None, f"API startup failed; inspect {log.name}"
                    try:
                        if client.get("/health/live").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                else:
                    pytest.fail("Loopback API did not become live")
                yield client
        finally:
            self.stop(process)


def command(client, path, body, key, status=200):
    response = client.post("/api/v1/" + path, json=body, headers={"Idempotency-Key": key})
    assert response.status_code == status, response.text
    return response


def read(client, path):
    response = client.get("/api/v1/" + path)
    assert response.status_code == 200, response.text
    return response.json()


def replay(client, path, body, key, original, status=200):
    response = command(client, path, body, key, status)
    assert response.headers["Idempotency-Replayed"] == "true"
    assert response.json() == original


def assert_public(payload, content, granted=False):
    encoded = json.dumps(payload, ensure_ascii=False)
    for forbidden in [
        "incorrect_solutions",
        "test_cases",
        "expected_json",
        "lease_token",
        "snapshot_bytes",
        "quality-v2",
        "zero-score",
        "missing-score",
    ]:
        assert forbidden not in encoded
    for candidate in content.incorrect_solutions:
        assert candidate.label not in encoded
        assert json.dumps(candidate.source_code, ensure_ascii=False)[1:-1] not in encoded
    assert "reference_code" not in encoded
    if not granted:
        for step in content.assistance_steps:
            assert step.content not in encoded


def setup_question(processes):
    for identifier, roles in [
        (ADMIN, ["content_admin"]),
        (LEARNER, ["learner"]),
        (OTHER, ["learner"]),
    ]:
        arguments = [
            "seed-identity",
            "--user-id",
            identifier,
            "--display-name",
            "S015 local identity",
        ]
        for role in roles:
            arguments.extend(["--role", role])
        processes.command("content", arguments)
    processes.command("content", ["seed-references", REFERENCES])
    payload = json.loads(CONTENT.read_text())
    with processes.api(ADMIN) as admin:
        draft = command(admin, "admin/questions", payload, "s015-create", 201).json()
        denied = command(
            admin,
            f"admin/question-versions/{draft['id']}/publish",
            {"expected_revision": 1},
            "no-approval",
            503,
        )
        assert denied.json()["error"]["code"] == "VERIFICATION_UNAVAILABLE"
    # Published hashes pin the stored canonical projection (relationships are sorted).
    canonical = {name: draft[name] for name in DraftContent.model_fields}
    return draft, DraftContent.model_validate(canonical)


@pytest.mark.parametrize("variant,reason", [("broken", "REFERENCE_FAILED"), ("weak", "WEAK_SUITE")])
def test_dictionary_question_rejects_broken_reference_and_weak_suite(
    storage_factory, isolated_runtime, tmp_path, variant, reason
):
    from mastery_backend.application.content_service import ContentService
    from mastery_backend.application.publication_verification import UnavailableReferenceVerifier

    processes = QuestionProcesses(storage_factory, tmp_path)
    draft, content = setup_question(processes)
    service = ContentService(storage_factory, UnavailableReferenceVerifier())
    principal = read_development_principal(storage_factory, ADMIN)
    if variant == "broken":
        changes = {
            "solution": content.solution.model_copy(
                update={
                    "reference_code": "def lookup_score(scores, name, fallback): return fallback"
                }
            )
        }
    else:
        changes = {
            "test_cases": [
                case.model_copy(update={"input": [{"Ada": 8}, "Ada", 0], "expected_output": 8})
                if case.visibility == "private"
                else case
                for case in content.test_cases
            ]
        }
    service.patch_draft(principal, UUID(draft["id"]), 1, changes)
    report = PublicationArtifactService(
        storage_factory, SystemClock(), LocalSandbox(isolated_runtime)
    ).verify(principal, UUID(draft["id"]), 2)
    assert report.quality.reason_code == reason
    with processes.api(ADMIN, str(report.evaluator_policy_version_id)) as admin:
        denied = command(
            admin,
            f"admin/question-versions/{draft['id']}/publish",
            {"expected_revision": 2},
            "bad-quality",
            409,
        )
        assert denied.json()["error"]["code"] == "VERIFICATION_FAILED"
        assert read(admin, f"admin/question-versions/{draft['id']}")["status"] == "draft"


def test_real_dictionary_question_end_to_end(
    storage_factory, isolated_runtime, tmp_path, record_property
):
    from mastery_backend.application.worker_authority import WorkerAuthority

    processes = QuestionProcesses(storage_factory, tmp_path)
    draft, content = setup_question(processes)
    version_id = draft["id"]
    raw_report = processes.command(
        "content",
        [
            "verify-reference",
            "--version-id",
            version_id,
            "--expected-revision",
            "1",
            "--runtime",
            isolated_runtime,
        ],
    )
    report = json.loads(raw_report)
    assert report["verifier_version"] == "quality-v2"
    assert report["result"]["outcome"] == "passed"
    assert report["quality"]["total_candidates"] == report["quality"]["killed_candidates"] == 2
    approved = report[
        "evaluator_policy_version_id"
    ]  # Explicit test-local approval after inspecting report.
    with processes.api(ADMIN, approved) as admin:
        publish_body = {"expected_revision": 1}
        published = command(
            admin, f"admin/question-versions/{version_id}/publish", publish_body, "publish"
        ).json()
        replay(
            admin,
            f"admin/question-versions/{version_id}/publish",
            publish_body,
            "publish",
            published,
        )
        assert_public(read(admin, "questions"), content)
    credential = tmp_path / "worker.json"
    worker_arguments = ["--runtime", isolated_runtime, "--credential", credential]
    processes.command("worker", ["provision", *worker_arguments])
    authority = WorkerAuthority.from_file(storage_factory, SystemClock(), credential)
    attempt_path = None
    with processes.api(LEARNER) as learner:
        forbidden = command(
            learner, "admin/questions", json.loads(CONTENT.read_text()), "forbidden", 403
        )
        assert_public(forbidden.json(), content)
        start_body = {
            "question_version_id": version_id,
            "mode": "practice",
            "independent_budget_seconds": 600,
        }
        started = command(learner, "attempts", start_body, "start", 201).json()
        attempt_path = f"attempts/{started['id']}"
        replay(learner, "attempts", start_body, "start", started, 201)
        pinned = read(learner, attempt_path + "/question")
        assert pinned["id"] == version_id
        assert_public(pinned, content)
        pause_body = {"expected_revision": started["revision"]}
        paused = command(learner, attempt_path + "/pause", pause_body, "pause").json()
    # A new real API process reconstructs state from PostgreSQL; there is no browser draft feature.
    with processes.api(LEARNER) as learner:
        reloaded = read(learner, attempt_path)
        assert reloaded["timer"]["remaining_ms"] == paused["timer"]["remaining_ms"]
        assert reloaded["policy_version_id"] == started["policy_version_id"]
        replay(learner, attempt_path + "/pause", pause_body, "pause", paused)
        resumed = command(
            learner, attempt_path + "/resume", {"expected_revision": reloaded["revision"]}, "resume"
        ).json()
        assert resumed["lifecycle_state"] == "active"
        assert datetime.fromisoformat(resumed["timer"]["server_now"]) >= datetime.fromisoformat(
            paused["timer"]["server_now"]
        )
        wrong = content.incorrect_solutions[0].source_code
        receipts, jobs, requests = [], [], []
        for index, (source, purpose, outcome) in enumerate(
            [
                (wrong, "public_run", "passed"),
                (wrong, "assessment", "incorrect"),
                (
                    "def lookup_score(scores, name, fallback):\n"
                    "    if name in scores:\n        return scores[name]\n"
                    "    return fallback\n",
                    "assessment",
                    "passed",
                ),
            ]
        ):
            current = read(learner, attempt_path)
            body = {
                "expected_revision": current["revision"],
                "source_code": source,
                "purpose": purpose,
            }
            receipt = command(
                learner, attempt_path + "/submissions", body, f"submit-{index}", 201
            ).json()
            assert receipt["status"] == "received" and receipt["evaluation"] == "not_requested"
            assert receipt["question_version_id"] == version_id
            replay(learner, attempt_path + "/submissions", body, f"submit-{index}", receipt, 201)
            authority.heartbeat(True)  # Actual authenticated readiness, test-local and short-lived.
            evaluation_path = f"submissions/{receipt['id']}/evaluations"
            request = {"expected_revision": receipt["attempt_revision"]}
            pending = command(learner, evaluation_path, request, f"evaluate-{index}", 202).json()
            assert pending["status"] == "pending" and pending["category"] is None
            if purpose == "assessment":
                current = read(learner, attempt_path)
                denied = command(
                    learner,
                    attempt_path + "/assistance/next",
                    {"expected_revision": current["revision"], "trigger": "learner_request"},
                    f"pending-help-{index}",
                    409,
                )
                assert denied.json()["error"]["code"] == "EVALUATION_PENDING"
            processes.command("worker", ["once", *worker_arguments])
            result = read(learner, f"evaluations/{pending['id']}")
            assert result["category"] == outcome
            assert result["status"] == ("passed" if outcome == "passed" else "failed")
            assert [row["state"] for row in result["transitions"]] == [
                "pending",
                "running",
                result["status"],
            ]
            assert result["question_version_id"] == version_id
            assert result["policy_version_id"] == started["policy_version_id"]
            assert_public(result, content)
            replay(learner, evaluation_path, request, f"evaluate-{index}", pending, 202)
            receipts.append(receipt)
            jobs.append(result)
            requests.append((evaluation_path, request, pending))
            if index == 1:
                current = read(learner, attempt_path)
                help_body = {"expected_revision": current["revision"], "trigger": "learner_request"}
                hint = command(learner, attempt_path + "/assistance/next", help_body, "hint").json()
                assert hint["grant"]["kind"] == "directional"
                assert hint["grant"]["content"] == content.assistance_steps[0].content
                assert hint["grant"]["solution"] is None
                assert_public(hint, content, granted=True)
                replay(learner, attempt_path + "/assistance/next", help_body, "hint", hint)
                denied = command(
                    learner,
                    attempt_path + "/assistance/next",
                    {
                        "expected_revision": hint["attempt"]["revision"],
                        "trigger": "learner_request",
                    },
                    "too-soon",
                    409,
                )
                assert denied.json()["error"]["code"] == "ASSISTANCE_NOT_READY"
        assert receipts[0]["evidence"]["assistance_grant_ids"] == []
        assert receipts[1]["evidence"]["assistance_grant_ids"] == []
        assert receipts[2]["evidence"]["assistance_grant_ids"] == [hint["grant"]["id"]]
        assert (
            receipts[2]["evidence"]["attempt"]["independent_end_reason"] == "assistance_requested"
        )
        for receipt in receipts:
            assert read(learner, f"submissions/{receipt['id']}") == receipt
        final = read(learner, attempt_path)
        # Evaluation is not a scoring/completion transition.
        assert final["lifecycle_state"] == "active"
        assert final["assistance_level"] == "directional"
        assert_public(read(learner, attempt_path), content)
        assert_public(read(learner, attempt_path + "/evaluations"), content)
        assert_public(read(learner, attempt_path + "/submissions"), content)
        history = read(learner, attempt_path + "/assistance")
        assert [row["id"] for row in history["grants"]] == [hint["grant"]["id"]]
    # Lost responses recover after API and worker exit; readiness is no longer needed for replay.
    with processes.api(LEARNER) as learner:
        path, request, pending = requests[-1]
        replay(learner, path, request, "evaluate-2", pending, 202)
        assert read(learner, f"evaluations/{jobs[-1]['id']}") == jobs[-1]
        assert read(learner, attempt_path + "/assistance") == history
    with processes.api(OTHER) as other:
        for path in [
            attempt_path,
            f"submissions/{receipts[-1]['id']}",
            f"evaluations/{jobs[-1]['id']}",
        ]:
            denied = other.get("/api/v1/" + path)
            assert denied.status_code == 404
            assert_public(denied.json(), content)
    with storage_factory() as session:
        artifact = session.get(PublicationVerificationArtifact, UUID(report["id"]))
        version = session.get(QuestionVersion, UUID(version_id))
        assert version.status == "published"
        assert version.verification_json["verification_id"] == report["id"]
        assert version.verification_json["content_hash"] == report["content_hash"]
        assert artifact.snapshot_bytes == content_snapshot(content)
        assert artifact.content_hash == hashlib.sha256(content_snapshot(content)).hexdigest()
        assert session.scalar(select(func.count()).select_from(EvaluationJob)) == 3
        assert session.scalar(select(func.count()).select_from(Submission)) == 3
        for receipt, job in zip(receipts, jobs, strict=True):
            provenance = session.get(EvaluationRunProvenance, (UUID(job["id"]), 1))
            assert authority.verify(provenance.record_json, provenance.signature)
            assert provenance.record_json["source_hash"] == receipt["code_hash"]
            assert provenance.record_json["outcome"] == job["category"]
        identity = session.get(ExecutionWorkerIdentity, authority.worker_id)
        assert identity.ready_until is None  # Bounded once exits withdraw readiness.
    record_property("publication_artifact_id", report["id"])
    record_property("question_version_id", version_id)
    record_property("final_evaluation_id", jobs[-1]["id"])
    record_property("final_category", jobs[-1]["category"])
