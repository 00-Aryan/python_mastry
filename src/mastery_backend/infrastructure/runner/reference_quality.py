"""Grade bounded reference/misconception runs outside isolation and database transactions."""

import time
from typing import cast

from mastery_backend.domain.content import ContentError, DraftContent, Example, TestCase
from mastery_backend.domain.evaluations import Outcome
from mastery_backend.domain.publication_artifacts import ReferenceCheckResult
from mastery_backend.domain.question_quality import (
    MAX_QUALITY_EXECUTIONS,
    QualityCheckResult,
    QualityReason,
    invalid_type_probes,
    matches_json_type,
    validate_quality_inputs,
    value_error_probe_source,
)
from mastery_backend.infrastructure.observability.logging import logger
from mastery_backend.infrastructure.runner.local_sandbox import (
    LocalSandbox,
    SandboxOutput,
    equal_json,
    validate_json,
)


class QualityBudgetExceeded(Exception):
    pass


def grade_quality(
    sandbox: LocalSandbox, content: DraftContent
) -> tuple[ReferenceCheckResult, QualityCheckResult]:
    assert content.contract is not None and content.solution is not None
    total = len(content.examples) + len(content.test_cases)
    checked = executions = killed = 0

    def result(
        outcome: Outcome, reason: QualityReason
    ) -> tuple[ReferenceCheckResult, QualityCheckResult]:
        return (
            ReferenceCheckResult(outcome=outcome, checked_cases=checked, total_cases=total),
            QualityCheckResult(
                reason_code=reason,
                total_candidates=len(content.incorrect_solutions),
                killed_candidates=killed,
                executions=executions,
            ),
        )

    try:
        validate_quality_inputs(content)
        values: list[Example | TestCase] = [*content.examples, *content.test_cases]
        for case in values:
            validate_json(case.input)
            validate_json(case.expected_output)
    except ContentError as error:
        return result("incorrect", cast(QualityReason, error.code))
    except ValueError:
        return result("incorrect", "INVALID_CONTRACT")
    started = time.monotonic()

    def execute(source: str, inputs: list[object], function: str | None = None) -> SandboxOutput:
        nonlocal executions
        if executions >= MAX_QUALITY_EXECUTIONS or time.monotonic() - started >= 30:
            raise QualityBudgetExceeded()
        executions += 1
        assert content.contract is not None
        return sandbox.execute(source, function or content.contract.function_name, inputs)

    try:
        sandbox.startup_check()
        cases: list[Example | TestCase] = [*content.examples, *content.test_cases]
        for case in cases:
            output = execute(content.solution.reference_code, list(case.input))
            checked += 1
            if output.category != "returned":
                return result(
                    output.category,
                    "RESOURCE_LIMIT" if output.category == "resource_limit" else "REFERENCE_FAILED",
                )
            if not matches_json_type(output.value, content.contract.output.type) or not equal_json(
                output.value, case.expected_output
            ):
                return result("incorrect", "REFERENCE_FAILED")
        probe_source = value_error_probe_source(
            content.solution.reference_code, content.contract.function_name
        )
        for inputs in invalid_type_probes(content):
            output = execute(probe_source, list(inputs), "__mastery_expect_value_error")
            if output.category == "resource_limit":
                return result("resource_limit", "RESOURCE_LIMIT")
            if output.category != "returned" or output.value is not True:
                return result("incorrect", "REFERENCE_FAILED")
        private_tests = [case for case in content.test_cases if case.visibility == "private"]
        for candidate in content.incorrect_solutions:
            for example in content.examples:
                output = execute(candidate.source_code, list(example.input))
                if output.category == "resource_limit":
                    return result("resource_limit", "RESOURCE_LIMIT")
                if output.category != "returned" or not equal_json(
                    output.value, example.expected_output
                ):
                    return result("incorrect", "INVALID_CANDIDATES")
            for test in private_tests:
                output = execute(candidate.source_code, list(test.input))
                if output.category == "resource_limit":
                    return result("resource_limit", "RESOURCE_LIMIT")
                if output.category == "syntax_error":
                    return result("incorrect", "INVALID_CANDIDATES")
                if output.category == "runtime_error" or not equal_json(
                    output.value, test.expected_output
                ):
                    killed += 1
                    break
            else:
                return result("incorrect", "WEAK_SUITE")
        return result("passed", "PASSED")
    except QualityBudgetExceeded:
        return result("resource_limit", "RESOURCE_LIMIT")
    except (RuntimeError, OSError, ValueError):
        logger.exception("publication_quality_infrastructure_failed")
        return result("infrastructure_error", "INFRASTRUCTURE_ERROR")
