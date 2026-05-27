"""Tests for LoadTask — async-style load ViewModel with injectable execution (Task 4.1).

Strict TDD: tests written before implementation.

Coverage:
- Initial state: state="idle", result_key=None, error_message=None
- run with successful callable: idle→loading→done transitions; result_key set
- run with raising callable: state="error", error_message captured, no exception propagates
- Notifications are fired at each state transition (loading, then done/error)
- inspect() reflects current state
- Real Session.load with temp CSV is used for at least one success case (no mocks)
"""

from __future__ import annotations

import csv
from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.load_task import LoadTask

# ─── Helpers ────────────────────────────────────────────────────────────────


def _csv_format() -> FormatDefinition:
    return FormatDefinition(
        name="t1",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )


def _write_csv(path: Path) -> Path:
    """Write a minimal 2-row CSV and return the path."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "speed"])
        writer.writerow(["0.0", "10.0"])
        writer.writerow(["1.0", "20.0"])
    return path


# ─── Initial state ───────────────────────────────────────────────────────────


def test_initial_state_is_idle() -> None:
    task = LoadTask()
    assert task.state == "idle"


def test_initial_result_key_is_none() -> None:
    task = LoadTask()
    assert task.result_key is None


def test_initial_error_message_is_none() -> None:
    task = LoadTask()
    assert task.error_message is None


# ─── run — success path ──────────────────────────────────────────────────────


def test_run_success_sets_state_to_done() -> None:
    task = LoadTask()
    task.run(lambda: "my_key")
    assert task.state == "done"


def test_run_success_stores_result_key() -> None:
    task = LoadTask()
    task.run(lambda: "csv_1")
    assert task.result_key == "csv_1"


def test_run_success_error_message_remains_none() -> None:
    task = LoadTask()
    task.run(lambda: "csv_1")
    assert task.error_message is None


def test_run_notifies_loading_then_done() -> None:
    task = LoadTask()
    changes: list[str] = []
    task.subscribe(changes.append)
    task.run(lambda: "key")
    assert "loading" in changes
    assert "done" in changes
    # loading must come before done
    assert changes.index("loading") < changes.index("done")


# ─── run — error path ────────────────────────────────────────────────────────


def test_run_error_sets_state_to_error() -> None:
    task = LoadTask()

    def bad() -> str:
        raise RuntimeError("file not found")

    task.run(bad)
    assert task.state == "error"


def test_run_error_captures_error_message() -> None:
    task = LoadTask()

    def bad() -> str:
        raise RuntimeError("file not found")

    task.run(bad)
    assert task.error_message == "file not found"


def test_run_error_result_key_remains_none() -> None:
    task = LoadTask()

    def bad() -> str:
        raise RuntimeError("fail")

    task.run(bad)
    assert task.result_key is None


def test_run_error_does_not_propagate_exception() -> None:
    task = LoadTask()

    def bad() -> str:
        raise ValueError("oops")

    # Must not raise — caller should continue normally
    task.run(bad)


def test_run_error_notifies_loading_then_error() -> None:
    task = LoadTask()
    changes: list[str] = []
    task.subscribe(changes.append)

    def bad() -> str:
        raise RuntimeError("fail")

    task.run(bad)
    assert "loading" in changes
    assert "error" in changes
    assert changes.index("loading") < changes.index("error")


# ─── Real Session integration (no mocks) ─────────────────────────────────────


def test_run_with_real_session_load(tmp_path: Path) -> None:
    csv_file = _write_csv(tmp_path / "data.csv")
    session = Session()
    fmt = _csv_format()
    task = LoadTask()

    task.run(lambda: session.load(csv_file, fmt))

    assert task.state == "done"
    assert task.result_key is not None
    assert task.error_message is None


def test_run_with_real_session_load_notifies_done(tmp_path: Path) -> None:
    csv_file = _write_csv(tmp_path / "data.csv")
    session = Session()
    fmt = _csv_format()
    task = LoadTask()
    changes: list[str] = []
    task.subscribe(changes.append)

    task.run(lambda: session.load(csv_file, fmt))

    assert "done" in changes


def test_run_with_missing_file_session_load_error(tmp_path: Path) -> None:
    session = Session()
    fmt = _csv_format()
    task = LoadTask()

    task.run(lambda: session.load(tmp_path / "missing.csv", fmt))

    assert task.state == "error"
    assert task.error_message is not None


# ─── inspect ─────────────────────────────────────────────────────────────────


def test_inspect_initial() -> None:
    task = LoadTask()
    info = task.inspect()
    assert info == {"state": "idle", "result_key": None, "error_message": None}


def test_inspect_after_success() -> None:
    task = LoadTask()
    task.run(lambda: "abc")
    info = task.inspect()
    assert info["state"] == "done"
    assert info["result_key"] == "abc"
    assert info["error_message"] is None


def test_inspect_after_error() -> None:
    task = LoadTask()

    def bad() -> str:
        raise RuntimeError("boom")

    task.run(bad)
    info = task.inspect()
    assert info["state"] == "error"
    assert info["result_key"] is None
    assert info["error_message"] == "boom"
