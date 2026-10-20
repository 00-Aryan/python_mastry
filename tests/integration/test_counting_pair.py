"""S018 counting contracts and real isolated publication/learner acceptance."""

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
FILES = {"DICT-P02": "dict_p02.private.json", "DICT-A02": "dict_a02.private.json"}
REFERENCES = [DIRECTORY / "s015_references.json", DIRECTORY / "s018_references.json"]
SKILL_ID = "18000000-0000-0000-0000-000000000011"


def payload(code):
    return json.loads((DIRECTORY / FILES[code]).read_text())


@pytest.mark.parametrize("code,role", [("DICT-P02", "practice"), ("DICT-A02", "assessment")])
def test_counting_authoring_contract_and_role(code, role):
    body = payload(code)
    content = DraftContent.model_validate(body["draft"])
    validate_publication(content)
    validate_quality_inputs(content)
    assert body["code"] == code
    assert content.assessment_role == role and content.supported_modes == [role]
    assert len(content.skill_mappings) == 1
    assert str(content.skill_mappings[0].skill_id) == SKILL_ID
    assert content.skill_mappings[0].attribution_role == "primary"
    assert content.contract.arguments[0].type == "array"
    assert content.contract.output.type == "object"
    assert content.contract.invalid_input_policy == "not_tested"
    assert [step.kind for step in content.assistance_steps] == [
        "directional",
        "pattern",
        "pseudocode",
        "partial_code",
        "full_solution",
    ]
    assert all(step.next_budget_seconds == 60 for step in content.assistance_steps)
    for case in content.test_cases:
        assert all(type(value) is int and value > 0 for value in case.expected_output.values())


def test_counting_family_contrasts_require_chronological_state():
    practice, assessment = payload("DICT-P02"), payload("DICT-A02")
    references = ReferenceCatalogSeed.model_validate_json(REFERENCES[1].read_bytes())
    assert not references.curricula  # Reuse S015's curriculum, not another catalog.
    assert len(references.skills) == 1 and str(references.skills[0].id) == SKILL_ID
    assert str(references.skills[0].curriculum_id) == "15000000-0000-0000-0000-000000000010"
    assert practice["family_id"] != assessment["family_id"]
    assert {str(item.id) for item in references.question_families} == {
        practice["family_id"],
        assessment["family_id"],
    }
    cases = assessment["draft"]["test_cases"]
    contrasts = [
        ([["x", -3], ["x", 2]], {"x": 2}),
        ([["x", 2], ["x", -3]], {}),
        ([["x", 3], ["x", -5], ["x", 4]], {"x": 4}),
        ([["x", 5], ["x", -2]], {"x": 3}),
        ([["y", 5], ["x", -3], ["x", 2], ["y", -1]], {"y": 4, "x": 2}),
        ([["x", 0]], {}),
    ]
    for adjustments, expected in contrasts:
        case = next(case for case in cases if case["input"] == [adjustments])
        assert case["visibility"] == "private" and case["expected_output"] == expected
    forward = next(case for case in cases if case["input"] == [contrasts[0][0]])
    reverse = next(case for case in cases if case["input"] == [contrasts[1][0]])
    assert sorted(forward["input"][0]) == sorted(reverse["input"][0])
    assert forward["expected_output"] != reverse["expected_output"]


@pytest.fixture
def counting_storage(storage_factory):
    seed_development_identity(storage_factory, ADMIN, "S018 administrator", {"content_admin"})
    for path in REFERENCES:
        seed_reference_catalog(
            storage_factory, ADMIN, ReferenceCatalogSeed.model_validate_json(path.read_bytes())
        )
    return storage_factory


@pytest.mark.parametrize("code", FILES)
@pytest.mark.parametrize(
    "damage,reason", [("reference", "REFERENCE_FAILED"), ("suite", "WEAK_SUITE")]
)
def test_counting_rejects_broken_reference_and_weak_tests(
    counting_storage, isolated_runtime, tmp_path, code, damage, reason
):
    verify_quality_rejection(
        counting_storage, isolated_runtime, tmp_path, payload(code), damage, reason
    )


def test_real_counting_pair_publication_privacy_family_history_and_results(
    storage_factory, isolated_runtime, tmp_path, record_property
):
    verify_pair_flow(
        storage_factory,
        isolated_runtime,
        tmp_path,
        record_property,
        {code: payload(code) for code in FILES},
        REFERENCES,
        {
            "DICT-A02": [
                "def apply_count_changes(adjustments):\n"
                "    counts = {}\n"
                "    for token, change in adjustments:\n"
                "        counts[token] = counts.get(token, 0) + 1\n"
                "    return counts\n"
            ]
        },
    )
