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
- active_panel_index: per-tab active panel tracking (PC-07 foundation),
  auto-activation on add_panel, clamping on remove_panel
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from valisync.core.models import Delimiter, FormatDefinition, Signal
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
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
    vm = GraphAreaVM(AppViewModel(session))
    tabs = vm.tabs()
    assert len(tabs) == 1


def test_initial_tab_named_tab1(tmp_path: Path) -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    assert vm.tabs()[0].name == "Tab 1"


def test_initial_active_tab_index_is_zero() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    assert vm.active_tab_index == 0


def test_initial_tab_has_one_panel() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    panels = vm.panels(0)
    assert len(panels) == 1
    assert isinstance(panels[0], GraphPanelVM)


# ─── add_tab ─────────────────────────────────────────────────────────────────


def test_add_tab_returns_index() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    idx = vm.add_tab()
    assert idx == 1


def test_add_tab_makes_new_tab_active() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()
    assert vm.active_tab_index == 1


def test_add_tab_auto_names_tab2() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()
    assert vm.tabs()[1].name == "Tab 2"


def test_add_tab_auto_names_sequential() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()
    vm.add_tab()
    assert vm.tabs()[2].name == "Tab 3"


def test_add_tab_with_explicit_name() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab(name="My Tab")
    assert vm.tabs()[1].name == "My Tab"


def test_add_tab_new_tab_has_one_panel() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()
    panels = vm.panels(1)
    assert len(panels) == 1
    assert isinstance(panels[0], GraphPanelVM)


def test_add_tab_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.add_tab()
    assert len(changes) >= 1
    assert "tabs" in changes or any("tab" in c for c in changes)


# ─── remove_tab ──────────────────────────────────────────────────────────────


def test_remove_tab_rejects_when_only_one_tab() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    with pytest.raises(ValueError, match="last"):
        vm.remove_tab(0)


def test_remove_tab_removes_the_tab() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab(name="Second")
    vm.remove_tab(0)
    assert len(vm.tabs()) == 1
    assert vm.tabs()[0].name == "Second"


def test_remove_tab_adjusts_active_index_when_active_removed() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()
    # active is 1, remove tab 1 → active should be 0
    vm.remove_tab(1)
    assert vm.active_tab_index == 0


def test_remove_tab_keeps_active_index_when_earlier_tab_removed() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()
    vm.add_tab()
    # active=2, remove tab 0 → active shifts to 1
    vm.remove_tab(0)
    assert vm.active_tab_index == 1


def test_remove_tab_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.remove_tab(0)
    assert len(changes) >= 1


# ─── rename_tab ──────────────────────────────────────────────────────────────


def test_rename_tab_rejects_empty_string() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    with pytest.raises(ValueError):
        vm.rename_tab(0, "")


def test_rename_tab_rejects_name_longer_than_32_chars() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    with pytest.raises(ValueError):
        vm.rename_tab(0, "x" * 33)


def test_rename_tab_accepts_name_of_32_chars() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.rename_tab(0, "x" * 32)
    assert vm.tabs()[0].name == "x" * 32


def test_rename_tab_accepts_name_of_1_char() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.rename_tab(0, "A")
    assert vm.tabs()[0].name == "A"


def test_rename_tab_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.rename_tab(0, "NewName")
    assert len(changes) >= 1


# ─── set_active_tab ──────────────────────────────────────────────────────────


def test_set_active_tab_changes_active_index() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()
    vm.set_active_tab(0)
    assert vm.active_tab_index == 0


def test_set_active_tab_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.set_active_tab(0)
    assert len(changes) >= 1


# ─── add_panel ───────────────────────────────────────────────────────────────


def test_add_panel_returns_new_panel_index() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    idx = vm.add_panel(0)
    assert idx == 1


def test_add_panel_appends_graphpanelvm() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_panel(0)
    panels = vm.panels(0)
    assert len(panels) == 2
    assert isinstance(panels[1], GraphPanelVM)


def test_add_panel_rejects_when_8_panels_exist() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    for _ in range(7):
        vm.add_panel(0)
    # now 8 panels — next one must be rejected
    with pytest.raises(ValueError, match="8"):
        vm.add_panel(0)


def test_add_panel_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.add_panel(0)
    assert len(changes) >= 1


def test_add_panel_emits_only_panels_not_active_panel() -> None:
    # PC-07 invariant: add_panel auto-activates the new panel, but the "panels"
    # rebuild already re-applies the active frame, so it must NOT also emit
    # "active_panel" (that would trigger the lightweight active_panel path on
    # top of a full rebuild). Guards against over-notification the >= 1 check
    # above cannot catch.
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.add_panel(0)
    assert changes == ["panels"]


# ─── remove_panel ────────────────────────────────────────────────────────────


