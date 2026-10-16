"""Pure contract checks reject malformed authored assets before any code runs."""

from copy import deepcopy

import pytest
from question_quality_fixtures import INCORRECT_SOLUTIONS

from mastery_backend.domain.content import ContentError, DraftContent
from mastery_backend.domain.question_quality import (
    invalid_type_probes,
    matches_json_type,
    validate_quality_inputs,
)


def quality_content(complete_draft):
    values = deepcopy(complete_draft)
    values["incorrect_solutions"] = INCORRECT_SOLUTIONS
    values["test_cases"][0]["expected_output"] = "PRIVATE_TEST_INPUT"
    return DraftContent.model_validate(values)


@pytest.mark.parametrize(
    "value,kind,valid",
    [
        (True, "integer", False),
        (True, "number", False),
        (1, "integer", True),
        (1.5, "integer", False),
        (1.5, "number", True),
        (1, "number", True),
        ([], "array", True),
        ({}, "object", True),
        (None, "null", True),
        (0, "boolean", False),
        ("word", "string", True),
    ],
)
def test_json_types_are_explicit(value, kind, valid):
    assert matches_json_type(value, kind) is valid


@pytest.mark.parametrize(
    "mutation", ["keyword", "type", "output", "arity", "defaults", "async", "missing", "duplicate"]
)
def test_invalid_contracts_and_candidates_reject(complete_draft, mutation):
    content = quality_content(complete_draft)
    values = content.model_dump()
    if mutation == "keyword":
        values["contract"]["function_name"] = "class"
    elif mutation == "type":
        values["examples"][0]["input"] = [True]
    elif mutation == "output":
        values["test_cases"][0]["expected_output"] = 1
    elif mutation == "arity":
        values["solution"]["reference_code"] = "def echo(other): return other"
    elif mutation == "defaults":
        values["solution"]["reference_code"] = 'def echo(word="hello"): return word'
    elif mutation == "async":
        values["solution"]["reference_code"] = "async def echo(word): return word"
    elif mutation == "missing":
        values["incorrect_solutions"] = []
    else:
        values["incorrect_solutions"][1]["source_code"] = values["incorrect_solutions"][0][
            "source_code"
        ]
    with pytest.raises(ContentError):
        validate_quality_inputs(DraftContent.model_validate(values))


def test_invalid_type_probes_follow_pinned_policy(complete_draft):
    content = quality_content(complete_draft)
    assert invalid_type_probes(content) == []
    contract = content.contract.model_copy(update={"invalid_input_policy": "raise_value_error"})
    probes = invalid_type_probes(content.model_copy(update={"contract": contract}))
    assert probes and all(not matches_json_type(probe[0], "string") for probe in probes)
    validate_quality_inputs(content)


@pytest.mark.parametrize("limit", ["elapsed", "count"])
def test_quality_budget_rejects_with_bounded_evidence(complete_draft, monkeypatch, limit):
    """Deterministic test-only sandbox/clock; real per-case limits are tested separately."""
    from types import SimpleNamespace

    from mastery_backend.domain.content import IncorrectSolution, TestCase
    from mastery_backend.infrastructure.runner import reference_quality
    from mastery_backend.infrastructure.runner.local_sandbox import SandboxOutput

    content = quality_content(complete_draft)
    content = content.model_copy(
        update={
            "test_cases": [
                TestCase(
                    position=n,
                    visibility="private",
                    input=["hello" if n < 63 else "long-private-word"],
                    expected_output="hello" if n < 63 else "long-private-word",
                )
                for n in range(1, 64)
            ],
            "incorrect_solutions": [
                IncorrectSolution(
                    position=n,
                    label=f"CONSTANT_{n}",
                    source_code=f'def echo(word): return "hello" # variant {n}',
                )
                for n in range(1, 5)
            ],
        }
    )
    reference_source = content.solution.reference_code

    class TestSandbox:
        def startup_check(self):
            pass

        def execute(self, source, function, inputs):
            return SandboxOutput("returned", inputs[0] if source == reference_source else "hello")

    ticks = iter([0.0, 30.0]) if limit == "elapsed" else None
    monkeypatch.setattr(
        reference_quality,
        "time",
        SimpleNamespace(monotonic=(lambda: next(ticks)) if ticks else (lambda: 0.0)),
    )
    result, quality = reference_quality.grade_quality(TestSandbox(), content)
    assert result.outcome == "resource_limit" and quality.reason_code == "RESOURCE_LIMIT"
    assert quality.executions == (0 if limit == "elapsed" else 256)
