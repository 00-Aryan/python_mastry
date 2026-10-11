"""Bounded fixed-argument processes; metadata logs never contain process output."""

import os
import selectors
import signal
import subprocess
import time
from pathlib import Path


def execute(
    arguments: list[str],
    directory: Path,
    *,
    timeout_seconds: int = 1800,
    input_text: str | None = None,
    environment: dict[str, str] | None = None,
) -> str:
    process = subprocess.Popen(
        arguments,
        cwd=directory,
        env=environment,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    output = bytearray()
    deadline = time.monotonic() + timeout_seconds
    try:
        if process.stdin is not None:
            process.stdin.write((input_text or "").encode())
            process.stdin.close()
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Command timed out: {Path(arguments[0]).name}")
                if selector.select(timeout=0.1):
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > 2_000_000:
                        raise RuntimeError("Command output exceeded bounded protocol")
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        if process.returncode != 0:
            raise RuntimeError(f"Command failed ({process.returncode}): {Path(arguments[0]).name}")
        return output.decode(errors="replace").strip()
    finally:
        # Includes descendants even when the command's parent has exited successfully.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        if process.stdout is not None:
            process.stdout.close()