def test_remove_panel_rejects_last_panel() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    with pytest.raises(ValueError, match="last"):
        vm.remove_panel(0, 0)


def test_remove_panel_removes_the_panel() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_panel(0)
    vm.remove_panel(0, 0)
    assert len(vm.panels(0)) == 1


def test_remove_panel_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_panel(0)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.remove_panel(0, 0)
    assert len(changes) >= 1


# ─── set_x_sync ──────────────────────────────────────────────────────────────


def test_set_x_sync_default_is_true() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    tab = vm.tabs()[0]
    assert tab.x_sync_enabled is True


def test_set_x_sync_disables() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.set_x_sync(0, False)
    assert vm.tabs()[0].x_sync_enabled is False


def test_set_x_sync_re_enables() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.set_x_sync(0, False)
    vm.set_x_sync(0, True)
    assert vm.tabs()[0].x_sync_enabled is True


def test_set_x_sync_notifies_subscribers() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.set_x_sync(0, False)
    assert len(changes) >= 1


# ─── propagate_x_range ───────────────────────────────────────────────────────


def test_propagate_x_range_with_sync_on_sets_all_panels() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_panel(0)  # now 2 panels
    vm.set_x_sync(0, True)
    vm.propagate_x_range(0, 1.0, 5.0)
    for panel in vm.panels(0):
        assert panel.x_range == (1.0, 5.0)


def test_propagate_x_range_with_sync_off_leaves_panels_unchanged() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_panel(0)  # now 2 panels
    vm.set_x_sync(0, False)
    vm.propagate_x_range(0, 1.0, 5.0)
    for panel in vm.panels(0):
        assert panel.x_range is None


def test_propagate_x_range_does_not_affect_other_tabs() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()
    vm.set_x_sync(0, True)
    vm.propagate_x_range(0, 1.0, 5.0)
    # tab 1 panels should be unaffected
    for panel in vm.panels(1):
        assert panel.x_range is None


# ─── auto X-sync: a panel's range change drives its siblings (R7.1/R7.2) ────────


def test_panel_range_change_propagates_when_sync_on() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_panel(0)  # 2 panels
    vm.set_x_sync(0, True)
    p0, p1 = vm.panels(0)

    p0.set_x_range(2.0, 4.0)  # a zoom on one panel

    assert p1.x_range == (2.0, 4.0)


def test_panel_range_change_independent_when_sync_off() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_panel(0)
    vm.set_x_sync(0, False)
    p0, p1 = vm.panels(0)

    p0.set_x_range(2.0, 4.0)

    assert p1.x_range is None


def test_panel_range_change_does_not_cross_tabs() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab()  # tab 1
    vm.set_x_sync(0, True)
    vm.set_x_sync(1, True)
    p_tab0 = vm.panels(0)[0]
    p_tab1 = vm.panels(1)[0]

    p_tab0.set_x_range(2.0, 4.0)

    assert p_tab1.x_range is None


def test_newly_added_panel_participates_in_sync() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.set_x_sync(0, True)
    p0 = vm.panels(0)[0]
    vm.add_panel(0)  # subscribe the new panel
    p1 = vm.panels(0)[1]

    p0.set_x_range(3.0, 7.0)

    assert p1.x_range == (3.0, 7.0)


def test_sync_does_not_recurse_infinitely() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_panel(0)
    vm.set_x_sync(0, True)
    p0, p1 = vm.panels(0)

    # Must terminate (no RecursionError) and both end on the same range.
    p0.set_x_range(1.0, 2.0)

    assert p0.x_range == (1.0, 2.0)
    assert p1.x_range == (1.0, 2.0)


# ─── active_tab accessor ─────────────────────────────────────────────────────


def test_active_tab_returns_current_tab() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab(name="Second")
    vm.set_active_tab(1)
    assert vm.active_tab().name == "Second"


# ─── inspect ─────────────────────────────────────────────────────────────────


def test_inspect_initial_state() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    info = vm.inspect()
    assert info["active_tab_index"] == 0
    assert len(info["tabs"]) == 1
    tab_info = info["tabs"][0]
    assert tab_info["name"] == "Tab 1"
    assert tab_info["panel_count"] == 1
    assert tab_info["x_sync_enabled"] is True


def test_inspect_reflects_added_tab() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_tab(name="Second")
    info = vm.inspect()
    assert len(info["tabs"]) == 2
    assert info["tabs"][1]["name"] == "Second"
    assert info["active_tab_index"] == 1


def test_inspect_reflects_panel_count() -> None:
    session = _make_session()
    vm = GraphAreaVM(AppViewModel(session))
    vm.add_panel(0)
    info = vm.inspect()
    assert info["tabs"][0]["panel_count"] == 2


