import json

import pytest

from mastery_backend.automation.controller import Configuration, Controller
from mastery_backend.automation.processes import execute
from mastery_backend.automation.state import SprintState, Unit
from mastery_backend.automation.verification import BRANCH, check_test_report, successful_ci


def setup_controller(tmp_path):
    controller = Controller(tmp_path)
    state = SprintState(units=[Unit(id="S010a", status="ready", profile="isolation")])
    controller.save(state)
    return controller


def test_dry_run_no_ledger_change(tmp_path):
    controller = setup_controller(tmp_path)
    before = controller.state_path.read_bytes()
    assert "S010a" in controller.run("09", dry_run=True)
    assert controller.state_path.read_bytes() == before
    assert not controller.workspace.exists()


def test_disable_denies_run_without_reserving(tmp_path):
    controller = setup_controller(tmp_path)
    with pytest.raises(RuntimeError, match="disabled"):
        controller.run("09")
    assert controller.state().daily_attempts == {}


def test_failed_preflight_blocks_preserves_and_stops_dependents(tmp_path, monkeypatch):
    controller = setup_controller(tmp_path)
    controller.config_path.write_text(
        json.dumps(
            {
                "uv": "/uv",
                "gh": "/gh",
                "codex": "/codex",
                "database_url": "postgresql://localhost/x_test",
            }
        )
    )
    monkeypatch.setattr(
        controller, "preflight", lambda config: (_ for _ in ()).throw(RuntimeError())
    )
    with pytest.raises(RuntimeError, match="blocked"):
        controller.run("09")
    state = controller.state()
    assert state.phase == "blocked" and state.units[0].attempts == 1
    assert controller.run("14") == "No ready unit; dependencies or blockers remain"
    assert len(list((controller.local / "logs").glob("*.json"))) == 2


def test_recover_interruption_never_restarts_agent(tmp_path):
    controller = setup_controller(tmp_path)
    state = controller.state()
    state.phase, state.active_unit = "verification", "S010a"
    state.units[0].status = "running"
    controller.save(state)
    controller.recover()
    assert controller.state().phase == "blocked"
    assert "Interrupted" in controller.state().units[0].reason


def test_pending_ci_recovery_reuses_commit(tmp_path, monkeypatch):
    controller = setup_controller(tmp_path)
    state = controller.state()
    state.phase, state.active_unit = "pending_ci", "S010a"
    state.units[0].commit = "a" * 40
    controller.save(state)
    seen = []
    monkeypatch.setattr(
        controller, "publish_and_verify", lambda value: seen.append(value.units[0].commit)
    )
    controller.recover()
    assert seen == ["a" * 40]


def test_exact_ci_rejects_other_sha_branch_failure_and_missing():
    sha = "a" * 40
    base = dict(
        id=1,
        head_sha=sha,
        head_branch=BRANCH,
        name="Backend checks",
        event="push",
        status="completed",
        conclusion="success",
    )
    assert successful_ci([base], sha) == base
    assert successful_ci([dict(base, head_sha="b" * 40)], sha) is None
    assert successful_ci([dict(base, head_branch="main")], sha) is None
    assert successful_ci([], sha) is None
    with pytest.raises(RuntimeError, match="failed"):
        successful_ci([dict(base, conclusion="failure")], sha)


def test_verification_rejects_skipped_postgres_and_empty_report(tmp_path):
    path = tmp_path / "report.xml"
    path.write_text(
        '<testsuite><testcase classname="integration"><skipped/></testcase></testsuite>'
    )
    with pytest.raises(RuntimeError):
        check_test_report(path, False)
    cases = '<testcase classname="regression"/>' * 306
    path.write_text(
        "<testsuite>"
        + cases
        + '<testcase classname="integration"><skipped/></testcase></testsuite>'
    )
    with pytest.raises(RuntimeError, match="skipped"):
        check_test_report(path, False)
    path.write_text(
        "<testsuite>"
        + cases
        + '<testcase classname="test_local_isolation"><skipped/></testcase></testsuite>'
    )
    assert check_test_report(path, False) == (306, 1)
    with pytest.raises(RuntimeError, match="skipped"):
        check_test_report(path, True)


def test_fixed_process_arguments_and_timeout(tmp_path):
    assert (
        execute(["/usr/bin/printf", "%s", "$(touch forbidden)"], tmp_path) == "$(touch forbidden)"
    )
    assert not (tmp_path / "forbidden").exists()
    with pytest.raises(RuntimeError, match="timed out"):
        execute(["/usr/bin/sleep", "5"], tmp_path, timeout_seconds=1)


def test_scope_protects_controller(tmp_path, monkeypatch):
    controller = setup_controller(tmp_path)
    monkeypatch.setattr(
        controller, "git", lambda *args, **kw: "src/mastery_backend/automation/state.py"
    )
    with pytest.raises(RuntimeError, match="Protected"):
        controller.validate_changes()


