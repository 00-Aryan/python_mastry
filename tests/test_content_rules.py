import copy

import pytest
from pydantic import ValidationError

from mastery_backend.api.schemas.questions import PatchDraft
from mastery_backend.domain.content import (
    ContentError,
    DraftContent,
    content_digest,
    content_snapshot,
    validate_publication,
)


def test_complete_content_and_immutable_snapshot(complete_draft: dict[str, object]) -> None:
    content = DraftContent.model_validate(complete_draft)
    validate_publication(content)
    snapshot = content_snapshot(content)
    assert isinstance(snapshot, bytes)
    assert len(content_digest(content)) == 64
    assert b"PRIVATE_SOLUTION" in snapshot


@pytest.mark.parametrize(
    "changes",
    [
        {"supported_modes": ["practice", "practice"]},
        {"suggested_budget_seconds": 0},
        {"difficulty": "impossible"},
        {"status": "published"},
        {"title": ""},
        {
            "test_cases": [
                {"position": 1, "visibility": "secret", "input": [], "expected_output": None}
            ]
        },
        {"pattern_ids": ["not-a-uuid"]},
        {
            "examples": [
                {
                    "position": 1,
                    "input": [float("nan")],
                    "expected_output": None,
                    "explanation": "x",
                }
            ]
        },
    ],
)
def test_invalid_draft_inputs(
    complete_draft: dict[str, object], changes: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        DraftContent.model_validate({**complete_draft, **changes})


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"solution": None}, "PUBLICATION_INCOMPLETE"),
        ({"skill_mappings": []}, "PUBLICATION_INCOMPLETE"),
        ({"supported_modes": ["practice"]}, "PUBLICATION_INCOMPLETE"),
        (
            {
                "assistance_steps": [
                    {
                        "position": 2,
                        "kind": "full_solution",
                        "content": "help",
                        "next_budget_seconds": 1,
                    }
                ]
            },
            "INVALID_POSITIONS",
        ),
        (
            {
                "assistance_steps": [
                    {
                        "position": 1,
                        "kind": "directional",
                        "content": "help",
                        "next_budget_seconds": 1,
                    }
                ]
            },
            "INVALID_ASSISTANCE",
        ),
        (
            {
                "test_cases": [
                    {"position": 1, "visibility": "public", "input": ["x"], "expected_output": "x"}
                ]
            },
            "PRIVATE_TEST_REQUIRED",
        ),
        (
            {
                "test_cases": [
                    {"position": 1, "visibility": "private", "input": [], "expected_output": "x"}
                ]
            },
            "INVALID_TEST_INPUT",
        ),
        (
            {
                "examples": [
                    {"position": 1, "input": [], "expected_output": "x", "explanation": "x"}
                ]
            },
            "INVALID_EXAMPLE_INPUT",
        ),
    ],
)
def test_publication_rules(
    complete_draft: dict[str, object], changes: dict[str, object], code: str
) -> None:
    content = DraftContent.model_validate({**copy.deepcopy(complete_draft), **changes})
    with pytest.raises(ContentError) as caught:
        validate_publication(content)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "patch",
    [
        {"expected_revision": 1},
        {"expected_revision": 1, "title": None},
        {"expected_revision": 1, "status": "published"},
        {"expected_revision": 0, "title": "x"},
    ],
)
def test_invalid_patch_semantics(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PatchDraft.model_validate(patch)
