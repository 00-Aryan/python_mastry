"""Opt-in REAL execution checks; no fake sandbox or mocked crash claims."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox, equal_json
from mastery_backend.infrastructure.runner.runtime_image import verify_runtime


@pytest.fixture
def sandbox(isolated_runtime):
    binding = LocalSandbox(isolated_runtime)
    binding.startup_check()
    yield binding
    binding.cancel()
    assert binding.active_unit is None


@pytest.mark.parametrize(
    "source,category,value",
    [
        ("def solve(x): return x + 1", "returned", 3),
        ("def solve(x): return x - 1", "returned", 1),
        ("def solve(:", "syntax_error", None),
        ("def solve(x): raise ValueError('PRIVATE_DIAGNOSTIC')", "runtime_error", None),
        ("def solve(x):\n while True: pass", "resource_limit", None),
        ("def solve(x):\n while True: print('x' * 8192)", "resource_limit", None),
        ("def solve(x): return bytearray(512 * 1024 * 1024)", "resource_limit", None),
        ("def solve(x):\n import os\n os.fork()", "runtime_error", None),
        ("def solve(x):\n import socket\n socket.socket()", "runtime_error", None),
        (
            "def solve(x): open('/tmp/huge', 'wb').write(b'x' * (2 * 1024 * 1024))",
            "resource_limit",
            None,
        ),
        (
            "def solve(x): return open('/home/aryan/projects/python_mastry/.env').read()",
            "runtime_error",
            None,
        ),
        ("def solve(x): return open('/bootstrap.py','w')", "runtime_error", None),
    ],
)
def test_real_execution(sandbox, source, category, value):
    result = sandbox.execute(source, "solve", [2])
    assert result.category == category
    assert result.value == value
    assert sandbox.active_unit is None


def test_fresh_storage_environment_and_privilege_controls(sandbox):
    assert (
        sandbox.execute(
            "def solve(): open('/tmp/marker','w').write('x'); return True", "solve", []
        ).value
        is True
    )
    result = sandbox.execute(
        """def solve():
 import os
 status = open('/proc/self/status').read()
 return [os.path.exists('/tmp/marker'), os.path.exists('/run'),
         os.path.exists('/proc/1/root/home'), os.getuid(), sorted(os.environ), status]
""",
        "solve",
        [],
    )
    assert result.category == "returned"
    assert result.value[:4] == [False, False, False, 1000]
    assert result.value[4] == ["LANG", "LD_LIBRARY_PATH", "PWD"]
    assert "NoNewPrivs:\t1" in result.value[5]
    assert "Seccomp:\t2" in result.value[5]
    assert "CapEff:\t0000000000000000" in result.value[5]


def test_missing_control_fails_before_source(sandbox, monkeypatch):
    def reject(*arguments):
        raise RuntimeError("controls absent")

    monkeypatch.setattr(sandbox, "verify_controls", reject)
    with pytest.raises(RuntimeError, match="controls absent"):
        sandbox.execute("def solve(): return True", "solve", [])
    assert sandbox.active_unit is None


def test_manifest_rejects_changes(tmp_path):
    # No execution necessary for this fail-closed integrity test.
    image = tmp_path / "image"
    image.mkdir()
    (image / "evil").write_text("changed")
    (tmp_path / "manifest.json").write_text("{}")
    with pytest.raises(RuntimeError):
        verify_runtime(tmp_path)


def test_json_comparison_is_type_aware():
    assert not equal_json(True, 1)
    assert not equal_json([True], [1])
    assert equal_json({"a": [1, "x"]}, {"a": [1, "x"]})


def test_real_worker_sigkill_independent_workload_cleanup(isolated_runtime, tmp_path):
    marker = tmp_path / "active-unit"
    script = """import sys
from pathlib import Path
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox
s = LocalSandbox(Path(sys.argv[1]))
original = s.verify_controls
def controls(unit, process):
 original(unit, process)
 Path(sys.argv[2]).write_text(unit)
s.verify_controls = controls
s.execute('def solve():\\n while True: pass', 'solve', [])
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(isolated_runtime), str(marker)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), "Real child worker never reached a live isolated service"
        unit = marker.read_text()
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=2)
        assert process.returncode == -signal.SIGKILL
        # Independent service RuntimeMaxSec bounds the orphan interval after a real SIGKILL.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = subprocess.run(
                ["/usr/bin/systemctl", "--user", "is-active", unit],
                capture_output=True,
                text=True,
                check=False,
            )
            if state.stdout.strip() != "active":
                break
            time.sleep(0.05)
        assert state.stdout.strip() != "active"
        group = subprocess.run(
            ["/usr/bin/systemctl", "--user", "show", unit, "--property=ControlGroup", "--value"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        assert (
            not group
            or not (Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs").read_text().strip()
        )
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)


def test_real_cancellation_stops_complete_unit(sandbox):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    ready = Event()
    original = sandbox.verify_controls

    def controls(unit, process):
        original(unit, process)
        ready.set()

    sandbox.verify_controls = controls
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(sandbox.execute, "def solve():\n while True: pass", "solve", [])
        assert ready.wait(3)
        time.sleep(0.1)
        sandbox.cancel()
        with pytest.raises(RuntimeError, match="cancelled"):
            result.result(timeout=5)
    assert sandbox.active_unit is None


def test_credentials_and_expected_assets_never_enter_sandbox(sandbox, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "DATABASE_CREDENTIAL_SENTINEL")
    monkeypatch.setenv("RUNNER_CREDENTIAL", "RUNNER_CREDENTIAL_SENTINEL")
    result = sandbox.execute(
        """def solve():
 import os
 return [dict(os.environ), open('/proc/1/environ', 'rb').read().decode(),
         sorted(globals()), sorted(os.listdir('/'))]
""",
        "solve",
        [],
    )
    assert result.category == "returned"
    text = str(result.value)
    for forbidden in (
        "DATABASE_CREDENTIAL_SENTINEL",
        "RUNNER_CREDENTIAL_SENTINEL",
        "expected_json",
        "lease_token",
        "source_hash",
        "PRIVATE_SOLUTION",
    ):
        assert forbidden not in text
    assert set(result.value[2]) <= {"__builtins__", "__name__", "__warningregistry__", "solve"}
    assert set(result.value[3]) <= {
        "bootstrap.py",
        "dev",
        "lib",
        "lib64",
        "usr",
        "proc",
        "runtime",
        "tmp",
    }
