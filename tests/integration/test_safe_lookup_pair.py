"""S017 authored inputs through real quality publication and owned isolated evaluation."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from test_first_question import ADMIN, LEARNER, OTHER, QuestionProcesses, command, read, replay

from mastery_backend.application.clock import SystemClock
from mastery_backend.application.content_seed_service import (
    seed_development_identity,
    seed_reference_catalog,
)
from mastery_backend.application.content_service import ContentService
from mastery_backend.application.identity_service import read_development_principal
from mastery_backend.application.publication_artifact_service import PublicationArtifactService
from mastery_backend.application.publication_verification import UnavailableReferenceVerifier
from mastery_backend.application.worker_authority import WorkerAuthority
from mastery_backend.domain.content import DraftContent, content_snapshot, validate_publication
from mastery_backend.domain.content_seed import ReferenceCatalogSeed
from mastery_backend.domain.question_quality import validate_quality_inputs
from mastery_backend.infrastructure.database.content_models import Question, QuestionVersion
from mastery_backend.infrastructure.database.evaluation_models import EvaluationJob
from mastery_backend.infrastructure.database.publication_models import (
    PublicationVerificationArtifact,
)
from mastery_backend.infrastructure.database.worker_models import EvaluationRunProvenance
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox

DIRECTORY = Path(__file__).resolve().parents[2] / "content/dictionaries"
FILES = {"DICT-P01": "dict_p01.private.json", "DICT-A01": "dict_a01.private.json"}
BASE_REFERENCES = DIRECTORY / "s015_references.json"
PAIR_REFERENCES = DIRECTORY / "s017_references.json"


def payload(code):
    return json.loads((DIRECTORY / FILES[code]).read_text())


@pytest.mark.parametrize("code,role", [("DICT-P01", "practice"), ("DICT-A01", "assessment")])
def test_lookup_authoring_contract_and_role(code, role):
    body = payload(code)
    content = DraftContent.model_validate(body["draft"])
    validate_publication(content)
    validate_quality_inputs(content)
    assert body["code"] == code
    assert content.assessment_role == role and content.supported_modes == [role]
    assert len(content.skill_mappings) == 1
    assert str(content.skill_mappings[0].skill_id) == "15000000-0000-0000-0000-000000000011"
    assert content.skill_mappings[0].attribution_role == "primary"
    assert [step.kind for step in content.assistance_steps] == [
        "directional",
        "pattern",
        "pseudocode",
        "partial_code",
        "full_solution",
    ]
    assert all(step.next_budget_seconds == 60 for step in content.assistance_steps)
    assert content.contract.invalid_input_policy == "not_tested"


def test_lookup_family_audit_has_dependent_key_contrasts_and_identity_continuity():
    practice, assessment = payload("DICT-P01"), payload("DICT-A01")
    previous = json.loads((DIRECTORY / "s015_lookup.private.json").read_text())
    family = ReferenceCatalogSeed.model_validate_json(PAIR_REFERENCES.read_bytes())
    assert practice["family_id"] == previous["family_id"] != assessment["family_id"]
    assert any(str(item.id) == assessment["family_id"] for item in family.question_families)
    # Retain the rejected presence proposal's identity; do not repurpose historical facts.
    assert assessment["family_id"] == "17000000-0000-0000-0000-000000000032"
    assert any(
        str(item.id) == "17000000-0000-0000-0000-000000000031" for item in family.question_families
    )
    assert not family.skills and not family.curricula  # D1 is reused, not duplicated.
    cases = assessment["draft"]["test_cases"]
    # A mapped value becomes the second key; the original key must not short-circuit it.
    contrasts = [
        ([{"short": "Ada"}, {"short": 99, "Ada": 8}, "short", -1], 8),
        ([{}, {"short": 99}, "short", -1], -1),
        ([{"short": "Ada"}, {"short": 99}, "short", -1], -1),
        ([{"short": ""}, {"": 0, "short": 99}, "short", 7], 0),
        ([{"start": "middle", "middle": "end"}, {"middle": 4, "end": 9}, "start", -1], 4),
        ([{"same": "same"}, {"same": 5}, "same", -3], 5),
    ]
    for arguments, result in contrasts:
        case = next(case for case in cases if case["input"] == arguments)
        assert case["visibility"] == "private" and case["expected_output"] == result
    assert assessment["draft"]["contract"]["function_name"] == "lookup_alias_score"
    assert assessment["draft"]["contract"]["output"]["type"] == "integer"
    for case in cases:
        assert type(case["expected_output"]) is int


@pytest.fixture
def lookup_storage(storage_factory):
    seed_development_identity(storage_factory, ADMIN, "S017 administrator", {"content_admin"})
    for path in [BASE_REFERENCES, PAIR_REFERENCES]:
        seed_reference_catalog(
            storage_factory, ADMIN, ReferenceCatalogSeed.model_validate_json(path.read_bytes())
        )
    return storage_factory


def assert_private_absent(value, contents, authorized_step=None, authorized_solution=None):
    encoded = json.dumps(value, ensure_ascii=False)
    for key in ["incorrect_solutions", "test_cases", "rubric", "snapshot_bytes", "lease_token"]:
        assert f'"{key}"' not in encoded
    if authorized_solution is None:
        assert '"reference_code"' not in encoded
    for content in contents:
        for candidate in content.incorrect_solutions:
            assert candidate.label not in encoded
            assert json.dumps(candidate.source_code, ensure_ascii=False)[1:-1] not in encoded
        if content.solution.reference_code != authorized_solution:
            assert (
                json.dumps(content.solution.reference_code, ensure_ascii=False)[1:-1] not in encoded
            )
        for step in content.assistance_steps:
            if step.content != authorized_step:
                assert json.dumps(step.content, ensure_ascii=False)[1:-1] not in encoded
        for case in content.test_cases:
            if case.visibility == "private":
                assert json.dumps(case.input, ensure_ascii=False) not in encoded


@pytest.mark.parametrize("code", FILES)
@pytest.mark.parametrize(
    "damage,reason", [("reference", "REFERENCE_FAILED"), ("suite", "WEAK_SUITE")]
)
def test_lookup_rejects_broken_reference_and_weak_tests(
    lookup_storage, isolated_runtime, tmp_path, code, damage, reason
):
    body = payload(code)
    draft = DraftContent.model_validate(body["draft"])
    if damage == "reference":
        name = draft.contract.function_name
        arguments = ", ".join(argument.name for argument in draft.contract.arguments)
        draft = draft.model_copy(
            update={
                "solution": draft.solution.model_copy(
                    update={"reference_code": f"def {name}({arguments}): return None"}
                )
            }
        )
    else:
        example = draft.examples[0]
        draft = draft.model_copy(
            update={
                "test_cases": [
                    case.model_copy(
                        update={"input": example.input, "expected_output": example.expected_output}
                    )
                    if case.visibility == "private"
                    else case
                    for case in draft.test_cases
                ]
            }
        )
    principal = read_development_principal(lookup_storage, ADMIN)
    created = ContentService(lookup_storage, UnavailableReferenceVerifier()).create_question(
        principal, "create", code, UUID(body["family_id"]), draft
    )
    version_id = UUID(created.body["id"])
    report = PublicationArtifactService(
        lookup_storage, SystemClock(), LocalSandbox(isolated_runtime)
    ).verify(principal, version_id, 1)
    assert report.quality.reason_code == reason and report.result.outcome == "incorrect"
    processes = QuestionProcesses(lookup_storage, tmp_path)
    with processes.api(ADMIN, str(report.evaluator_policy_version_id)) as admin:
        response = command(
            admin,
            f"admin/question-versions/{version_id}/publish",
            {"expected_revision": 1},
            "reject",
            409,
        )
        assert response.json()["error"]["code"] == "VERIFICATION_FAILED"
        assert read(admin, f"admin/question-versions/{version_id}")["status"] == "draft"
        assert read(admin, "questions")["items"] == []
        assert_private_absent(response.json(), [draft])


def test_real_lookup_pair_publication_privacy_family_history_and_results(
    storage_factory, isolated_runtime, tmp_path, record_property
):
    processes = QuestionProcesses(storage_factory, tmp_path)
    for identifier, role in [(ADMIN, "content_admin"), (LEARNER, "learner"), (OTHER, "learner")]:
        processes.command(
            "content",
            [
                "seed-identity",
                "--user-id",
                identifier,
                "--display-name",
                "S017 local identity",
                "--role",
                role,
            ],
        )
    for path in [BASE_REFERENCES, PAIR_REFERENCES]:
        processes.command("content", ["seed-references", path])
    drafts, contents, reports = {}, {}, {}
    with processes.api(ADMIN) as admin:
        for code in FILES:
            drafts[code] = command(admin, "admin/questions", payload(code), code, 201).json()
            contents[code] = DraftContent.model_validate(
                {field: drafts[code][field] for field in DraftContent.model_fields}
            )
    for code, draft in drafts.items():
        report = json.loads(
            processes.command(
                "content",
                [
                    "verify-reference",
                    "--version-id",
                    draft["id"],
                    "--expected-revision",
                    "1",
                    "--runtime",
                    isolated_runtime,
                ],
            )
        )
        assert report["verifier_version"] == "quality-v2"
        assert (
            report["result"]["outcome"] == "passed" and report["quality"]["reason_code"] == "PASSED"
        )
        assert (
            report["quality"]["total_candidates"]
            == report["quality"]["killed_candidates"]
            == len(contents[code].incorrect_solutions)
        )
        reports[code] = report
    with processes.api(ADMIN) as admin:
        for code, draft in drafts.items():
            denied = command(
                admin,
                f"admin/question-versions/{draft['id']}/publish",
                {"expected_revision": 1},
                code,
                503,
            )
            assert denied.json()["error"]["code"] == "VERIFICATION_UNAVAILABLE"
            assert_private_absent(denied.json(), list(contents.values()))
    for code, draft in drafts.items():
        # Explicit test-local approval of the real report's immutable policy, never .env.
        with processes.api(ADMIN, reports[code]["evaluator_policy_version_id"]) as admin:
            path, body = f"admin/question-versions/{draft['id']}/publish", {"expected_revision": 1}
            published = command(admin, path, body, code).json()
            replay(admin, path, body, code, published)
            assert published["status"] == "published"
    credential = tmp_path / "worker.json"
    worker_args = ["--runtime", isolated_runtime, "--credential", credential]
    processes.command("worker", ["provision", *worker_args])
    authority = WorkerAuthority.from_file(storage_factory, SystemClock(), credential)
    outcomes, receipts, jobs, attempts = {}, {}, {}, {}
    with processes.api(LEARNER) as learner:
        catalog = read(learner, "questions")
        assert {item["code"] for item in catalog["items"]} == set(FILES)
        assert_private_absent(catalog, list(contents.values()))
        denied = command(learner, "admin/questions", payload("DICT-P01"), "denied-write", 403)
        assert_private_absent(denied.json(), list(contents.values()))
        for code, draft in drafts.items():
            for path in [f"questions/{draft['question_id']}", f"question-versions/{draft['id']}"]:
                assert_private_absent(read(learner, path), list(contents.values()))
            role = contents[code].assessment_role
            start_body = {
                "question_version_id": draft["id"],
                "mode": role,
                "independent_budget_seconds": 600,
            }
            denied = command(
                learner,
                "attempts",
                {**start_body, "mode": "assessment" if role == "practice" else "practice"},
                code + "-wrong-mode",
                422,
            )
            assert denied.json()["error"]["code"] == "INVALID_MODE"
            started = command(learner, "attempts", start_body, code, 201).json()
            assert started["family_previously_attempted"] is False
            replay(learner, "attempts", start_body, code, started, 201)
            attempts[code] = started
            attempt_path = f"attempts/{started['id']}"
            assert_private_absent(
                read(learner, attempt_path + "/question"), list(contents.values())
            )
            wrong = contents[code].incorrect_solutions[0].source_code
            sources = [(wrong, "incorrect"), (contents[code].solution.reference_code, "passed")]
            if code == "DICT-A01":
                sources.insert(
                    1,
                    (
                        "def lookup_alias_score(aliases, scores, alias, fallback):\n"
                        "    return scores.get(alias, fallback)\n",
                        "incorrect",
                    ),
                )
            for index, (source, expected) in enumerate(sources):
                key = f"{code}-{index}"
                current = read(learner, attempt_path)
                submission_body = {
                    "expected_revision": current["revision"],
                    "purpose": "assessment",
                    "source_code": source,
                }
                receipt = command(
                    learner, attempt_path + "/submissions", submission_body, key, 201
                ).json()
                assert receipt["status"] == "received" and receipt["evaluation"] == "not_requested"
                replay(learner, attempt_path + "/submissions", submission_body, key, receipt, 201)
                authority.heartbeat(True)
                path = f"submissions/{receipt['id']}/evaluations"
                body = {"expected_revision": receipt["attempt_revision"]}
                pending = command(learner, path, body, key, 202).json()
                assert pending["status"] == "pending" and pending["category"] is None
                processes.command("worker", ["once", *worker_args])
                result = read(learner, f"evaluations/{pending['id']}")
                assert result["category"] == expected
                assert result["status"] == ("passed" if expected == "passed" else "failed")
                assert result["question_version_id"] == draft["id"]
                assert result["policy_version_id"] == started["policy_version_id"]
                assert_private_absent(result, list(contents.values()))
                replay(learner, path, body, key, pending, 202)  # Readiness withdrawn by once.
                assert read(learner, f"submissions/{receipt['id']}") == receipt
                outcomes[key], receipts[key], jobs[key] = (path, body, pending), receipt, result
            current = read(learner, attempt_path)
            assert current["lifecycle_state"] == "active"  # No scoring/completion inferred.
            hint_body = {"expected_revision": current["revision"], "trigger": "learner_request"}
            hint = command(learner, attempt_path + "/assistance/next", hint_body, code).json()
            assert hint["grant"]["kind"] == "directional" and hint["grant"]["solution"] is None
            assert_private_absent(
                hint,
                list(contents.values()),
                authorized_step=contents[code].assistance_steps[0].content,
            )
            replay(learner, attempt_path + "/assistance/next", hint_body, code, hint)
            denied = command(
                learner,
                attempt_path + "/assistance/next",
                {"expected_revision": hint["attempt"]["revision"], "trigger": "learner_request"},
                code + "-too-soon",
                409,
            )
            assert denied.json()["error"]["code"] == "ASSISTANCE_NOT_READY"
            escape = command(
                learner,
                attempt_path + "/assistance/solution",
                {"expected_revision": hint["attempt"]["revision"], "confirmation": True},
                code,
            ).json()
            assert (
                escape["grant"]["solution"]["reference_code"]
                == contents[code].solution.reference_code
            )
            assert_private_absent(
                escape,
                list(contents.values()),
                authorized_step=contents[code].assistance_steps[-1].content,
                authorized_solution=contents[code].solution.reference_code,
            )
            for receipt in receipts.values():
                assert read(learner, f"submissions/{receipt['id']}") == receipt
            repeat = command(learner, "attempts", start_body, code + "-repeat", 201).json()
            assert repeat["family_previously_attempted"] is True
            assert_private_absent(
                read(learner, attempt_path + "/evaluations"), list(contents.values())
            )
    with processes.api(LEARNER) as learner:
        for key, (path, body, pending) in outcomes.items():
            replay(learner, path, body, key, pending, 202)
            assert read(learner, f"evaluations/{pending['id']}") == jobs[key]
    with processes.api(OTHER) as other:
        for code, attempt in attempts.items():
            denied = other.get(f"/api/v1/attempts/{attempt['id']}/assistance")
            assert denied.status_code == 404
            assert_private_absent(denied.json(), list(contents.values()))
            denied = command(
                other,
                f"attempts/{attempt['id']}/assistance/solution",
                {"expected_revision": attempt["revision"], "confirmation": True},
                code,
                404,
            )
            assert_private_absent(denied.json(), list(contents.values()))
    with storage_factory() as session:
        assert session.scalar(select(func.count()).select_from(Question)) == 2
        assert session.scalar(select(func.count()).select_from(EvaluationJob)) == 5
        for code, draft in drafts.items():
            artifact = session.get(PublicationVerificationArtifact, UUID(reports[code]["id"]))
            version = session.get(QuestionVersion, UUID(draft["id"]))
            assert artifact.snapshot_bytes == content_snapshot(contents[code])
            assert version.verification_json["verification_id"] == str(artifact.id)
            assert version.verification_json["content_hash"] == artifact.content_hash
            record_property(code + "_version_id", draft["id"])
            record_property(code + "_artifact_id", str(artifact.id))
        for key, result in jobs.items():
            provenance = session.get(EvaluationRunProvenance, (UUID(result["id"]), 1))
            assert authority.verify(provenance.record_json, provenance.signature)
            assert provenance.record_json["source_hash"] == receipts[key]["code_hash"]
            assert provenance.record_json["outcome"] == result["category"]
