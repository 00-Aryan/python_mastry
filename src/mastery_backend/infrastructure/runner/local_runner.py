"""Grade bounded JSON outside isolation; no database/session/credential handling."""

import time
from collections.abc import Callable
from datetime import datetime

from mastery_backend.domain.evaluations import Outcome, RunnerRequest
from mastery_backend.infrastructure.runner.local_sandbox import (
    LocalSandbox,
    equal_json,
    validate_json,
)


def grade_request(
    sandbox: LocalSandbox, request: RunnerRequest, now: Callable[[], datetime]
) -> Outcome:
    if not 1 <= len(request.tests) <= 64:
        raise RuntimeError("Unsupported test bundle size")
    started = time.monotonic()
    for test in request.tests:
        if time.monotonic() - started >= 10 or now() >= request.execution_deadline:
            return "resource_limit"
        validate_json(test.input_json)
        output = sandbox.execute(
            request.source_code, request.contract["function_name"], test.input_json
        )
        if output.category != "returned":
            return output.category
        if not equal_json(output.value, test.expected_json):
            return "incorrect"
    return "passed"
