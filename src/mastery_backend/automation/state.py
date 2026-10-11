"""Validated plan/state, durable file replacement and one cross-process run lock."""

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Unit(StrictRecord):
    id: str = Field(pattern=r"^(S[0-9]{3}[a-z]?|AUTO[0-9]{3})$")
    dependencies: list[str] = Field(default_factory=list)
    status: Literal["ready", "planned", "running", "pending_ci", "blocked", "verified"]
    profile: Literal["baseline", "isolation"] = "baseline"
    attempts: int = Field(default=0, ge=0, le=2)
    reason: str | None = None
    commit: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    ci_url: str | None = None


class SprintState(StrictRecord):
    version: Literal[1] = 1
    units: list[Unit]
    sessions: dict[str, str] = Field(default_factory=dict)
    daily_attempts: dict[str, int] = Field(default_factory=dict)
    phase: str = "idle"
    active_unit: str | None = None
    starting_commit: str | None = None

    @model_validator(mode="after")
    def validate_graph(self) -> "SprintState":
        ids = {unit.id for unit in self.units}
        if len(ids) != len(self.units):
            raise ValueError("Duplicate sprint IDs")
        done: set[str] = set()
        while len(done) < len(ids):
            added = {
                unit.id
                for unit in self.units
                if unit.id not in done and set(unit.dependencies) <= done
            }
            if not added:
                raise ValueError("Missing dependencies or dependency cycle")
            done.update(added)
        if any(not 0 <= count <= 3 for count in self.daily_attempts.values()):
            raise ValueError("Daily attempt count exceeds policy")
        return self


def atomic_write(path: Path, value: BaseModel | dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".state-")
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(data, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def run_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    with path.open("a") as descriptor:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another controller operation holds the run lock") from None
        yield


def select_unit(state: SprintState, retry: str | None = None) -> Unit | None:
    verified = {unit.id for unit in state.units if unit.status == "verified"}
    for unit in state.units:
        eligible = (
            unit.status == "ready"
            if retry is None
            else (unit.id == retry and unit.status == "blocked" and unit.attempts < 2)
        )
        if eligible and set(unit.dependencies) <= verified and unit.attempts < 2:
            return unit
    return None


def reserve(state: SprintState, unit: Unit, now: datetime, slot: str) -> str:
    day = now.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
    session = day + ":" + slot
    if session in state.sessions:
        raise RuntimeError("Scheduled session already consumed")
    if state.daily_attempts.get(day, 0) >= 3:
        raise RuntimeError("Three daily unit attempts already consumed")
    if unit.status not in {"ready", "blocked"} or unit.attempts >= 2:
        raise RuntimeError("Unit is not eligible for a bounded attempt")
    state.daily_attempts[day] = state.daily_attempts.get(day, 0) + 1
    state.sessions[session] = unit.id
    unit.status, unit.reason = "running", None
    unit.attempts += 1
    state.active_unit, state.phase = unit.id, "reserved"
    return session