def test_graph_area_prunes_panels_when_file_unloaded(tmp_path: Path) -> None:
    """GraphAreaVM subscribes to AppViewModel: unloading a file prunes its
    plotted signals from every panel (R7.4)."""
    app_vm = AppViewModel()
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    vm = GraphAreaVM(app_vm)
    panel = vm.panels(0)[0]
    panel.add_signal(f"{key}::speed")
    assert [p["signal_key"] for p in panel.inspect()["plotted_signals"]] == [
        f"{key}::speed"
    ]

    app_vm.unload_file(key)  # AppViewModel notifies "unloaded"; GraphAreaVM reacts

    assert [p["signal_key"] for p in panel.inspect()["plotted_signals"]] == []


def test_unload_prunes_every_panel_without_scanning_all_session_signals(
    tmp_path: Path,
) -> None:
    """FU-16: unloading a file must prune plotted signals in every panel via
    group-key membership, NEVER calling session.signals() (which forces a
    namespaced rebuild of all remaining signals at prod scale). Multiple
    panels must not multiply the scan. Sabotage-RED: reverting prune to
    `{s.name for s in session.signals()}` makes call-count == panel-count > 0.
    """
    app_vm = AppViewModel()
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    key2 = app_vm.request_load(_write_csv(tmp_path / "b.csv"), _csv_format())
    vm = GraphAreaVM(app_vm)
    vm.add_panel(0)  # tab 0 に 2 panel (NxP の乗数を exercise)
    for panel in vm.panels(0):
        panel.add_signal(f"{key}::speed")
        panel.add_signal(f"{key2}::speed")

    calls = 0
    real_signals = app_vm.session.signals

    def spy_signals() -> list[Signal]:
        nonlocal calls
        calls += 1
        return real_signals()

    app_vm.session.signals = spy_signals  # type: ignore[method-assign]

    app_vm.unload_file(key)  # unloaded broadcast → every panel prunes

    assert calls == 0, f"prune walked all session signals {calls} times"
    # 正当性: 消えたファイルの信号だけ落ち、生存ファイルの信号は残る
    for panel in vm.panels(0):
        keys = [p["signal_key"] for p in panel.inspect()["plotted_signals"]]
        assert keys == [f"{key2}::speed"]


# ─── active panel (PC-07: click-to-activate foundation) ─────────────────────


