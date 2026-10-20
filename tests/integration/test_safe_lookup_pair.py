"""S017 authored inputs through real quality publication and owned isolated evaluation."""

import json
from pathlib import Path

import pytest
from question_pair_checks import verify_pair_flow, verify_quality_rejection
from test_first_question import ADMIN

from mastery_backend.application.content_seed_service import (
    seed_development_identity,
    seed_reference_catalog,
)
from mastery_backend.domain.content import DraftContent, validate_publication
from mastery_backend.domain.content_seed import ReferenceCatalogSeed
from mastery_backend.domain.question_quality import validate_quality_inputs

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


@pytest.mark.parametrize("code", FILES)
@pytest.mark.parametrize(
    "damage,reason", [("reference", "REFERENCE_FAILED"), ("suite", "WEAK_SUITE")]
)
def test_lookup_rejects_broken_reference_and_weak_tests(
    lookup_storage, isolated_runtime, tmp_path, code, damage, reason
):
    verify_quality_rejection(
        lookup_storage, isolated_runtime, tmp_path, payload(code), damage, reason
    )


def test_real_lookup_pair_publication_privacy_family_history_and_results(
    storage_factory, isolated_runtime, tmp_path, record_property
):
    verify_pair_flow(
        storage_factory,
        isolated_runtime,
        tmp_path,
        record_property,
        {code: payload(code) for code in FILES},
        [BASE_REFERENCES, PAIR_REFERENCES],
        {
            "DICT-A01": [
                "def lookup_alias_score(aliases, scores, alias, fallback):\n"
                "    return scores.get(alias, fallback)\n"
            ]
        },
    )
