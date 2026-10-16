"""Deterministic supervisor interleavings; subprocess substitutes never execute source."""

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest

from mastery_backend.infrastructure.runner import local_sandbox as module


@pytest.fixture
def controlled_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "verify_runtime", lambda path: ("image", "profile"))
    sandbox = module.LocalSandbox(tmp_path)
    stopped = []
    monkeypatch.setattr(sandbox, "_stop_unit", lambda unit: stopped.append(unit))
    process = Mock()
    process.stdin = io.BytesIO()
    process.stdout = Mock()
    process.stderr = io.BytesIO()
    process.poll.return_value = 0
    writes = []
    process.stdin = Mock(wraps=io.BytesIO())
    process.stdin.write.side_effect = lambda payload: writes.append(payload)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Mock(stdout=""))
    monkeypatch.setattr(sandbox, "verify_controls", lambda unit, child: None)
    return sandbox, process, writes, stopped


def test_prelaunch_cancel_is_latched_and_never_starts_process(controlled_sandbox, monkeypatch):
    sandbox, _, writes, stopped = controlled_sandbox
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: pytest.fail("launched"))
    sandbox.cancel()
    for _ in range(2):
        with pytest.raises(RuntimeError, match="cancelled"):
            sandbox.execute("source as data", "solve", [])
    assert not writes and not stopped and sandbox.active_unit is None


@pytest.mark.parametrize("invalid_controls", [False, True])
def test_cancel_during_validation_does_not_hide_bad_controls(
    controlled_sandbox, monkeypatch, invalid_controls
):
    sandbox, _, writes, stopped = controlled_sandbox

    def validate(unit, process):
        sandbox.cancel()
        assert not stopped  # Never kill a validation in progress to manufacture its failure.
        if invalid_controls:
            raise RuntimeError("Required cgroup controls are missing")

    monkeypatch.setattr(sandbox, "verify_controls", validate)
    monkeypatch.setattr(sandbox, "wait_for_ready", lambda child: pytest.fail("handshake"))
    expected = "cgroup controls" if invalid_controls else "cancelled"
    with pytest.raises(RuntimeError, match=expected):
        sandbox.execute("source as data", "solve", [])
    assert not writes and stopped and sandbox.active_unit is None


@pytest.mark.parametrize("readable", [False, True])
def test_cancel_wakes_handshake_without_sending_source(controlled_sandbox, monkeypatch, readable):
    sandbox, _, writes, stopped = controlled_sandbox
    waiting, release = Event(), Event()
    selector = Mock()
    selector.__enter__ = Mock(return_value=selector)
    selector.__exit__ = Mock(return_value=False)

    def select(timeout):
        waiting.set()
        assert release.wait(3)
        return [object()] if readable else []

    selector.select.side_effect = select
    monkeypatch.setattr(module.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(module.os, "read", lambda descriptor, size: b"")
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(sandbox.execute, "source as data", "solve", [])
        try:
            assert waiting.wait(3)
            sandbox.cancel()
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="cancelled"):
            result.result(timeout=5)
    assert not writes and stopped and sandbox.active_unit is None


@pytest.mark.parametrize("frame", [None, b"", b"BAD\n"])
def test_genuine_bootstrap_failure_survives_later_cancel(controlled_sandbox, monkeypatch, frame):
    sandbox, _, writes, stopped = controlled_sandbox
    selector = Mock()
    selector.__enter__ = Mock(return_value=selector)
    selector.__exit__ = Mock(return_value=False)
    selector.select.return_value = [] if frame is None else [object()]
    monkeypatch.setattr(module.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(module.os, "read", lambda descriptor, size: frame)
    with pytest.raises(RuntimeError, match="bootstrap is unavailable") as failure:
        sandbox.execute("source as data", "solve", [])
    sandbox.cancel()
    assert "cancelled" not in str(failure.value)
    assert not writes and stopped and sandbox.active_unit is None


def test_cancel_after_ready_prevents_source_write(controlled_sandbox, monkeypatch):
    sandbox, _, writes, _ = controlled_sandbox
    monkeypatch.setattr(sandbox, "wait_for_ready", lambda child: sandbox.cancel())
    with pytest.raises(RuntimeError, match="cancelled"):
        sandbox.execute("source as data", "solve", [])
    assert not writes and sandbox.active_unit is None


def test_cleanup_does_not_create_external_cancellation(controlled_sandbox, monkeypatch):
    sandbox, process, writes, _ = controlled_sandbox
    monkeypatch.setattr(sandbox, "wait_for_ready", lambda child: None)
    selector = Mock()
    selector.__enter__ = Mock(return_value=selector)
    selector.__exit__ = Mock(return_value=False)
    selector.get_map.return_value = {}
    monkeypatch.setattr(module.selectors, "DefaultSelector", lambda: selector)
    process.wait.return_value = 65
    assert sandbox.execute("source as data", "solve", []).category == "syntax_error"
    assert writes and not sandbox.cancelled
    assert sandbox.active_unit is None


def test_malformed_frame_is_not_relabelled_by_reentrant_cancel(controlled_sandbox, monkeypatch):
    sandbox, _, writes, _ = controlled_sandbox
    selector = Mock()
    selector.__enter__ = Mock(return_value=selector)
    selector.__exit__ = Mock(return_value=False)
    selector.select.return_value = [object()]
    monkeypatch.setattr(module.selectors, "DefaultSelector", lambda: selector)

    def read(descriptor, size):
        sandbox.cancel()
        return b"BAD\n"

    monkeypatch.setattr(module.os, "read", read)
    with pytest.raises(RuntimeError, match="bootstrap is unavailable"):
        sandbox.execute("source as data", "solve", [])
    assert not writes


@pytest.mark.parametrize("cancel", [False, True])
def test_broken_pipe_remains_failure_without_explicit_cancel(controlled_sandbox, cancel):
    sandbox, process, _, _ = controlled_sandbox

    def write(payload):
        if cancel:
            sandbox.cancel()  # Models the worker's same-thread signal callback during a write.
        raise BrokenPipeError("genuine closed pipe")

    process.stdin.write.side_effect = write
    expected = RuntimeError if cancel else BrokenPipeError
    with pytest.raises(expected, match="cancelled" if cancel else "closed pipe"):
        sandbox.send_payload(process, b"source as data")
