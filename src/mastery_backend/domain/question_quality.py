"""Bounded authored-contract checks; AST inspection never executes source."""

import ast
import hashlib
import keyword
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from mastery_backend.domain.content import (
    ContentError,
    ContentValue,
    DraftContent,
    Example,
    FunctionContract,
    TestCase,
)

QualityReason = Literal[
    "PASSED",
    "INVALID_CONTRACT",
    "INVALID_CANDIDATES",
    "REFERENCE_FAILED",
    "WEAK_SUITE",
    "INFRASTRUCTURE_ERROR",
    "RESOURCE_LIMIT",
]
MAX_QUALITY_EXECUTIONS = 256


class QualityCheckResult(ContentValue):
    reason_code: QualityReason
    total_candidates: int = Field(ge=0, le=8)
    killed_candidates: int = Field(ge=0, le=8)
    executions: int = Field(ge=0, le=MAX_QUALITY_EXECUTIONS)

    @model_validator(mode="after")
    def coherent_counts(self) -> "QualityCheckResult":
        if self.killed_candidates > self.total_candidates or (
            self.reason_code == "PASSED"
            and (
                self.total_candidates < 2
                or self.killed_candidates != self.total_candidates
                or self.executions < 2 + 2 * self.total_candidates
            )
        ):
            raise ValueError("Quality counts do not match outcome")
        return self


def matches_json_type(value: object, kind: str) -> bool:
    if kind == "integer":
        return type(value) is int
    if kind == "number":
        return type(value) in {int, float}
    return (
        type(value)
        is {"string": str, "boolean": bool, "array": list, "object": dict, "null": type(None)}[kind]
    )


def validate_signature(source: str, contract: FunctionContract, reason: str) -> None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        raise ContentError(reason, "Source must define the documented Python function.") from None
    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == contract.function_name
    ]
    if len(definitions) != 1:
        raise ContentError(reason, "Source must define the documented Python function.")
    function = definitions[0]
    names = [argument.arg for argument in function.args.posonlyargs + function.args.args]
    if (
        function.decorator_list
        or function.args.vararg
        or function.args.kwarg
        or function.args.kwonlyargs
        or function.args.defaults
        or names != [argument.name for argument in contract.arguments]
    ):
        raise ContentError(reason, "Function signature must match positional contract arguments.")


def validate_quality_inputs(content: DraftContent) -> None:
    contract, solution = content.contract, content.solution
    assert contract is not None and solution is not None
    if any(
        keyword.iskeyword(name) or name.startswith("__mastery_")
        for name in [contract.function_name, *(argument.name for argument in contract.arguments)]
    ):
        raise ContentError(
            "INVALID_CONTRACT", "Contract names must be supported Python identifiers."
        )
    validate_signature(solution.reference_code, contract, "INVALID_CONTRACT")
    cases: list[Example | TestCase] = [*content.examples, *content.test_cases]
    for case in cases:
        if (
            len(case.input) != len(contract.arguments)
            or any(
                not matches_json_type(value, argument.type)
                for value, argument in zip(case.input, contract.arguments, strict=True)
            )
            or not matches_json_type(case.expected_output, contract.output.type)
        ):
            raise ContentError("INVALID_CONTRACT", "Example/test values must match contract types.")
    candidates = content.incorrect_solutions
    hashes = {
        hashlib.sha256(candidate.source_code.encode()).hexdigest() for candidate in candidates
    }
    if (
        not 2 <= len(candidates) <= 8
        or len(hashes) != len(candidates)
        or sorted(candidate.position for candidate in candidates)
        != list(range(1, len(candidates) + 1))
        or hashlib.sha256(solution.reference_code.encode()).hexdigest() in hashes
    ):
        raise ContentError(
            "INVALID_CANDIDATES", "Supply two to eight distinct representative incorrect solutions."
        )
    for candidate in candidates:
        validate_signature(candidate.source_code, contract, "INVALID_CANDIDATES")


def invalid_type_probes(content: DraftContent) -> list[list[JsonValue]]:
    assert content.contract is not None
    if content.contract.invalid_input_policy != "raise_value_error":
        return []
    replacements: list[JsonValue] = [None, True, 1, 1.5, "invalid", [], {}]
    probes: list[list[JsonValue]] = []
    for index, argument in enumerate(content.contract.arguments):
        for value in replacements:
            if not matches_json_type(value, argument.type):
                inputs = list(content.examples[0].input)
                inputs[index] = value
                probes.append(inputs)
    return probes


def value_error_probe_source(source: str, function_name: str) -> str:
    # A trusted wrapper travels as source DATA through the existing sandbox protocol.
    # Only the validated function identifier is interpolated; no shell/expression evaluation.
    return (
        source
        + f"""
\ndef __mastery_expect_value_error(*arguments):
    import builtins as __mastery_builtins
    try:
        {function_name}(*arguments)
    except __mastery_builtins.ValueError:
        return True
    except __mastery_builtins.BaseException:
        return False
    return False
"""
    )
