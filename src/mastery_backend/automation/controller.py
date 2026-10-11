"""Trusted orchestration outside the workspace-write coding agent."""

import argparse
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from mastery_backend.automation.processes import execute
from mastery_backend.automation.state import (
    SprintState,
    StrictRecord,
    atomic_write,
    reserve,
    run_lock,
    select_unit,
)
from mastery_backend.automation.verification import BRANCH, REPOSITORY, verify, wait_for_ci


class Configuration(StrictRecord):
    uv: str
    gh: str
    codex: str
    database_url: str


class AgentResult(StrictRecord):
    status: Literal["complete", "blocked"]
    reason: str = Field(max_length=2000)


class Controller:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.local = self.root / ".automation"
        self.workspace = self.local / "workspace"
        self.state_path = self.local / "state.json"
        self.config_path = self.local / "config.json"

    def git(self, *arguments: str, workspace: bool = False) -> str:
        return execute(["/usr/bin/git", *arguments], self.workspace if workspace else self.root)

    def state(self) -> SprintState:
        path = (
            self.state_path if self.state_path.exists() else self.root / "docs/roadmap/sprints.json"
        )
        return SprintState.model_validate_json(path.read_text())

    def save(self, state: SprintState) -> None:
        atomic_write(self.state_path, state)

    def event(self, kind: str, state: SprintState) -> None:
        atomic_write(
            self.local / "logs" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + ".json"),
            {
                "time": datetime.now(UTC).isoformat(),
                "event": kind,
                "unit": state.active_unit,
                "starting_commit": state.starting_commit,
                "phase": state.phase,
                "state": state.model_dump(mode="json"),
            },
        )

    def configuration(self) -> Configuration:
        return Configuration.model_validate_json(self.config_path.read_text())

    def preflight(self, config: Configuration) -> None:
        for path in (config.uv, config.gh, config.codex):
            if not Path(path).is_absolute() or not os.access(path, os.X_OK):
                raise RuntimeError("Configured tool missing; rerun init with actual paths")
        execute([config.uv, "--version"], self.root, timeout_seconds=30)
        execute([config.codex, "--version"], self.root, timeout_seconds=30)
        execute([config.codex, "login", "status"], self.root, timeout_seconds=30)
        execute([config.gh, "auth", "status"], self.root, timeout_seconds=30)
        repository = json.loads(execute([config.gh, "api", f"repos/{REPOSITORY}"], self.root))
        if repository["full_name"] != REPOSITORY:
            raise RuntimeError("Wrong remote repository")
        remote = self.git("remote", "get-url", "origin")
        if remote not in (
            f"https://github.com/{REPOSITORY}.git",
            f"git@github.com:{REPOSITORY}.git",
        ):
            raise RuntimeError("Origin differs from authorized repository")
        for key in ("user.name", "user.email"):
            if not self.git("config", key):
                raise RuntimeError("Git author identity is not configured")
        url = make_url(config.database_url)
        if (
            not url.database
            or not url.database.endswith("_test")
            or url.host not in {"localhost", "127.0.0.1"}
        ):
            raise RuntimeError("Only local disposable *_test PostgreSQL is accepted")
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()

    def initialize(self, config: Configuration) -> None:
        with run_lock(self.local / "run.lock"):
            if self.config_path.exists() or self.state_path.exists():
                raise RuntimeError("Already initialized; existing records preserved")
            self.preflight(config)
            if self.git("status", "--porcelain"):
                raise RuntimeError("Commit the reviewed controller before initialization")
            if not self.workspace.exists():
                existing = self.git("branch", "--list", BRANCH)
                remote = self.git("ls-remote", "--heads", "origin", BRANCH)
                if not existing and remote:
                    self.git("fetch", "origin", BRANCH)
                    self.git("branch", BRANCH, "FETCH_HEAD")
                    existing = BRANCH
                args = ["worktree", "add"]
                if not existing:
                    args.extend(["-b", BRANCH])
                args.append(str(self.workspace))
                args.append(BRANCH if existing else "HEAD")
                self.git(*args)
            if self.git("branch", "--show-current", workspace=True) != BRANCH:
                raise RuntimeError("Wrong worktree branch; no reset performed")
            # Separate control Git metadata from the agent-writable linked worktree.
            if not (self.workspace / "docs/roadmap/STATUS.md").is_file():
                raise RuntimeError(
                    "Existing automation branch lacks verified roadmap; review manually"
                )
            atomic_write(self.config_path, config)
            self.save(self.state())
            (self.local / "DISABLED").touch(mode=0o600)

    def enabled(self) -> None:
        if not self.config_path.exists() or (self.local / "DISABLED").exists():
            raise RuntimeError("Automation disabled or not initialized")

    def run(self, slot: str, retry: str | None = None, dry_run: bool = False) -> str:
        with run_lock(self.local / "run.lock"):
            state = self.state()
            if state.phase not in {"idle", "blocked"}:
                raise RuntimeError("Unfinished operation preserved; inspect status and use recover")
            unit = select_unit(state, retry)
            if unit is None:
                return "No ready unit; dependencies or blockers remain"
            if dry_run:
                return f"Would attempt {unit.id} with {unit.profile} acceptance; no work performed"
            self.enabled()
            reserve(state, unit, datetime.now(UTC), slot)
            self.save(state)
            self.event("reserved", state)
            try:
                config = self.configuration()
                self.preflight(config)
                if unit.profile == "isolation":
                    if os.getuid() == 0 or not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
                        raise RuntimeError("Required isolation capabilities absent")
                    execute(["/usr/bin/bwrap", "--version"], self.root, timeout_seconds=10)
                    execute(
                        ["/usr/bin/systemctl", "--user", "is-active", "default.target"],
                        self.root,
                        timeout_seconds=10,
                    )
                if self.git("branch", "--show-current", workspace=True) != BRANCH:
                    raise RuntimeError("Wrong automation branch")
                if self.git("status", "--porcelain", workspace=True):
                    raise RuntimeError("Unfinished work preserved; review before bounded retry")
                state.starting_commit = self.git("rev-parse", "HEAD", workspace=True)
                state.phase = "agent"
                self.save(state)
                result_path = self.local / "agent-result.json"
                result_path.unlink(missing_ok=True)
                schema = self.local / "agent-schema.json"
                atomic_write(schema, AgentResult.model_json_schema())
                prompt = (self.root / "docs/automation/sprint_prompt.md").read_text()
                prompt += f"\nUnit: {unit.id}. Profile: {unit.profile}. Only this bounded unit.\n"
                execute(
                    [
                        config.codex,
                        "-a",
                        "never",
                        "exec",
                        "--sandbox",
                        "workspace-write",
                        "--ephemeral",
                        "-C",
                        str(self.workspace),
                        "--output-schema",
                        str(schema),
                        "-o",
                        str(result_path),
                        "-",
                    ],
                    self.workspace,
                    input_text=prompt,
                    timeout_seconds=2700,
                )
                result = AgentResult.model_validate_json(result_path.read_text())
                if result.status != "complete":
                    raise RuntimeError("Agent reported blocker; private result retained")
                self.validate_changes()
                self.enabled()
                state.phase = "verification"
                self.save(state)
                verify(
                    self.workspace,
                    config.uv,
                    config.database_url,
                    unit.profile == "isolation",
                    self.local / "verification.xml",
                )
                self.enabled()
                self.git("add", "--all", workspace=True)
                self.git(
                    "commit",
                    "-m",
                    f"{unit.id}: independently verified sprint increment",
                    workspace=True,
                )
                unit.commit = self.git("rev-parse", "HEAD", workspace=True)
                state.phase = "pending_ci"
                unit.status = "pending_ci"
                self.save(state)
                self.publish_and_verify(state)
                return f"Verified {unit.id} at {unit.commit}"
            except Exception as error:
                if state.phase != "pending_ci":
                    unit.status, state.phase = "blocked", "blocked"
                # Exception text may contain connection credentials; persist only safe reason codes.
                unit.reason = type(error).__name__ + ": inspect phase/logs; work preserved"
                self.save(state)
                self.event("blocked", state)
                raise RuntimeError(
                    f"{unit.id} blocked in {state.phase}; see status/recovery"
                ) from None

    def validate_changes(self) -> None:
        changed = self.git("diff", "--name-only", "HEAD", workspace=True).splitlines()
        untracked = self.git(
            "ls-files", "--others", "--exclude-standard", workspace=True
        ).splitlines()
        protected = (
            "scripts/",
            "src/mastery_backend/automation/",
            "tests/automation/",
            ".github/",
            ".gitignore",
            "pyproject.toml",
            "uv.lock",
            "AGENTS.md",
            "docs/automation/",
            "docs/roadmap/sprints.json",
            ".python-version",
            "alembic.ini",
        )
        if not changed and not untracked:
            raise RuntimeError("No reviewable changes; no empty completion commit")
        for path in changed + untracked:
            if path.startswith(protected) or path.endswith("conftest.py"):
                raise RuntimeError("Protected configuration changed; operator review required")
            if path in changed and (
                path.startswith("tests/") or not (self.workspace / path).exists()
            ):
                raise RuntimeError("Existing acceptance tests/deletion changed; review required")
            if (self.workspace / path).is_symlink():
                raise RuntimeError("Symlink changes require operator review")
        if self.git("rev-parse", "HEAD", workspace=True) != self.state().starting_commit:
            raise RuntimeError("Agent changed Git history; preserve and review manually")

    def publish_and_verify(self, state: SprintState) -> None:
        unit = next(unit for unit in state.units if unit.id == state.active_unit)
        if not unit.commit or self.git("rev-parse", "HEAD", workspace=True) != unit.commit:
            raise RuntimeError("Recovery SHA differs from journal; no push performed")
        self.enabled()
        config = self.configuration()
        self.git("push", "origin", f"HEAD:refs/heads/{BRANCH}", workspace=True)
        if not self.git("ls-remote", "--heads", "origin", BRANCH).startswith(unit.commit):
            raise RuntimeError("Remote branch SHA does not match pushed work")
        unit.ci_url = wait_for_ci(config.gh, self.workspace, unit.commit)
        unit.status, unit.reason = "verified", None
        state.phase = "idle"
        self.save(state)
        self.event("verified", state)

    def recover(self) -> None:
        with run_lock(self.local / "run.lock"):
            state = self.state()
            if state.phase == "pending_ci":
                self.publish_and_verify(state)
            elif state.phase not in {"idle", "blocked"}:
                unit = next(unit for unit in state.units if unit.id == state.active_unit)
                unit.status, unit.reason = (
                    "blocked",
                    "Interrupted; inspect preserved work before retry",
                )
                state.phase = "blocked"
                self.save(state)
                self.event("interrupted", state)

    def smoke(self) -> None:
        with run_lock(self.local / "run.lock"):
            config = self.configuration()
            smoke = self.local / "smoke"
            smoke.mkdir(mode=0o700, exist_ok=True)
            execute(["/usr/bin/git", "init", "--quiet"], smoke)
            response = execute(
                [
                    config.codex,
                    "-a",
                    "never",
                    "exec",
                    "--sandbox",
                    "workspace-write",
                    "--ephemeral",
                    "-C",
                    str(smoke),
                    "-o",
                    str(smoke / "response.txt"),
                    "-",
                ],
                smoke,
                timeout_seconds=180,
                input_text=(
                    "Scheduled launcher smoke test only. Do not use tools or modify files. "
                    "Reply exactly AUTO001_SMOKE_OK."
                ),
            )
            del response
            if (smoke / "response.txt").read_text().strip() != "AUTO001_SMOKE_OK":
                raise RuntimeError("Authenticated Codex smoke response invalid")
            atomic_write(
                self.local / "scheduled-smoke.json",
                {
                    "time": datetime.now(UTC).isoformat(),
                    "uid": os.getuid(),
                    "pid": os.getpid(),
                    "distribution": os.environ.get("WSL_DISTRO_NAME"),
                    "result": "success",
                    "codex": config.codex,
                },
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "command",
        choices=[
            "init",
            "run",
            "run-batch",
            "status",
            "enable",
            "disable",
            "recover",
            "smoke",
            "logs",
        ],
    )
    parser.add_argument("--slot", choices=["09", "14", "19"], default="09")
    parser.add_argument("--retry")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--maximum-units", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--codex")
    parser.add_argument("--database-url")
    args = parser.parse_args()
    controller = Controller(args.root)
    try:
        if args.command == "init":
            if not args.codex or not args.database_url:
                raise RuntimeError("init requires --codex and disposable --database-url")
            controller.initialize(
                Configuration(
                    uv=shutil.which("uv") or "",
                    gh=shutil.which("gh") or "",
                    codex=args.codex,
                    database_url=args.database_url,
                )
            )
        elif args.command == "disable":
            controller.local.mkdir(mode=0o700, exist_ok=True)
            (controller.local / "DISABLED").touch(mode=0o600)
        elif args.command == "enable":
            with run_lock(controller.local / "run.lock"):
                controller.preflight(controller.configuration())
                if not (controller.local / "scheduled-smoke.json").is_file():
                    raise RuntimeError("Real scheduled-launch smoke must succeed before enable")
                (controller.local / "DISABLED").unlink(missing_ok=True)
        elif args.command in {"run", "run-batch"}:
            count = args.maximum_units if args.command == "run-batch" else 1
            for index in range(count):
                slot = args.slot if args.command == "run" else f"batch-{args.slot}-{index}"
                print(controller.run(slot, args.retry, args.dry_run))
        elif args.command == "recover":
            controller.recover()
        elif args.command == "smoke":
            controller.smoke()
        elif args.command == "logs":
            print(controller.local / "logs")
        else:
            print(controller.state().model_dump_json(indent=2))
            print("disabled:", (controller.local / "DISABLED").exists())
    except Exception as error:
        print(f"Controller stopped: {type(error).__name__}; inspect status and private records")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
