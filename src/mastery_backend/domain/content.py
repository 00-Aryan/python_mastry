"""Validated authoring values and pure publication rules; no database or HTTP."""

import hashlib
import json
from collections.abc import Hashable, Sequence
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

NonEmptyText = Annotated[str, Field(min_length=1, max_length=65536)]
Code = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_-]{1,63}$")]
Mode = Literal["practice", "assessment", "transfer", "delayed_review"]
Difficulty = Literal["easy", "medium", "hard"]
AssistanceKind = Literal["directional", "pattern", "pseudocode", "partial_code", "full_solution"]


class ContentValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TypeSpecification(ContentValue):
    type: Literal["integer", "number", "string", "boolean", "array", "object", "null"]


class ArgumentSpecification(TypeSpecification):
    name: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=64)]


class FunctionContract(ContentValue):
    function_name: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=64)]
    arguments: list[ArgumentSpecification] = Field(max_length=32)
    output: TypeSpecification
    constraints: list[NonEmptyText] = Field(default_factory=list, max_length=100)
    invalid_input_policy: Literal["not_tested", "raise_value_error"]

    @model_validator(mode="after")
    def unique_arguments(self) -> "FunctionContract":
        names = [argument.name for argument in self.arguments]
        if len(names) != len(set(names)):
            raise ValueError("Argument names must be unique")
        return self


class SkillMapping(ContentValue):
    skill_id: UUID
    attribution_role: Literal["primary", "secondary"]
    rubric: dict[str, JsonValue] = Field(default_factory=dict)


class Example(ContentValue):
    position: int = Field(ge=1)
    input: list[JsonValue]
    expected_output: JsonValue
    explanation: NonEmptyText


class TestCase(ContentValue):
    position: int = Field(ge=1)
    visibility: Literal["public", "private"]
    input: list[JsonValue]
    expected_output: JsonValue
    assertion_rule: Literal["equals"] = "equals"
    critical: bool = False


class AssistanceStep(ContentValue):
    position: int = Field(ge=1)
    kind: AssistanceKind
    content: NonEmptyText
    next_budget_seconds: int = Field(gt=0, le=86400)


class Solution(ContentValue):
    reference_code: NonEmptyText
    explanation: NonEmptyText
    expected_complexity: NonEmptyText


class IncorrectSolution(ContentValue):
    position: int = Field(ge=1)
    label: Code
    source_code: NonEmptyText


class RevisionLink(ContentValue):
    target_version_id: UUID
    link_type: Literal["variation", "transfer", "review"]


class DraftContent(ContentValue):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    statement: NonEmptyText
    track: Annotated[str, Field(min_length=1, max_length=64)] = "python"
    difficulty: Difficulty = "easy"
    assessment_role: Mode = "practice"
    supported_modes: list[Mode] = Field(default_factory=list, max_length=4)
    suggested_budget_seconds: int = Field(default=600, gt=0, le=86400)
    contract: FunctionContract | None = None
    skill_mappings: list[SkillMapping] = Field(default_factory=list, max_length=100)
    pattern_ids: list[UUID] = Field(default_factory=list, max_length=100)
    examples: list[Example] = Field(default_factory=list, max_length=100)
    test_cases: list[TestCase] = Field(default_factory=list, max_length=500)
    assistance_steps: list[AssistanceStep] = Field(default_factory=list, max_length=20)
    solution: Solution | None = None
    incorrect_solutions: list[IncorrectSolution] = Field(default_factory=list, max_length=8)
    revision_links: list[RevisionLink] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_collections(self) -> "DraftContent":
        unique_groups: list[Sequence[Hashable]] = [
            self.supported_modes,
            self.pattern_ids,
            [mapping.skill_id for mapping in self.skill_mappings],
            [example.position for example in self.examples],
            [candidate.position for candidate in self.incorrect_solutions],
            [candidate.label for candidate in self.incorrect_solutions],
            [test.position for test in self.test_cases],
            [step.position for step in self.assistance_steps],
            [(link.target_version_id, link.link_type) for link in self.revision_links],
        ]
        if any(len(group) != len(set(group)) for group in unique_groups):
            raise ValueError("Duplicate relationship or position")
        if sum(mapping.attribution_role == "primary" for mapping in self.skill_mappings) > 1:
            raise ValueError("Only one primary skill is allowed")
        try:
            json.dumps(self.model_dump(mode="json"), allow_nan=False)
        except ValueError:
            raise ValueError("Content JSON must contain finite numbers") from None
        return self


class ContentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def content_snapshot(content: DraftContent) -> bytes:
    encoded = json.dumps(
        content.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return encoded.encode()


def content_digest(content: DraftContent) -> str:
    return hashlib.sha256(content_snapshot(content)).hexdigest()


def validate_publication(content: DraftContent) -> None:
    """Check completeness before requesting trusted executable verification."""
    if (
        not content.title.strip()
        or not content.statement.strip()
        or content.contract is None
        or content.solution is None
        or not content.examples
        or not content.test_cases
        or not content.assistance_steps
        or not content.supported_modes
        or content.assessment_role not in content.supported_modes
        or sum(mapping.attribution_role == "primary" for mapping in content.skill_mappings) != 1
    ):
        raise ContentError("PUBLICATION_INCOMPLETE", "The draft is incomplete for publication.")
    if any(
        not value.strip()
        for value in (
            content.solution.reference_code,
            content.solution.explanation,
            content.solution.expected_complexity,
            content.track,
            *(step.content for step in content.assistance_steps),
            *(example.explanation for example in content.examples),
        )
    ):
        raise ContentError("PUBLICATION_INCOMPLETE", "Publication assets cannot be blank.")
    for values in (content.examples, content.test_cases, content.assistance_steps):
        if sorted(value.position for value in values) != list(range(1, len(values) + 1)):
            raise ContentError("INVALID_POSITIONS", "Positions must be contiguous starting at one.")
    steps = sorted(content.assistance_steps, key=lambda step: step.position)
    kinds = ["directional", "pattern", "pseudocode", "partial_code", "full_solution"]
    ranks = [kinds.index(step.kind) for step in steps]
    if ranks != sorted(set(ranks)) or steps[-1].kind != "full_solution":
        raise ContentError("INVALID_ASSISTANCE", "Assistance must progress to a full solution.")
    if not any(test.visibility == "private" for test in content.test_cases):
        raise ContentError("PRIVATE_TEST_REQUIRED", "Publication requires private tests.")
    if any(len(case.input) != len(content.contract.arguments) for case in content.test_cases):
        raise ContentError("INVALID_TEST_INPUT", "Test argument counts must match the contract.")
    if any(len(example.input) != len(content.contract.arguments) for example in content.examples):
        raise ContentError("INVALID_EXAMPLE_INPUT", "Example arguments must match the contract.")
