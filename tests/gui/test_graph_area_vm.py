"""Tests for GraphAreaVM — tabbed container ViewModel (Task 3.2).

Strict TDD: tests written before implementation.

Coverage:
- Initial state: one tab named "Tab 1" with one empty GraphPanelVM, active_tab_index=0
- add_tab: creates tab, auto-names "Tab N" if None, makes it active, returns index
- remove_tab: rejects when only one tab remains (ValueError, R5.6)
- remove_tab: adjusts active index sensibly
- rename_tab: rejects empty string and >32 chars (ValueError, R5.4)
- rename_tab: accepts valid name 1..32 chars
- set_active_tab: changes active_tab_index
- add_panel: appends a new GraphPanelVM to the tab, returns new panel index
- add_panel: rejects when tab already has 8 panels (ValueError, R6.5)
- remove_panel: rejects when tab has only one panel (ValueError, R6.6)
- set_x_sync: toggles x_sync_enabled flag on the tab
- propagate_x_range: with sync ON calls set_x_range on every panel in the tab
- propagate_x_range: with sync OFF leaves panels unchanged
- inspect: returns snapshot dict reflecting current state
- subscribe notifications are fired on mutations
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

# ─── Helpers ────────────────────────────────────────────────────────────────


def _make_session() -> Session:
    return Session()


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


def test_initial_state_has_one_tab(tmp_path: Path) -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    tabs = vm.tabs()
    assert len(tabs) == 1


def test_initial_tab_named_tab1(tmp_path: Path) -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    assert vm.tabs()[0].name == "Tab 1"


def test_initial_active_tab_index_is_zero() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    assert vm.active_tab_index == 0


def test_initial_tab_has_one_panel() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    panels = vm.panels(0)
    assert len(panels) == 1
    assert isinstance(panels[0], GraphPanelVM)


# ─── add_tab ─────────────────────────────────────────────────────────────────


def test_add_tab_returns_index() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    idx = vm.add_tab()
    assert idx == 1


def test_add_tab_makes_new_tab_active() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab()
    assert vm.active_tab_index == 1


def test_add_tab_auto_names_tab2() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab()
    assert vm.tabs()[1].name == "Tab 2"


def test_add_tab_auto_names_sequential() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab()
    vm.add_tab()
    assert vm.tabs()[2].name == "Tab 3"


def test_add_tab_with_explicit_name() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab(name="My Tab")
    assert vm.tabs()[1].name == "My Tab"


def test_add_tab_new_tab_has_one_panel() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab()
    panels = vm.panels(1)
    assert len(panels) == 1
    assert isinstance(panels[0], GraphPanelVM)


def test_add_tab_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.add_tab()
    assert len(changes) >= 1
    assert "tabs" in changes or any("tab" in c for c in changes)


# ─── remove_tab ──────────────────────────────────────────────────────────────


def test_remove_tab_rejects_when_only_one_tab() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    with pytest.raises(ValueError, match="last"):
        vm.remove_tab(0)


def test_remove_tab_removes_the_tab() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab(name="Second")
    vm.remove_tab(0)
    assert len(vm.tabs()) == 1
    assert vm.tabs()[0].name == "Second"


def test_remove_tab_adjusts_active_index_when_active_removed() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab()
    # active is 1, remove tab 1 → active should be 0
    vm.remove_tab(1)
    assert vm.active_tab_index == 0


def test_remove_tab_keeps_active_index_when_earlier_tab_removed() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab()
    vm.add_tab()
    # active=2, remove tab 0 → active shifts to 1
    vm.remove_tab(0)
    assert vm.active_tab_index == 1


def test_remove_tab_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab()
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.remove_tab(0)
    assert len(changes) >= 1


# ─── rename_tab ──────────────────────────────────────────────────────────────


def test_rename_tab_rejects_empty_string() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    with pytest.raises(ValueError):
        vm.rename_tab(0, "")


def test_rename_tab_rejects_name_longer_than_32_chars() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    with pytest.raises(ValueError):
        vm.rename_tab(0, "x" * 33)


def test_rename_tab_accepts_name_of_32_chars() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.rename_tab(0, "x" * 32)
    assert vm.tabs()[0].name == "x" * 32


def test_rename_tab_accepts_name_of_1_char() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.rename_tab(0, "A")
    assert vm.tabs()[0].name == "A"


def test_rename_tab_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.rename_tab(0, "NewName")
    assert len(changes) >= 1


# ─── set_active_tab ──────────────────────────────────────────────────────────


def test_set_active_tab_changes_active_index() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab()
    vm.set_active_tab(0)
    assert vm.active_tab_index == 0


def test_set_active_tab_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab()
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.set_active_tab(0)
    assert len(changes) >= 1


# ─── add_panel ───────────────────────────────────────────────────────────────


def test_add_panel_returns_new_panel_index() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    idx = vm.add_panel(0)
    assert idx == 1


def test_add_panel_appends_graphpanelvm() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_panel(0)
    panels = vm.panels(0)
    assert len(panels) == 2
    assert isinstance(panels[1], GraphPanelVM)


def test_add_panel_rejects_when_8_panels_exist() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    for _ in range(7):
        vm.add_panel(0)
    # now 8 panels — next one must be rejected
    with pytest.raises(ValueError, match="8"):
        vm.add_panel(0)


def test_add_panel_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.add_panel(0)
    assert len(changes) >= 1


# ─── remove_panel ────────────────────────────────────────────────────────────


def test_remove_panel_rejects_last_panel() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    with pytest.raises(ValueError, match="last"):
        vm.remove_panel(0, 0)


def test_remove_panel_removes_the_panel() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_panel(0)
    vm.remove_panel(0, 0)
    assert len(vm.panels(0)) == 1


def test_remove_panel_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_panel(0)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.remove_panel(0, 0)
    assert len(changes) >= 1


# ─── set_x_sync ──────────────────────────────────────────────────────────────


def test_set_x_sync_default_is_true() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    tab = vm.tabs()[0]
    assert tab.x_sync_enabled is True


def test_set_x_sync_disables() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.set_x_sync(0, False)
    assert vm.tabs()[0].x_sync_enabled is False


def test_set_x_sync_re_enables() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.set_x_sync(0, False)
    vm.set_x_sync(0, True)
    assert vm.tabs()[0].x_sync_enabled is True


def test_set_x_sync_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.set_x_sync(0, False)
    assert len(changes) >= 1


# ─── propagate_x_range ───────────────────────────────────────────────────────


def test_propagate_x_range_with_sync_on_sets_all_panels() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_panel(0)  # now 2 panels
    vm.set_x_sync(0, True)
    vm.propagate_x_range(0, 1.0, 5.0)
    for panel in vm.panels(0):
        assert panel.x_range == (1.0, 5.0)


def test_propagate_x_range_with_sync_off_leaves_panels_unchanged() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_panel(0)  # now 2 panels
    vm.set_x_sync(0, False)
    vm.propagate_x_range(0, 1.0, 5.0)
    for panel in vm.panels(0):
        assert panel.x_range is None


def test_propagate_x_range_does_not_affect_other_tabs() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab()
    vm.set_x_sync(0, True)
    vm.propagate_x_range(0, 1.0, 5.0)
    # tab 1 panels should be unaffected
    for panel in vm.panels(1):
        assert panel.x_range is None


# ─── active_tab accessor ─────────────────────────────────────────────────────


def test_active_tab_returns_current_tab() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab(name="Second")
    vm.set_active_tab(1)
    assert vm.active_tab().name == "Second"


# ─── inspect ─────────────────────────────────────────────────────────────────


def test_inspect_initial_state() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    info = vm.inspect()
    assert info["active_tab_index"] == 0
    assert len(info["tabs"]) == 1
    tab_info = info["tabs"][0]
    assert tab_info["name"] == "Tab 1"
    assert tab_info["panel_count"] == 1
    assert tab_info["x_sync_enabled"] is True


def test_inspect_reflects_added_tab() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_tab(name="Second")
    info = vm.inspect()
    assert len(info["tabs"]) == 2
    assert info["tabs"][1]["name"] == "Second"
    assert info["active_tab_index"] == 1


def test_inspect_reflects_panel_count() -> None:
    session = _make_session()
    vm = GraphAreaVM(session)
    vm.add_panel(0)
    info = vm.inspect()
    assert info["tabs"][0]["panel_count"] == 2
