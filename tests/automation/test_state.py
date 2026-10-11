import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from mastery_backend.automation.state import (
    SprintState,
    Unit,
    atomic_write,
    reserve,
    run_lock,
    select_unit,
)


def test_selection_blocks_dependents_and_bounds_retry():
    state = SprintState(
        units=[
            Unit(id="S001", status="blocked"),
            Unit(id="S002", status="ready", dependencies=["S001"]),
        ]
    )
    assert select_unit(state) is None
    assert select_unit(state, "S001") is state.units[0]
    state.units[0].attempts = 2
    assert select_unit(state, "S001") is None
    state.units[0].status = "verified"
    assert select_unit(state) is state.units[1]


@pytest.mark.parametrize("dependencies", [["S001"], ["S999"]])
def test_bad_graph_rejected(dependencies):
    with pytest.raises(ValidationError):
        SprintState(units=[Unit(id="S001", status="ready", dependencies=dependencies)])


def test_shared_daily_budget_duplicates_and_india_date():
    state = SprintState(units=[Unit(id=f"S00{i}", status="ready") for i in range(1, 5)])
    now = datetime(2026, 10, 11, 20, tzinfo=UTC)
    reserve(state, state.units[0], now, "09")
    assert state.sessions == {"2026-10-12:09": "S001"}
    with pytest.raises(RuntimeError, match="already consumed"):
        reserve(state, state.units[1], now, "09")
    reserve(state, state.units[1], now, "batch-14-0")
    reserve(state, state.units[2], now, "19")
    with pytest.raises(RuntimeError, match="Three daily"):
        reserve(state, state.units[3], now, "batch-19-1")
    assert state.units[3].attempts == 0


def test_atomic_replacement_and_cross_instance_lock(tmp_path: Path):
    path = tmp_path / "state.json"
    atomic_write(path, {"phase": "agent"})
    atomic_write(path, {"phase": "pending_ci"})
    assert json.loads(path.read_text()) == {"phase": "pending_ci"}
    assert path.stat().st_mode & 0o777 == 0o600
    with run_lock(tmp_path / "lock"):
        with pytest.raises(RuntimeError, match="Another controller"):
            with run_lock(tmp_path / "lock"):
                pytest.fail("Overlapping run acquired lock")
    with run_lock(tmp_path / "lock"):
        pass