class TestActivePanel:
    def test_initial_active_panel_index_is_zero(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        assert vm.active_panel_index(0) == 0

    def test_set_active_panel_changes_index(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        vm.add_panel(0)
        vm.set_active_panel(0, 0)
        vm.set_active_panel(0, 1)
        assert vm.active_panel_index(0) == 1

    def test_set_active_panel_notifies_active_panel_tag(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        vm.add_panel(0)
        vm.set_active_panel(0, 0)
        changes: list[str] = []
        vm.subscribe(changes.append)
        vm.set_active_panel(0, 1)
        assert changes == ["active_panel"]

    def test_set_active_panel_same_index_does_not_notify(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        changes: list[str] = []
        vm.subscribe(changes.append)
        vm.set_active_panel(0, 0)
        assert changes == []

    def test_set_active_panel_out_of_range_is_noop(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        vm.set_active_panel(0, 5)
        assert vm.active_panel_index(0) == 0

    def test_add_panel_makes_new_panel_active(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        vm.add_panel(0)
        assert vm.active_panel_index(0) == 1

    def test_remove_panel_before_active_shifts_index(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        vm.add_panel(0)
        vm.add_panel(0)  # 3 panels, active=2
        vm.remove_panel(0, 0)
        assert vm.active_panel_index(0) == 1  # same panel, index shifted down

    def test_remove_active_last_panel_clamps(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        vm.add_panel(0)  # 2 panels, active=1
        vm.remove_panel(0, 1)
        assert vm.active_panel_index(0) == 0

    def test_active_panel_is_per_tab(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        vm.add_panel(0)  # tab0 active=1
        vm.add_tab()  # tab1 active=0
        assert vm.active_panel_index(0) == 1
        assert vm.active_panel_index(1) == 0

    def test_active_panel_returns_vm_of_active_tab(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        vm.add_panel(0)
        assert vm.active_panel() is vm.panels(0)[1]

    def test_active_panel_index_defaults_to_active_tab(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        vm.add_tab()
        vm.add_panel(1)
        assert vm.active_panel_index() == 1  # tab1 is active

    def test_inspect_includes_active_panel_index(self) -> None:
        session = _make_session()
        vm = GraphAreaVM(AppViewModel(session))
        assert vm.inspect()["tabs"][0]["active_panel_index"] == 0


# ─── Task 2: タブ注入 CursorState (spec §2.1) ────────────────────────────────


@pytest.fixture
def area_with_signals() -> GraphAreaVM:
    """タブ内共有 CursorState の検証専用 GraphAreaVM (信号データは不要)。"""
    return GraphAreaVM(AppViewModel(_make_session()))


def test_add_panel_preserves_tab_cursor_state(area_with_signals: GraphAreaVM) -> None:
    area = area_with_signals
    p0 = area.panels(0)[0]
    p0.set_cursor(3.0)
    p0.set_cursor_b(5.0)
    area.add_panel(0)
    p1 = area.panels(0)[1]
    # 巻き戻し禁止 (blocker): 既存値が不変で新パネルから同値が読める
    assert (p0.cursor_t, p0.cursor_t_b, p0.delta_enabled) == (3.0, 5.0, True)
    assert (p1.cursor_t, p1.cursor_t_b, p1.delta_enabled) == (3.0, 5.0, True)


def test_tabs_have_independent_cursor_state(area_with_signals: GraphAreaVM) -> None:
    area = area_with_signals
    area.add_tab()
    area.panels(0)[0].set_cursor(3.0)
    assert area.panels(1)[0].cursor_t is None


# ─── Task 5: クロスパネル軸移動の再計算+refit (spec §3.7) ─────────────────────


def _write_big_csv(path: Path) -> Path:
    """Write a 2-row CSV with a large-range signal (mirrors vm_with_two_scales's 'big')."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "big"])
        writer.writerow(["0.0", "800.0"])
        writer.writerow(["1.0", "2275.0"])
    return path


@pytest.fixture
def area_vm_two_panels_two_scales(
    tmp_path: Path,
) -> tuple[GraphAreaVM, GraphPanelVM, GraphPanelVM, str]:
    """GraphAreaVM: one tab, two panels sharing a session with a large-range
    signal loaded (mirrors vm_with_two_scales's 'big') so a cross-panel
    insert_axis auto-fit is observable. (area, src_vm, dst_vm, key_big)."""
    app_vm = AppViewModel()
    group_key = app_vm.request_load(
        _write_big_csv(tmp_path / "big.csv"),
        FormatDefinition(
            name="big",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    area = GraphAreaVM(app_vm)
    area.add_panel(0)
    src_vm, dst_vm = area.panels(0)[0], area.panels(0)[1]
    key_big = f"{group_key}::big"
    return area, src_vm, dst_vm, key_big


def test_cross_panel_insert_axis_recalcs_and_fits(
    area_vm_two_panels_two_scales: tuple[GraphAreaVM, GraphPanelVM, GraphPanelVM, str],
) -> None:
    # spec §3.7: YAxisVM はオブジェクトごと移送 (y_is_auto も運ばれる)。
    # auto 軸は挿入先で即フィット・手動軸は温存。
    _area, src_vm, dst_vm, key_big = area_vm_two_panels_two_scales
    src_vm.add_signal(key_big)
    extracted = src_vm.extract_axis(0)
    assert extracted is not None
    axis, entries = extracted
    dst_vm.insert_axis(axis, entries, column=dst_vm.column_count - 1, position=None)
    assert dst_vm.axes[-1].name == key_big.split("::")[-1]
    assert dst_vm.axes[-1].y_range is not None


def test_extract_axis_preserves_manual_range_of_sole_axis(
    area_vm_two_panels_two_scales: tuple[GraphAreaVM, GraphPanelVM, GraphPanelVM, str],
) -> None:
    # レビュー捕捉の回帰ガード: 抽出対象が源パネルの唯一の軸のとき、
    # _compact_axes の「全削除」placeholder 分岐 (keep = self._axes[0]) が
    # 抽出中の軸オブジェクトそのものを別名でミューテートし (y_range=None・
    # y_is_auto=True へリセット)、手動レンジが消える (spec §3.7 手動温存の破れ)。
    # 挿入先でも手動値のまま (フィットされない) ことまで確認する。
    _area, src_vm, dst_vm, key_big = area_vm_two_panels_two_scales
    src_vm.add_signal(key_big)
    src_vm.set_axis_range(0, 1000.0, 2000.0)  # 手動化 (y_is_auto=False)
    extracted = src_vm.extract_axis(0)
    assert extracted is not None
    axis, entries = extracted
    assert axis.y_is_auto is False  # 現行は True (別名ミューテートで自動化) で fail
    assert axis.y_range == (1000.0, 2000.0)  # 現行は None で fail
    dst_vm.insert_axis(axis, entries, column=dst_vm.column_count - 1, position=None)
    assert dst_vm.axes[-1].y_is_auto is False
    assert dst_vm.axes[-1].y_range == (1000.0, 2000.0)  # 挿入先でもフィットされず温存
