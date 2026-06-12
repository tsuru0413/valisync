"""Tests for AppViewModel (Task 1.2).

Tests verify:
- load a temp CSV records the group key in state
- a "loaded" notification fires when request_load succeeds
- signals() exposes the namespaced signal after load
- inspect() reflects current state (keys, active tab, data sources)
- add_data_source / remove_data_source update state and emit notifications
"""

from __future__ import annotations

from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel

# ─── Helpers ────────────────────────────────────────────────────────────────


def _csv_format() -> FormatDefinition:
    return FormatDefinition(
        name="test_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )


def _write_csv(path: Path) -> Path:
    """Write a minimal valid CSV and return its path."""
    path.write_text("t,speed\n0.0,10.0\n1.0,20.0\n2.0,30.0\n")
    return path


# ─── Tests ──────────────────────────────────────────────────────────────────


def test_request_load_records_key(tmp_path: Path) -> None:
    """request_load returns the group key and adds it to loaded_file_keys."""
    vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")

    key = vm.request_load(csv_file, _csv_format())

    assert key in vm.inspect()["loaded_keys"]


def test_request_load_fires_loaded_notification(tmp_path: Path) -> None:
    """request_load calls _notify('loaded') after a successful load."""
    vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.request_load(csv_file, _csv_format())

    assert "loaded" in notifications


def test_signals_exposes_namespaced_signal_after_load(tmp_path: Path) -> None:
    """signals() returns a Signal with a namespaced name after load."""
    vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")

    key = vm.request_load(csv_file, _csv_format())

    names = [s.name for s in vm.signals()]
    assert any(name.startswith(f"{key}::") for name in names)


def test_inspect_reflects_initial_state() -> None:
    """inspect() snapshot matches the default initial state."""
    vm = AppViewModel()

    state = vm.inspect()

    assert state["loaded_keys"] == []
    assert state["active_tab"] == 0
    assert state["data_sources"] == []


def test_inspect_reflects_state_after_load(tmp_path: Path) -> None:
    """inspect() includes the new key and preserves other fields after load."""
    vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")

    key = vm.request_load(csv_file, _csv_format())
    state = vm.inspect()

    assert key in state["loaded_keys"]
    assert state["active_tab"] == 0


def test_add_data_source_updates_state_and_notifies(tmp_path: Path) -> None:
    """add_data_source appends the path and fires 'data_sources' notification."""
    vm = AppViewModel()
    notifications: list[str] = []
    vm.subscribe(notifications.append)
    folder = tmp_path / "logs"

    vm.add_data_source(folder)

    assert str(folder) in vm.inspect()["data_sources"]
    assert "data_sources" in notifications


def test_remove_data_source_updates_state_and_notifies(tmp_path: Path) -> None:
    """remove_data_source removes the path and fires 'data_sources' notification."""
    vm = AppViewModel()
    folder = tmp_path / "logs"
    vm.add_data_source(folder)
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.remove_data_source(folder)

    assert str(folder) not in vm.inspect()["data_sources"]
    assert "data_sources" in notifications


def test_remove_nonexistent_data_source_is_noop(tmp_path: Path) -> None:
    """Removing a path not in the list does not raise and still notifies."""
    vm = AppViewModel()
    notifications: list[str] = []
    vm.subscribe(notifications.append)
    ghost = tmp_path / "ghost"

    vm.remove_data_source(ghost)  # must not raise

    assert "data_sources" in notifications


def test_active_file_state_updates_and_notifies() -> None:
    """set_active_file updates the state and fires 'active_file' notification."""
    vm = AppViewModel()
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    assert vm.active_file_key is None
    assert vm.inspect()["active_file"] is None

    test_key = "some/file/path.mf4"
    vm.set_active_file(test_key)

    assert vm.active_file_key == test_key
    assert vm.inspect()["active_file"] == test_key
    assert "active_file" in notifications


def test_loaded_file_keys_exposes_list(tmp_path: Path) -> None:
    """loaded_file_keys property returns the list of group keys."""
    vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")

    key = vm.request_load(csv_file, _csv_format())

    assert vm.loaded_file_keys == [key]
