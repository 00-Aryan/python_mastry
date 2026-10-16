"""Fail-closed Bubblewrap/systemd supervisor. Only sealed runtime files enter isolation."""

import json
import os
import selectors
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from mastery_backend.infrastructure.runner.runtime_image import verify_runtime


@dataclass(frozen=True)
class SandboxOutput:
    category: Literal["returned", "resource_limit", "syntax_error", "runtime_error"]
    value: object = None


class LocalSandbox:
    def __init__(self, directory: Path) -> None:
        if os.getuid() == 0 or sys.platform != "linux":
            raise RuntimeError("Isolated worker requires non-root Linux")
        self.directory = directory.resolve()
        self.image_hash, self.profile_hash = verify_runtime(self.directory)
        self.active_unit: str | None = None
        self.checked = False
        self.cancelled = False
        self._state_lock = RLock()
        self._controls_verified = False

    def cancel(self) -> None:
        # Keep control validation intact. The execution observes this request before READY/source.
        # RLock also permits the worker's same-thread signal handler to request cancellation.
        with self._state_lock:
            self.cancelled = True
            unit = self.active_unit if self._controls_verified else None
        if unit is not None:
            self._stop_unit(unit)

    @staticmethod
    def _stop_unit(unit: str) -> None:
        subprocess.run(
            ["/usr/bin/systemctl", "--user", "stop", unit],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )

    def _raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeError("Isolated execution was cancelled")

    def wait_for_ready(self, process: subprocess.Popen[bytes]) -> None:
        """Order a pending stop request against observation of a genuine bootstrap failure."""
        assert process.stdout is not None
        with self._state_lock:
            self._raise_if_cancelled()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            readable = selector.select(2)
            with self._state_lock:
                self._raise_if_cancelled()
                frame = os.read(process.stdout.fileno(), 64) if readable else b""
                # Cancellation can cause EOF, but cannot explain a malformed nonempty frame.
                if frame and frame != b"READY\n":
                    raise RuntimeError("Trusted sandbox bootstrap is unavailable")
                self._raise_if_cancelled()
                if not frame:
                    raise RuntimeError("Trusted sandbox bootstrap is unavailable")

    def send_payload(self, process: subprocess.Popen[bytes], payload: bytes) -> None:
        """Serialize cancellation and source transmission after the validated handshake."""
        assert process.stdin is not None
        with self._state_lock:
            self._raise_if_cancelled()
            try:
                process.stdin.write(payload)
                process.stdin.close()
            except BrokenPipeError:
                # A same-thread signal handler can reenter while write/close is in progress.
                self._raise_if_cancelled()
                raise

    def verify_controls(self, unit: str, process: subprocess.Popen[bytes]) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            result = subprocess.run(
                [
                    "/usr/bin/systemctl",
                    "--user",
                    "show",
                    unit,
                    "--property=ControlGroup,MemoryMax,MemorySwapMax,TasksMax,KillMode,"
                    "KillSignal,NoNewPrivileges,RuntimeMaxUSec,CPUQuotaPerSecUSec,LimitCPU",
                ],
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
            )
            properties = dict(
                line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
            )
            group = properties.get("ControlGroup", "")
            if group:
                cgroup = Path("/sys/fs/cgroup") / group.lstrip("/")
                if (cgroup / "memory.max").exists():
                    expected = {
                        "MemoryMax": "134217728",
                        "MemorySwapMax": "0",
                        "TasksMax": "16",
                        "KillMode": "control-group",
                        "KillSignal": "9",
                        "NoNewPrivileges": "yes",
                        "RuntimeMaxUSec": "3s",
                        "LimitCPU": "2",
                    }
                    if any(properties.get(key) != value for key, value in expected.items()):
                        raise RuntimeError("Required systemd controls are missing")
                    limits = {"memory.max": "134217728", "memory.swap.max": "0", "pids.max": "16"}
                    if any(
                        (cgroup / key).read_text().strip() != value for key, value in limits.items()
                    ):
                        raise RuntimeError("Required cgroup controls are missing")
                    quota, period = (cgroup / "cpu.max").read_text().split()
                    if quota == "max" or int(quota) > int(period):
                        raise RuntimeError("CPU quota is missing")
                    return
            if process.poll() is not None:
                break
            time.sleep(0.01)
        raise RuntimeError("Isolated service did not become ready")

    def execute(self, source: str, function: str, inputs: list[object]) -> SandboxOutput:
        with self._state_lock:
            self._raise_if_cancelled()
        hashes = verify_runtime(self.directory)
        if hashes != (self.image_hash, self.profile_hash):
            raise RuntimeError("Pinned runtime has changed")
        payload = (
            json.dumps(
                {"source": source, "function": function, "input": inputs}, allow_nan=False
            ).encode()
            + b"\n"
        )
        if len(payload) > 131072:
            raise RuntimeError("Runner input exceeds the bounded protocol")
        unit = "mastery-sandbox-" + uuid4().hex
        with self._state_lock:
            self._raise_if_cancelled()
            if self.active_unit is not None:
                raise RuntimeError("A sandbox supports only one active execution")
            self.active_unit = unit
            self._controls_verified = False
        launcher = Path(__file__).with_name("sandbox_launcher.py")
        command = [
            "/usr/bin/systemd-run",
            "--user",
            "--quiet",
            "--wait",
            "--pipe",
            "--unit=" + unit,
            "--property=OOMPolicy=kill",
            "--property=MemoryMax=134217728",
            "--property=MemorySwapMax=0",
            "--property=TasksMax=16",
            "--property=CPUQuota=100%",
            "--property=LimitCPU=2",
            "--property=RuntimeMaxSec=3",
            "--property=TimeoutStopSec=1",
            "--property=KillMode=control-group",
            "--property=KillSignal=SIGKILL",
            "--property=NoNewPrivileges=yes",
            sys.executable,
            "-I",
            str(launcher),
            str(self.directory / "image"),
            str(self.directory / "seccomp.bpf"),
        ]
        process: subprocess.Popen[bytes] | None = None
        output = bytearray()
        total = 0
        limited = False
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            self.verify_controls(unit, process)
            with self._state_lock:
                self._controls_verified = True
                self._raise_if_cancelled()
            assert process.stdout is not None and process.stderr is not None
            self.wait_for_ready(process)
            self.send_payload(process, payload)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, True)
                selector.register(process.stderr, selectors.EVENT_READ, False)
                deadline = time.monotonic() + 4
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        limited = True
                        self._stop_unit(unit)
                        break
                    for key, _ in selector.select(0.05):
                        chunk = os.read(key.fd, 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        if total > 65536:
                            limited = True
                            self._stop_unit(unit)
                            break
                        if key.data:
                            output.extend(chunk)
                    if limited:
                        break
            code = process.wait(timeout=5)
            service_result = subprocess.run(
                ["/usr/bin/systemctl", "--user", "show", unit, "--property=Result", "--value"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout.strip()
            if service_result in {"oom-kill", "timeout"}:
                limited = True
            if self.cancelled and not limited:
                raise RuntimeError("Isolated execution was cancelled")
            if limited or code in {137, 9, -9, 152, -24}:
                return SandboxOutput("resource_limit")
            if code == 71:
                return SandboxOutput("resource_limit")
            if code == 65:
                return SandboxOutput("syntax_error")
            if code != 0:
                return SandboxOutput("runtime_error")
            try:
                value = json.loads(
                    output, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
                )
                validate_json(value)
                return SandboxOutput("returned", value)
            except (ValueError, RecursionError):
                return SandboxOutput("runtime_error")
        finally:
            try:
                self._stop_unit(unit)
            finally:
                try:
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=5)
                        for stream in (process.stdin, process.stdout, process.stderr):
                            if stream is not None:
                                stream.close()
                    subprocess.run(
                        ["/usr/bin/systemctl", "--user", "reset-failed", unit],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2,
                        check=False,
                    )
                finally:
                    with self._state_lock:
                        self.active_unit = None
                        self._controls_verified = False

    def startup_check(self) -> None:
        source = """import os, socket

def probe():
    status = open('/proc/self/status').read()
    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
    assert os.getuid() == 1000 and fields['NoNewPrivs'].strip() == '1'
    assert fields['CapEff'].strip() == '0000000000000000'
    assert fields['Seccomp'].strip() == '2'
    try: socket.socket()
    except PermissionError: pass
    else: raise AssertionError()
    try: os.fork()
    except PermissionError: pass
    else: raise AssertionError()
    assert not os.path.exists('/home') and not os.path.exists('/run')
    try: open('/bootstrap.py', 'w')
    except OSError: pass
    else: raise AssertionError()
    assert set(os.environ) <= {'LD_LIBRARY_PATH', 'LANG', 'LC_CTYPE', 'PWD'}
    return True
"""
        result = self.execute(source, "probe", [])
        if result != SandboxOutput("returned", True):
            raise RuntimeError("Mandatory sandbox startup probe failed")
        self.checked = True


def validate_json(value: object, depth: int = 0) -> None:
    if depth > 20:
        raise ValueError("JSON nesting exceeds protocol limit")
    if isinstance(value, dict):
        for item in value.values():
            validate_json(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            validate_json(item, depth + 1)


def equal_json(left: object, right: object) -> bool:
    # Preserve JSON types; Python's True == 1 is not a correct answer comparison.
    if type(left) is not type(right):
        return False
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            equal_json(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(equal_json(left[k], right[k]) for k in left)
    return bool(left == right)
