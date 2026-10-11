"""Independent, fixed acceptance commands and exact-SHA remote CI verification."""

import json
import os
import time
from pathlib import Path
from xml.etree import ElementTree

from mastery_backend.automation.processes import execute
from mastery_backend.automation.state import atomic_write

REPOSITORY = "00-Aryan/python_mastry"
BRANCH = "automation/daily-sprints"


def check_test_report(path: Path, isolation: bool) -> tuple[int, int]:
    root = ElementTree.parse(path).getroot()
    cases = list(root.iter("testcase"))
    skipped = [case for case in cases if case.find("skipped") is not None]
    failed = any(
        case.find("failure") is not None or case.find("error") is not None for case in cases
    )
    if failed or len(cases) - len(skipped) < 306:
        raise RuntimeError("Regression report failed or lacked required PostgreSQL coverage")
    allowed = ("test_local_isolation", "test_local_runner")
    if (
        (isolation and skipped)
        or len(skipped) > 25
        or any(
            not any(name in case.attrib.get("classname", "") for name in allowed)
            for case in skipped
        )
    ):
        raise RuntimeError("Unexpected skipped acceptance checks")
    return len(cases) - len(skipped), len(skipped)


def verify(workspace: Path, uv: str, database_url: str, isolation: bool, report: Path) -> None:
    environment = dict(os.environ)
    environment.pop("DATABASE_URL", None)
    environment["TEST_DATABASE_URL"] = database_url
    environment["RUN_ISOLATION_TESTS"] = "1" if isolation else "0"
    commands = [
        [uv, "lock", "--check"],
        [uv, "sync", "--locked"],
        [uv, "run", "ruff", "check", "."],
        [uv, "run", "ruff", "format", "--check", "."],
        [uv, "run", "mypy", "src", "migrations"],
    ]
    evidence: dict[str, object] = {
        "commands": [],
        "profile": "isolation" if isolation else "baseline",
    }
    completed: list[list[str]] = []
    evidence["commands"] = completed
    evidence_path = report.with_suffix(".commands.json")
    atomic_write(evidence_path, evidence)
    for command in commands:
        execute(command, workspace, environment=environment)
        completed.append(command)
        atomic_write(evidence_path, evidence)
    migrations = dict(environment, DATABASE_URL=database_url)
    for action in ("upgrade", "current", "check"):
        arguments = [uv, "run", "alembic", action]
        if action == "upgrade":
            arguments.append("head")
        execute(arguments, workspace, environment=migrations)
        completed.append(arguments)
        atomic_write(evidence_path, evidence)
    execute([uv, "run", "pytest", "--junitxml=" + str(report)], workspace, environment=environment)
    passed, skipped = check_test_report(report, isolation)
    completed.append([uv, "run", "pytest"])
    evidence.update(passed=passed, skipped=skipped)
    atomic_write(evidence_path, evidence)
    execute([uv, "build"], workspace, environment=environment)
    completed.append([uv, "build"])
    atomic_write(evidence_path, evidence)


def successful_ci(runs: list[dict[str, object]], sha: str) -> dict[str, object] | None:
    matching = [
        run
        for run in runs
        if run.get("head_sha") == sha
        and run.get("head_branch") == BRANCH
        and run.get("name") == "Backend checks"
        and run.get("event") == "push"
    ]
    if not matching:
        return None
    latest = max(matching, key=lambda run: int(str(run["id"])))
    if latest.get("status") != "completed":
        return None
    if latest.get("conclusion") != "success":
        raise RuntimeError("Exact-commit CI failed; dependent work is blocked")
    return latest


def wait_for_ci(gh: str, workspace: Path, sha: str, timeout_seconds: int = 1200) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        data = json.loads(
            execute(
                [gh, "api", f"repos/{REPOSITORY}/actions/runs?head_sha={sha}&per_page=100"],
                workspace,
                timeout_seconds=60,
            )
        )
        run = successful_ci(data["workflow_runs"], sha)
        if run is not None:
            jobs = json.loads(
                execute(
                    [gh, "api", f"repos/{REPOSITORY}/actions/runs/{run['id']}/jobs?per_page=100"],
                    workspace,
                    timeout_seconds=60,
                )
            )["jobs"]
            required = [job for job in jobs if job["name"] == "checks"]
            if len(required) != 1 or required[0]["conclusion"] != "success":
                raise RuntimeError("Required CI job is absent or unsuccessful")
            return str(run["html_url"])
        time.sleep(10)
    raise RuntimeError("Exact-commit CI unavailable within bounded wait; use recover")
