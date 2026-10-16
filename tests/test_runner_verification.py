"""Real protocol abuse and cleanup checks for S010a; require the existing full sandbox."""

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox


@pytest.mark.parametrize(
    "body",
    [
        "return float('nan')",
        "return {1, 2}",
        "value = 0\nfor _ in range(25): value = [value]\nreturn value",
        "import os\nos.write(1, b\"__import__('os').system('false')\")\nreturn 1",
        "import os\nos.write(1, bytes([128, 4, 255]))\nreturn 1",
    ],
    ids=["nonfinite", "nonjson", "deep", "expression-output", "binary-output"],
)
def test_hostile_real_return_is_runtime_failure(isolated_runtime, body):
    sandbox = LocalSandbox(isolated_runtime)
    sandbox.startup_check()
    source = "def solve():\n " + body.replace("\n", "\n ")
    # These sources remain data and execute only through the production isolation profile.
    result = sandbox.execute(source, "solve", [])
    assert result.category == "runtime_error"
    assert result.value is None
    assert sandbox.active_unit is None


def test_input_bound_rejects_before_creating_workload(isolated_runtime):
    sandbox = LocalSandbox(isolated_runtime)
    with pytest.raises(RuntimeError, match="input exceeds"):
        sandbox.execute("def solve(value): return value", "solve", ["x" * 131072])
    assert sandbox.active_unit is None


def test_resource_cleanup_preserves_unrelated_service(isolated_runtime):
    sandbox = LocalSandbox(isolated_runtime)
    sandbox.startup_check()
    sentinel = "mastery-verification-sentinel-" + uuid4().hex
    executed = []
    original = sandbox.verify_controls

    def remember(unit, process):
        original(unit, process)
        executed.append(unit)

    sandbox.verify_controls = remember
    try:
        # A trusted sleep is an unrelated workload, never a fallback for learner execution.
        subprocess.run(
            [
                "/usr/bin/systemd-run",
                "--user",
                "--quiet",
                "--collect",
                "--unit=" + sentinel,
                "--property=RuntimeMaxSec=30",
                "--property=NoNewPrivileges=yes",
                "/usr/bin/sleep",
                "25",
            ],
            check=True,
            capture_output=True,
            timeout=5,
        )
        assert (
            sandbox.execute("def solve():\n while True: pass", "solve", []).category
            == "resource_limit"
        )
        assert executed and sandbox.active_unit is None
        subprocess.run(
            ["/usr/bin/systemctl", "--user", "is-active", "--quiet", sentinel],
            check=True,
            capture_output=True,
            timeout=5,
        )
        for unit in executed:
            state = subprocess.run(
                ["/usr/bin/systemctl", "--user", "is-active", unit],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            assert state.stdout.strip() not in {"active", "activating", "deactivating"}
            group = subprocess.run(
                [
                    "/usr/bin/systemctl",
                    "--user",
                    "show",
                    unit,
                    "--property=ControlGroup",
                    "--value",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            processes = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
            assert not group or not processes.exists() or not processes.read_text().strip()
    finally:
        sandbox.cancel()
        subprocess.run(
            ["/usr/bin/systemctl", "--user", "stop", sentinel],
            check=False,
            capture_output=True,
            timeout=5,
        )