def test_claimed_success_still_runs_independent_checks_and_never_pushes_failure(
    tmp_path, monkeypatch
):
    import mastery_backend.automation.controller as module

    controller = setup_controller(tmp_path)
    controller.workspace.mkdir(parents=True)
    controller.config_path.write_text(
        Configuration(
            uv="/uv", gh="/gh", codex="/codex", database_url="postgresql://localhost/mastery_test"
        ).model_dump_json()
    )
    (controller.root / "docs/automation").mkdir(parents=True)
    (controller.root / "docs/automation/sprint_prompt.md").write_text("fixed prompt")
    (controller.root / "docs/roadmap/sprints").mkdir(parents=True)
    (controller.root / "docs/roadmap/sprints/S010a.md").write_text("trusted acceptance")
    state = controller.state()
    state.units[0].profile = "baseline"
    controller.save(state)
    monkeypatch.setattr(controller, "preflight", lambda config: None)
    monkeypatch.setattr(controller, "validate_changes", lambda: None)
    calls = []

    def git(*args, **kwargs):
        calls.append(args)
        if args[0] == "branch":
            return BRANCH
        if args[0] == "rev-parse":
            return "a" * 40
        return ""

    def agent(*args, **kwargs):
        (controller.local / "agent-result.json").write_text('{"status":"complete","reason":"done"}')
        return ""

    def reject(*args, **kwargs):
        raise RuntimeError("Independent checks failed")

    monkeypatch.setattr(controller, "git", git)
    monkeypatch.setattr(module, "execute", agent)
    monkeypatch.setattr(module, "verify", reject)
    with pytest.raises(RuntimeError, match="blocked"):
        controller.run("09")
    assert controller.state().units[0].status == "blocked"
    assert not any(call[0] in {"push", "commit", "add"} for call in calls)
    assert controller.state().starting_commit == "a" * 40


def test_publish_requires_exact_journal_sha_and_required_ci(tmp_path, monkeypatch):
    import mastery_backend.automation.controller as module

    controller = setup_controller(tmp_path)
    controller.config_path.write_text(
        Configuration(
            uv="/uv", gh="/gh", codex="/codex", database_url="postgresql://localhost/mastery_test"
        ).model_dump_json()
    )
    state = controller.state()
    state.active_unit, state.phase = "S010a", "pending_ci"
    state.units[0].commit = "a" * 40
    state.units[0].status = "pending_ci"
    controller.save(state)
    calls = []

    def git(*args, **kwargs):
        calls.append(args)
        return "a" * 40

    monkeypatch.setattr(controller, "git", git)
    seen = []
    monkeypatch.setattr(module, "wait_for_ci", lambda gh, ws, sha: seen.append(sha) or "https://ci")
    controller.publish_and_verify(state)
    assert seen == ["a" * 40]
    assert state.units[0].status == "verified"
    assert ("push", "origin", "HEAD:refs/heads/automation/daily-sprints") in calls
    monkeypatch.setattr(controller, "git", lambda *args, **kwargs: "b" * 40)
    with pytest.raises(RuntimeError, match="SHA differs"):
        controller.publish_and_verify(state)


def test_output_limit_terminates_process(tmp_path):
    with pytest.raises(RuntimeError, match="output exceeded"):
        execute(["/usr/bin/yes"], tmp_path, timeout_seconds=3)


@pytest.mark.parametrize(
    "task_result,started,enabled",
    [(0, 1791753130, True), (1, 1791753130, False), (0, 1791750000, False)],
)
def test_enable_requires_matching_real_task_completion(
    tmp_path, monkeypatch, task_result, started, enabled
):
    import mastery_backend.automation.controller as module

    controller = setup_controller(tmp_path)
    controller.config_path.write_text(
        Configuration(
            uv="/uv", gh="/gh", codex="/codex", database_url="postgresql://localhost/mastery_test"
        ).model_dump_json()
    )
    (controller.local / "DISABLED").touch()
    (controller.local / "scheduled-smoke.json").write_text(
        json.dumps(
            {
                "time": "2026-10-11T21:12:17.223723+00:00",
                "uid": module.os.getuid(),
                "result": "success",
            }
        )
    )
    monkeypatch.setattr(module.Controller, "preflight", lambda self, config: None)
    monkeypatch.setattr(
        module,
        "execute",
        lambda *args, **kwargs: json.dumps({"result": task_result, "started": started}),
    )
    monkeypatch.setattr("sys.argv", ["controller", "--root", str(tmp_path), "enable"])
    if enabled:
        module.main()
        assert not (controller.local / "DISABLED").exists()
    else:
        with pytest.raises(SystemExit):
            module.main()
        assert (controller.local / "DISABLED").exists()
