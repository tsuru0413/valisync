"""Tests for MainWindow — Task 6.1.

TDD: tests written first; all must FAIL before implementation exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.models.load_result import Diagnostic
from valisync.core.session import LoadError, LoadOutcome
from valisync.gui.viewmodels.app_viewmodel import AppViewModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_window(qtbot: QtBot) -> object:
    """Construct a MainWindow and register it with qtbot."""
    from valisync.gui.views.main_window import MainWindow

    app_vm = AppViewModel()
    window = MainWindow(app_vm)
    qtbot.addWidget(window)
    return window


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


def _write_csv(dir_path: Path) -> Path:
    """Write a minimal valid CSV into *dir_path* and return its path."""
    csv_file = dir_path / "data.csv"
    csv_file.write_text("t,speed\n0.0,10.0\n1.0,20.0\n2.0,30.0\n")
    return csv_file


def _write_csv_named(dir_path: Path, name: str) -> Path:
    """Write a minimal valid CSV named *name* into *dir_path* (distinct basename)."""
    csv_file = dir_path / name
    csv_file.write_text("t,speed\n0.0,10.0\n1.0,20.0\n2.0,30.0\n")
    return csv_file


def _write_csv_nonmonotonic(dir_path: Path) -> Path:
    """Write a non-monotonic CSV (timestamps not strictly increasing)."""
    csv_file = dir_path / "nonmonotonic.csv"
    csv_file.write_text("t,speed\n0.0,10.0\n2.0,20.0\n1.0,30.0\n")
    return csv_file


# ---------------------------------------------------------------------------
# Dock existence and type
# ---------------------------------------------------------------------------


class TestDocksExist:
    def test_channel_dock_is_qdockwidget(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        assert isinstance(window.channel_dock, QDockWidget)  # type: ignore[union-attr]

    def test_bottom_right_corner_belongs_to_right_dock_area(self, qtbot: QtBot) -> None:
        """FU-10: the bottom-right corner is assigned to the Right dock area so the
        File/Channel Browser docks span the right column full-height (Diagnostics,
        in the bottom area, no longer extends under them). Qt's default assigns
        this corner to BottomDockWidgetArea, which shortens the right docks."""
        window = _make_window(qtbot)
        assert (
            window.corner(Qt.Corner.BottomRightCorner)  # type: ignore[union-attr]
            == Qt.DockWidgetArea.RightDockWidgetArea
        )

    def test_corner_survives_reset_layout(self, qtbot: QtBot) -> None:
        """FU-10 regression: restoreState resets dock corner config to Qt defaults,
        so SH-11 Reset Layout (which calls restoreState) must re-apply the corner.
        Without the re-apply the right docks silently revert to short (the same
        clobber that broke the startup restore for users with a saved windowState)."""
        window = _make_window(qtbot)
        window._reset_layout()  # type: ignore[union-attr]  # SH-11 -> restoreState
        assert (
            window.corner(Qt.Corner.BottomRightCorner)  # type: ignore[union-attr]
            == Qt.DockWidgetArea.RightDockWidgetArea
        )


# ---------------------------------------------------------------------------
# Central Widget
# ---------------------------------------------------------------------------


class TestCentralWidget:
    def test_graph_area_is_mounted_in_central_stack(self, qtbot: QtBot) -> None:
        """Central widget is a QStackedWidget (Welcome/GraphArea swap, Task 5);
        the real GraphAreaView must still be the workbench page (index 1)."""
        from valisync.gui.views.graph_area_view import GraphAreaView

        window = _make_window(qtbot)
        assert isinstance(window.graph_area_view, GraphAreaView)  # type: ignore[union-attr]
        assert window.central_stack.widget(1) is window.graph_area_view  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Dock feature flags: floatable + closable (R1.2 / R1.3)
# ---------------------------------------------------------------------------


class TestDockFeatures:
    def test_channel_dock_is_floatable(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        features = window.channel_dock.features()  # type: ignore[union-attr]
        assert features & QDockWidget.DockWidgetFeature.DockWidgetFloatable

    def test_channel_dock_is_closable(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        features = window.channel_dock.features()  # type: ignore[union-attr]
        assert features & QDockWidget.DockWidgetFeature.DockWidgetClosable


# ---------------------------------------------------------------------------
# Window title
# ---------------------------------------------------------------------------


class TestWindowTitle:
    def test_title_is_valisync(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        assert window.windowTitle() == "ValiSync"  # type: ignore[union-attr]

    def test_window_title_tracks_active_file(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        window = _make_window(qtbot)
        assert window.windowTitle() == "ValiSync"  # type: ignore[union-attr]
        key = window.app_vm.request_load(_write_csv(tmp_path), _csv_format())  # type: ignore[union-attr]
        window.app_vm.set_active_file(key)  # type: ignore[union-attr]
        assert window.windowTitle().endswith(" — ValiSync")  # type: ignore[union-attr]
        assert window.windowTitle().startswith("data.csv")  # type: ignore[union-attr]
        window.app_vm.set_active_file(None)  # type: ignore[union-attr]
        assert window.windowTitle() == "ValiSync"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Toggle-view action re-shows a closed dock (R1.4)
# ---------------------------------------------------------------------------


class TestDockToggleAction:
    def test_channel_dock_toggle_action_reshows_closed_dock(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        dock = window.channel_dock  # type: ignore[union-attr]
        assert not dock.isHidden()
        # Close the dock (sets hidden state to True)
        dock.close()
        assert dock.isHidden()
        # Trigger the toggle action to re-show
        action = dock.toggleViewAction()
        action.trigger()
        assert not dock.isHidden()


# ---------------------------------------------------------------------------
# Data Explorer toolbar action (R1.5)
# ---------------------------------------------------------------------------


class TestDataExplorerAction:
    def test_data_explorer_action_exists(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        assert hasattr(window, "action_data_explorer")

    def test_data_explorer_action_triggers_without_error(self, qtbot: QtBot) -> None:
        """open_data_explorer is a no-op placeholder; must not raise."""
        window = _make_window(qtbot)
        window.action_data_explorer.trigger()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Analyze menu (計測 IA 刷新 spec §2.2) -- AnalysisActions 共有・配線規約
# ---------------------------------------------------------------------------


def _analyze_menu(window: object):
    # submenu の生存は .menu() を呼んだ QAction ラッパの寿命に紐づく (shiboken) —
    # ラッパを保持しないと genexpr の一時変数が捨てられた時点で GC され、戻り値の
    # QMenu が "already deleted" になる (memory gui_pyside_qaction_submenu_shiboken_lifetime)。
    act = next(
        a
        for a in window.menuBar().actions()  # type: ignore[attr-defined]
        if a.text() == "&Analyze"
    )
    menu = act.menu()
    menu._keepalive = act  # type: ignore[attr-defined]
    return menu


class TestAnalyzeMenu:
    def test_menu_has_four_items_and_disabled_info_row(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        menu = _analyze_menu(window)
        texts = [a.text() for a in menu.actions()]
        assert "カーソル A" in texts
        assert "カーソル B（Δ）" in texts  # noqa: RUF001
        assert "カーソルを消す" in texts
        assert any(
            a.text() == "補間方式" and a.menu() is not None for a in menu.actions()
        )
        step = next(a for a in menu.actions() if a.text() == "← / → サンプルステップ")
        assert not step.isEnabled()

    def test_blank_menu_shares_same_qaction_as_analyze_menu(self, qtbot: QtBot) -> None:
        """空白右クリックメニューと Analyze メニューは同一 QAction を掲載する
        (checked/文言の乖離を構造防止 -- spec §2.2)。"""
        window = _make_window(qtbot)
        analyze_cursor_a = next(
            a for a in _analyze_menu(window).actions() if a.text() == "カーソル A"
        )
        panel_view = window.graph_area_view.tabs.widget(0).widget(0)  # type: ignore[union-attr]
        blank_cursor_a = next(
            a
            for a in panel_view.build_context_menu().actions()  # type: ignore[attr-defined]
            if a.text() == "カーソル A"
        )
        assert analyze_cursor_a is blank_cursor_a

    def test_about_to_show_sync_transition_does_not_fire_vm_handlers(
        self, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """誤発火ガード実質化 (レビュー指摘): 旧版はカーソル未設置パネルで検証して
        おり、sync は checked=False のまま無変化 (setChecked(False) は何もしない)
        だったため toggled 配線でも発火せず恒真だった。カーソル設置済みの状態で
        aboutToShow を発火させ、setChecked(False→True) の遷移が実際に起きること
        を確認した上でハンドラ非発火 (calls == []) と cursor_t 不変を検証する。
        sabotage (toggled 配線への変更) で RED になることを実装時に確認済み。"""
        window = _make_window(qtbot)
        pvm = window.graph_area_view.active_panel_vm()  # type: ignore[attr-defined]
        assert pvm is not None
        pvm.set_cursor(
            0.3
        )  # 既に設置済み。toggle_main_cursor(True) の既定中央と異なる値。
        cursor_a = window._analysis_actions.cursor_a  # type: ignore[attr-defined]
        assert cursor_a.isChecked() is False  # aboutToShow 前 (前提)

        calls: list[str] = []
        monkeypatch.setattr(
            pvm,
            "toggle_main_cursor",
            lambda *a, **k: calls.append("main"),
        )
        monkeypatch.setattr(
            pvm,
            "toggle_delta",
            lambda *a, **k: calls.append("delta"),
        )
        _analyze_menu(window).aboutToShow.emit()

        assert (
            cursor_a.isChecked() is True
        )  # 遷移が実際に起きたことの確認 (テストの前提)
        assert calls == []
        assert pvm.cursor_t == pytest.approx(0.3)  # setChecked だけでは変異しない

    def test_triggering_cursor_a_from_analyze_dispatches_to_active_panel(
        self, qtbot: QtBot
    ) -> None:
        """実際のメニュー表示は必ず aboutToShow → (ユーザー操作) trigger の順。
        aboutToShow で再ターゲットされて初めて trigger がアクティブパネルへ届く
        (spec §2.2 レビュー修正: 共有ターゲットは sync 時点まで None)。"""
        window = _make_window(qtbot)
        pvm = window.graph_area_view.active_panel_vm()  # type: ignore[attr-defined]
        assert pvm is not None
        pvm.x_range = (0.0, 1.0)
        menu = _analyze_menu(window)
        menu.aboutToShow.emit()
        cursor_a = next(a for a in menu.actions() if a.text() == "カーソル A")
        cursor_a.trigger()
        assert pvm.cursor_t == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# State persistence (R2.3)
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_dock_layout_roundtrips_across_instances(self, qtbot: QtBot) -> None:
        """Dock area survives saveState/restoreState across two MainWindow instances.

        Without setObjectName on each QDockWidget, restoreState silently no-ops
        (Qt can't map saved geometry back to unnamed widgets) — this test catches
        that false-green production bug.  QSettings isolation is provided by the
        conftest _isolate_qsettings autouse fixture.
        """
        from PySide6.QtCore import Qt

        from valisync.gui.views.main_window import MainWindow

        app_vm = AppViewModel()
        w1 = MainWindow(app_vm)
        qtbot.addWidget(w1)

        # Move file_dock to Left (default is Right); verify the move took effect.
        w1.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, w1.file_dock)
        assert w1.dockWidgetArea(w1.file_dock) == Qt.DockWidgetArea.LeftDockWidgetArea

        state = w1.saveState()

        # Second instance starts with default layout, then restores.
        w2 = MainWindow(app_vm)
        qtbot.addWidget(w2)
        ok = w2.restoreState(state)
        assert ok, "restoreState returned False"
        assert (
            w2.dockWidgetArea(w2.file_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
        ), "dock layout not restored — restoreState no-op (setObjectName missing?)"

    def test_save_state_runs_without_error(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        window.save_state()  # type: ignore[union-attr]

    def test_second_mainwindow_restore_does_not_crash(self, qtbot: QtBot) -> None:
        """After save_state, constructing a new MainWindow must not raise."""
        from valisync.gui.views.main_window import MainWindow

        app_vm = AppViewModel()
        w1 = MainWindow(app_vm)
        qtbot.addWidget(w1)
        w1.save_state()

        # Second construction exercises the restore path
        w2 = MainWindow(app_vm)
        qtbot.addWidget(w2)
        assert w2.windowTitle() == "ValiSync"

    def test_first_run_no_stored_state_does_not_crash(self, qtbot: QtBot) -> None:
        """First run with an empty settings store must not crash.

        The autouse _isolate_qsettings fixture provides a fresh per-test key,
        so no prior state is present for this test instance.
        """
        window = _make_window(qtbot)
        assert window is not None  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Dependency-injection overrides
# ---------------------------------------------------------------------------


class TestMountedViews:
    """MainWindow now builds and mounts the real views (Task 10 integration)."""

    def test_channel_dock_holds_channel_browser_view(self, qtbot: QtBot) -> None:
        from valisync.gui.views.channel_browser_view import ChannelBrowserView

        window = _make_window(qtbot)
        assert isinstance(window.channel_dock.widget(), ChannelBrowserView)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# State is persisted on window close (R2.3 — restore requires save-on-close)
# ---------------------------------------------------------------------------


class TestSaveOnClose:
    def test_close_event_persists_state(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        calls: list[int] = []
        # Spy on save_state to verify closeEvent wires through to it.
        original = window.save_state  # type: ignore[attr-defined]

        def _spy() -> None:
            calls.append(1)
            original()

        window.save_state = _spy  # type: ignore[attr-defined,method-assign]
        window.close()
        assert calls, "closeEvent must call save_state so geometry persists"


# ---------------------------------------------------------------------------
# Diagnostics dock + modal + status-bar wiring (FB-01/02/03/06)
# ---------------------------------------------------------------------------


def test_load_error_shows_dialog_and_records(qtbot, monkeypatch):
    window = _make_window(qtbot)
    calls = {}
    import valisync.gui.views.main_window as mw

    monkeypatch.setattr(
        mw.QMessageBox,
        "critical",
        lambda *a, **k: calls.setdefault("shown", a),
    )
    err = LoadError(Path("bad.mdf"), ["no loader supports file"])
    window._on_load_error(Path("bad.mdf"), err)
    assert "shown" in calls  # FB-01: modal shown
    assert window.diagnostics_vm.counts()[0] == 1  # 1 error recorded


def test_on_loaded_records_warnings_and_activates(qtbot, tmp_path):
    window = _make_window(qtbot)
    # Load a real CSV directly via the Session (no register_loaded) so a group
    # exists without the key already being tracked; _on_loaded below performs
    # the single registration, matching the production off-thread callback path.
    # (QSettings isolation is applied automatically by the autouse fixture in
    #  tests/gui/conftest.py — no import needed.)
    key = window.app_vm.session.load(_write_csv(tmp_path), _csv_format()).key
    outcome = LoadOutcome(
        key=key,
        diagnostics=(Diagnostic(level="warning", message="skip", signal_name="x"),),
    )
    window._on_loaded(outcome)
    assert window.app_vm.active_file_key == key  # FB-03
    assert window.diagnostics_vm.counts()[1] >= 1  # FB-02 warning recorded


def test_on_loaded_records_nonmonotonic_csv_warning(qtbot, tmp_path):
    """Task 7.1: Non-monotonic CSV end-to-end connection test.

    Verifies that:
    - A non-monotonic CSV (timestamps not strictly increasing) is loaded
      successfully via session.load()
    - The non-monotonic warning is issued by csv_loader and propagates
      through _on_loaded() to the diagnostics dock VM
    - The warning message contains '非単調' (non-monotonic)

    This is a Layer B integration test: exercises the full wiring from
    csv_loader diagnostics → LoadResult → _on_loaded() → diagnostics_vm.
    """
    window = _make_window(qtbot)
    # Load non-monotonic CSV directly via Session to create the group
    result = window.app_vm.session.load(
        _write_csv_nonmonotonic(tmp_path), _csv_format()
    )
    key = result.key
    # Wrap the result in a LoadOutcome (matching the callback path)
    outcome = LoadOutcome(key=key, diagnostics=result.diagnostics)
    window._on_loaded(outcome)

    # Verify diagnostics were recorded
    assert window.app_vm.active_file_key == key  # File is activated
    assert window.diagnostics_vm.counts()[1] >= 1  # At least 1 warning recorded

    # Verify the message contains "非単調" (non-monotonic)
    entries = window.diagnostics_vm.entries(level="warning")
    messages = [e.message for e in entries]

    assert any("非単調" in msg for msg in messages), (
        f"Expected '非単調' in diagnostics, got: {messages}"
    )


def test_on_loaded_status_bar_shows_info_not_alert_for_info_only(qtbot, tmp_path):
    """LD-12: info-only diagnostics must not be reported as "⚠" alerts (透明化)."""
    window = _make_window(qtbot)
    key = window.app_vm.session.load(_write_csv(tmp_path), _csv_format()).key
    outcome = LoadOutcome(
        key=key,
        diagnostics=(
            Diagnostic(level="info", message="展開1", signal_name="a"),
            Diagnostic(level="info", message="展開2", signal_name="b"),
        ),
    )
    window._on_loaded(outcome)
    msg = window.status_message()  # spec §2.4: 右ラベルへ移設 (showMessage 廃止)
    assert "ℹ 2 件の情報" in msg  # noqa: RUF001
    assert "⚠" not in msg


def test_on_loaded_status_bar_shows_alert_count_excluding_info(qtbot, tmp_path):
    """LD-12: alert count must only tally error/warning, not info."""
    window = _make_window(qtbot)
    key = window.app_vm.session.load(_write_csv(tmp_path), _csv_format()).key
    outcome = LoadOutcome(
        key=key,
        diagnostics=(
            Diagnostic(level="warning", message="skip", signal_name="x"),
            Diagnostic(level="info", message="展開", signal_name="y"),
        ),
    )
    window._on_loaded(outcome)
    msg = window.status_message()  # spec §2.4: 右ラベルへ移設 (showMessage 廃止)
    assert "⚠ 1 件の診断" in msg


def test_diagnostics_dock_exists_with_object_name(qtbot):
    window = _make_window(qtbot)
    assert window.diagnostics_dock.objectName() == "diagnostics_dock"


# ---------------------------------------------------------------------------
# _on_diagnostic_activated — best-effort jump to source/signal (spec §4.4)
# ---------------------------------------------------------------------------


class TestDiagnosticActivatedJump:
    def test_jumps_by_source_basename(self, qtbot, tmp_path):
        """entry_activated may emit the file basename (e.source) as target."""
        window = _make_window(qtbot)
        key = window.app_vm.request_load(_write_csv(tmp_path), _csv_format())
        source = window.app_vm.session.source_name(key)

        window._on_diagnostic_activated(source)

        assert window.app_vm.active_file_key == key

    def test_jumps_by_signal_name(self, qtbot, tmp_path):
        """entry_activated may emit a namespaced signal name as target."""
        window = _make_window(qtbot)
        key = window.app_vm.request_load(_write_csv(tmp_path), _csv_format())
        sig = window.app_vm.session.group_signals(key)[0]

        window._on_diagnostic_activated(sig.name)

        assert window.app_vm.active_file_key == key

    def test_unknown_target_is_noop(self, qtbot, tmp_path):
        """A target matching neither a source name nor a signal name is a no-op."""
        window = _make_window(qtbot)
        key = window.app_vm.request_load(_write_csv(tmp_path), _csv_format())
        window.app_vm.set_active_file(key)

        window._on_diagnostic_activated("no_such_thing")

        assert window.app_vm.active_file_key == key


# ---------------------------------------------------------------------------
# Real dblclick on the Diagnostics dock's table jumps the active file
# (Layer B integration: exercises the FULL wiring — cellDoubleClicked →
# entry_activated → MainWindow._on_diagnostic_activated — via a real
# qtbot.mouseDClick, never entry_activated.emit() directly).
# ---------------------------------------------------------------------------


def test_real_dblclick_on_diagnostics_row_switches_active_file(qtbot, tmp_path):
    window = _make_window(qtbot)
    window.show()
    qtbot.waitExposed(window)

    key_a = window.app_vm.request_load(
        _write_csv_named(tmp_path, "a.csv"), _csv_format()
    )
    key_b = window.app_vm.request_load(
        _write_csv_named(tmp_path, "b.csv"), _csv_format()
    )
    window.app_vm.set_active_file(key_a)

    source_b = window.app_vm.session.source_name(key_b)
    window.diagnostics_vm.add(source_b, [Diagnostic(level="warning", message="skip")])

    table = window.diagnostics_dock._table
    qtbot.waitUntil(
        lambda: table.visualItemRect(table.item(0, 0)).height() > 0, timeout=2000
    )
    pos = table.visualItemRect(table.item(0, 0)).center()
    # Warm-up single click before the double click (see comment in
    # tests/gui/test_diagnostics_view.py::test_real_double_click_on_row_emits_entry_activated
    # for why a lone qtbot.mouseDClick() doesn't reliably fire cellDoubleClicked).
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=pos)

    assert window.app_vm.active_file_key == key_b


def test_real_dblclick_on_row_with_signal_name_switches_active_file(qtbot, tmp_path):
    """LD Task 5 review fix: diagnostics carrying ``signal_name`` (e.g. a raw
    channel name from a non-monotonic-timestamp warning) must still resolve to
    their file on double-click. Before the fix, DiagnosticsView emitted
    ``e.signal_name or e.source`` — a raw channel name matches neither
    ``source_name(key)`` (basename) nor a group signal's namespaced
    ``"key::name"`` in ``MainWindow._on_diagnostic_activated``, so the
    double-click silently no-op'd. Fix: DiagnosticsView always emits
    ``e.source`` (the file basename), which the first loop always resolves."""
    window = _make_window(qtbot)
    window.show()
    qtbot.waitExposed(window)

    key_a = window.app_vm.request_load(
        _write_csv_named(tmp_path, "a.csv"), _csv_format()
    )
    key_b = window.app_vm.request_load(
        _write_csv_named(tmp_path, "b.csv"), _csv_format()
    )
    window.app_vm.set_active_file(key_a)

    source_b = window.app_vm.session.source_name(key_b)
    window.diagnostics_vm.add(
        source_b, [Diagnostic(level="warning", message="skip", signal_name="gps")]
    )

    table = window.diagnostics_dock._table
    qtbot.waitUntil(
        lambda: table.visualItemRect(table.item(0, 0)).height() > 0, timeout=2000
    )
    pos = table.visualItemRect(table.item(0, 0)).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    qtbot.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=pos)

    assert window.app_vm.active_file_key == key_b


# ---------------------------------------------------------------------------
# FB-04: cancel wiring — busy_overlay.cancel_requested → controller, and the
# cancelled-outcome status update (no modal, no diagnostics — spec §6)
# ---------------------------------------------------------------------------


def test_cancel_requested_wired_to_controller(qtbot, monkeypatch):
    window = _make_window(qtbot)
    calls = []
    monkeypatch.setattr(
        window._load_controller, "cancel_active", lambda: calls.append(True)
    )
    window.busy_overlay.cancel_requested.emit()
    assert calls == [True]


def test_on_load_cancelled_updates_status_without_dialog(qtbot, monkeypatch):
    import valisync.gui.views.main_window as mw

    window = _make_window(qtbot)
    dialogs = []
    monkeypatch.setattr(mw.QMessageBox, "critical", lambda *a, **k: dialogs.append(a))
    window._on_load_cancelled(Path("big.mf4"))
    assert "キャンセル" in window.status_message()  # 右ラベルへ移設 (spec §2.4)
    assert "big.mf4" in window.status_message()
    assert dialogs == []  # モーダル無し(spec §6)
    assert window.diagnostics_vm.counts() == (0, 0)  # 診断追記無し


def test_load_file_wires_cancel_event_and_adapter(qtbot, monkeypatch, tmp_path):
    """Verify _load_file creates a cancel Event and passes cancel=event.is_set to session.load.

    This test guards against regression in the critical adapter that allows
    LoadController to request cancellation. If the adapter is missing, hard
    cancellation (via BusyOverlay cancel button) becomes a silent no-op.
    """
    import contextlib
    import threading

    window = _make_window(qtbot)
    captured = {}

    def fake_submit(load_callable, **kwargs):
        captured["kwargs"] = kwargs
        captured["load_callable"] = load_callable

    monkeypatch.setattr(window._load_controller, "submit", fake_submit)
    window._load_file(tmp_path / "x.mf4")

    kw = captured["kwargs"]
    event = kw["cancel_event"]
    assert isinstance(event, threading.Event)
    assert kw["label"] == "x.mf4"
    assert callable(kw["on_cancelled"]) and callable(kw["on_discard"])

    # load_callable が session.load に cancel=event.is_set を渡すこと
    # (欠けるとハードキャンセルが無音で無効化される - 本タスクの肝の配線ガード)
    seen = {}

    def fake_load(path, fmt, cancel=None, confirm_expansion=None):
        seen["cancel"] = cancel
        seen["confirm"] = confirm_expansion
        raise RuntimeError("stop before real load")

    monkeypatch.setattr(window.app_vm.session, "load", fake_load)
    with contextlib.suppress(RuntimeError):
        captured["load_callable"]()
    assert seen["cancel"] == event.is_set  # 同一 Event の bound method
    # confirm_expansion に confirmer.confirm を渡すこと (LD-14 の展開確認配線ガード)
    assert seen["confirm"] == window._expansion_confirmer.confirm

    # on_discard 本体(手遅れ完走の巻き戻し)が正しい key/force で remove_group
    # を呼ぶこと — 「callable であること」だけでは中身の配線ミスを拾えない
    import types

    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        window.app_vm.session,
        "remove_group",
        lambda key, force=False: calls.append((key, force)),
    )
    kw["on_discard"](types.SimpleNamespace(key="csv_9"))
    assert calls == [("csv_9", True)]


# ─── CSV プリフライト配線 (LD-01) ─────────────────────────────────────────────


def test_load_file_csv_uses_resolver_format(qtbot, monkeypatch, tmp_path):
    """CSV は _csv_format_resolver が返す FormatDefinition で session.load される (LD-01)."""
    import contextlib

    window = _make_window(qtbot)
    fmt = _csv_format()
    window._csv_format_resolver = lambda p: fmt  # ダイアログを差し替え

    captured: dict = {}
    monkeypatch.setattr(
        window._load_controller,
        "submit",
        lambda load_callable, **kw: captured.update(cb=load_callable, kw=kw),
    )
    window._load_file(_write_csv(tmp_path))

    seen: dict = {}

    def fake_load(path, f, cancel=None, confirm_expansion=None):
        seen["fmt"] = f
        raise RuntimeError("stop")

    monkeypatch.setattr(window.app_vm.session, "load", fake_load)
    with contextlib.suppress(RuntimeError):
        captured["cb"]()
    assert seen["fmt"] is fmt


def test_load_file_csv_cancel_aborts_without_submit(qtbot, monkeypatch, tmp_path):
    """resolver が None (ダイアログキャンセル) ならロードせず _on_load_cancelled (LD-01)."""
    window = _make_window(qtbot)
    window._csv_format_resolver = lambda p: None

    submits: list = []
    monkeypatch.setattr(
        window._load_controller, "submit", lambda *a, **k: submits.append(a)
    )
    cancelled: list = []
    monkeypatch.setattr(window, "_on_load_cancelled", lambda p: cancelled.append(p))
    window._load_file(_write_csv(tmp_path))

    assert submits == []
    assert len(cancelled) == 1


def test_load_file_mdf_skips_resolver(qtbot, monkeypatch, tmp_path):
    """MDF は resolver を通らず format_def=None で submit (LD-01 無回帰)."""
    window = _make_window(qtbot)
    called: list = []
    window._csv_format_resolver = lambda p: called.append(p)

    captured: dict = {}
    monkeypatch.setattr(
        window._load_controller,
        "submit",
        lambda load_callable, **kw: captured.update(cb=load_callable),
    )
    window._load_file(tmp_path / "x.mf4")
    assert called == []  # CSV 判定を通らない
    assert "cb" in captured  # submit された


# ─── FU-04: Recent ボタンのラベル省略 + window 最小幅不変性 ──────────────────────


class _FakeRecentForMinWidth:
    """existing() だけの duck-stub (test_welcome_view.py と同型。タスク独立性のため重複可)。"""

    def __init__(self, paths: list[str]) -> None:
        self._paths = paths

    def existing(self) -> list[str]:
        return list(self._paths)


def test_window_min_width_does_not_scale_with_recent_path_length(qtbot) -> None:
    """FU-04: Recent のパス長がウィンドウ最小幅を駆動しない。

    修正前は 150 文字→400 文字で最小幅が ~1700px 増える (RED)。修正後は
    どちらも同じ省略予算に収まり差は省略粒度 (数 px) 以内。絶対値でなく
    不変性で assert するのでスタイル/フォント差に頑健。
    """
    from PySide6.QtWidgets import QApplication

    from valisync.gui.views.main_window import MainWindow

    def min_width_with(path: str) -> int:
        mw = MainWindow(AppViewModel())
        qtbot.addWidget(mw)
        mw.welcome_view._recent = _FakeRecentForMinWidth([path])  # type: ignore[assignment]
        mw.welcome_view.refresh()
        # spec の実シナリオ: グラフエリア表示中 (WelcomeView は QStackedWidget の
        # 隠れページ) でも「全ページ最大」経由で最小幅を支配する経路を再現する。
        mw._workbench_started = True
        mw._update_central()
        assert not mw.showing_welcome()
        QApplication.processEvents()
        return mw.minimumSizeHint().width()

    w_mid = min_width_with("C:/" + "d" * 150 + "/m.mf4")
    w_long = min_width_with("C:/" + "d" * 400 + "/m.mf4")
    assert w_long <= w_mid + 16


def test_window_can_still_be_resized_beyond_screen(qtbot) -> None:
    """spec 受け入れ 3: 意図的な大画面表示は不変 (最大幅制約を導入していない)。

    offscreen は WM クランプが無いので、resize がそのまま通る=コード側に
    上限が無いことの回帰ガード。
    """
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    mw.resize(3000, 700)
    assert mw.width() == 3000


# ---------------------------------------------------------------------------
# FU-13: ChannelBrowser double-click wiring opens the single preview window
# ---------------------------------------------------------------------------


def test_channel_browser_double_click_opens_preview(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-13 wiring: ChannelBrowser preview_requested opens the single preview window."""
    from valisync.gui.views.signal_preview_window import SignalPreviewWindow

    window = _make_window(qtbot)
    assert isinstance(window.signal_preview_window, SignalPreviewWindow)  # type: ignore[union-attr]
    # Emitting preview_requested drives show_signal (window becomes visible).
    window.channel_browser_view.preview_requested.emit("nonexistent::key")  # type: ignore[union-attr]
    assert window.signal_preview_window.isVisible()  # type: ignore[union-attr]


def test_preview_window_is_parented_to_main_window(qtbot: QtBot) -> None:
    """Important #1 (final review): SignalPreviewWindow must be parented to
    MainWindow, not a parent-less top-level. Qt's quitOnLastWindowClosed only
    quits on the last PARENT-LESS top-level closing, so a parent-less preview
    left open when MainWindow is closed via X orphans the app (never quits).
    It must still be a floating, non-modal top-level window (isWindow() True)
    -- parenting just ties its lifetime to MainWindow and stops it counting as
    a primary window."""
    window = _make_window(qtbot)
    assert window.signal_preview_window.parent() is window  # type: ignore[union-attr]
    assert window.signal_preview_window.isWindow() is True  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# 折りたたみ可能ドック (collapsible-docks 増分C Task 3)
# ---------------------------------------------------------------------------


def test_docks_have_collapsible_title_bars(qtbot):
    from valisync.gui.app import build_main_window
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win = build_main_window()
    qtbot.addWidget(win)
    for dock in (win.file_dock, win.channel_dock, win.diagnostics_dock):
        assert isinstance(dock.titleBarWidget(), CollapsibleDockTitleBar), (
            dock.objectName()
        )


# ---------------------------------------------------------------------------
# 辺対応の折りたたみ (edge-aware-dock-collapse Task 5) — hide+レール機構
# ---------------------------------------------------------------------------


def test_collapse_hides_dock_and_adds_rail_tab(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win._collapse_dock(win.file_dock)
    assert win.file_dock.isHidden()  # ドックは hide
    rail = win._collapse_rails[win.dockWidgetArea(win.file_dock)]
    assert not rail.is_empty()  # 対応辺レールにタブ


def test_expand_from_rail_shows_dock(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    edge = win.dockWidgetArea(win.file_dock)
    win._collapse_dock(win.file_dock)
    win._expand_dock(win.file_dock)
    assert not win.file_dock.isHidden()
    assert win._collapse_rails[edge].is_empty()


def test_collapse_state_roundtrips_through_qsettings(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    win._collapse_dock(win.file_dock)
    win.save_state()
    win2 = build_main_window()
    qtbot.addWidget(win2)
    win2.show()
    assert win2.file_dock.isHidden()
    assert not win2.channel_dock.isHidden()


def test_reset_layout_expands_all_docks(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    win._collapse_dock(win.diagnostics_dock)
    win._reset_layout()
    assert not win.diagnostics_dock.isHidden()


# ---------------------------------------------------------------------------
# 辺対応の折りたたみ (edge-aware-dock-collapse Task 3)
# ---------------------------------------------------------------------------


def test_docks_forbid_top_area(qtbot):
    from PySide6.QtCore import Qt

    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    for dock in (win.file_dock, win.channel_dock, win.diagnostics_dock):
        areas = dock.allowedAreas()
        assert not (areas & Qt.DockWidgetArea.TopDockWidgetArea), dock.objectName()
        assert areas & Qt.DockWidgetArea.RightDockWidgetArea
        assert areas & Qt.DockWidgetArea.LeftDockWidgetArea
        assert areas & Qt.DockWidgetArea.BottomDockWidgetArea


def test_expand_right_dock_resizes_horizontal_with_captured_extent(qtbot):
    """右ドック (VERTICAL レール) の展開は resizeDocks を
    orientation=Horizontal・畳む直前に控えた幅で呼ぶ。

    _dock_extent/_expand_dock の軸写像 (VERTICAL→Horizontal) を直接検証する
    (Task 5 で増分C由来の同種 resizeDocks spy テストが削除され無検証だった)。
    """
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    win._collapse_dock(win.file_dock)
    expected_extent = win._expanded_extent["file_dock"]

    calls: list[tuple[list[QDockWidget], list[int], Qt.Orientation]] = []
    original_resize_docks = win.resizeDocks

    def _spy_resize_docks(
        docks: list[QDockWidget], sizes: list[int], orient: Qt.Orientation
    ) -> None:
        calls.append((list(docks), list(sizes), orient))
        original_resize_docks(docks, sizes, orient)

    win.resizeDocks = _spy_resize_docks  # type: ignore[assignment]

    win._expand_dock(win.file_dock)

    assert calls, "展開で resizeDocks が呼ばれていない"
    docks, sizes, orient = calls[-1]
    assert docks == [win.file_dock]
    assert sizes == [expected_extent]
    assert orient == Qt.Orientation.Horizontal


def test_expand_bottom_dock_resizes_vertical_with_captured_extent(qtbot):
    """下ドック (HORIZONTAL レール) の展開は resizeDocks を
    orientation=Vertical・畳む直前に控えた高さで呼ぶ。

    _dock_extent/_expand_dock の軸写像 (HORIZONTAL→Vertical) を直接検証する
    (Task 5 で増分C由来の同種 resizeDocks spy テストが削除され無検証だった)。
    """
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    win._collapse_dock(win.diagnostics_dock)
    expected_extent = win._expanded_extent["diagnostics_dock"]

    calls: list[tuple[list[QDockWidget], list[int], Qt.Orientation]] = []
    original_resize_docks = win.resizeDocks

    def _spy_resize_docks(
        docks: list[QDockWidget], sizes: list[int], orient: Qt.Orientation
    ) -> None:
        calls.append((list(docks), list(sizes), orient))
        original_resize_docks(docks, sizes, orient)

    win.resizeDocks = _spy_resize_docks  # type: ignore[assignment]

    win._expand_dock(win.diagnostics_dock)

    assert calls, "展開で resizeDocks が呼ばれていない"
    docks, sizes, orient = calls[-1]
    assert docks == [win.diagnostics_dock]
    assert sizes == [expected_extent]
    assert orient == Qt.Orientation.Vertical


# ---------------------------------------------------------------------------
# 外部 show() の整合 (edge-aware-dock-collapse ブランチレビュー Important 1)
#
# 畳み=hide() へ切替済みのため、View メニュー/ツールバーの toggleViewAction や
# _on_load_error の diagnostics_dock.show() のような「集約状態機械を経由しない
# 直接 show()」は素の show() を呼ぶだけで、レールタブ/_collapsed_docks/
# QSettings のいずれも更新しない (孤立 UI + 次回起動での意図しない再畳み)。
# ---------------------------------------------------------------------------


def test_toggling_collapsed_dock_visible_reconciles_rail_and_state(qtbot):
    from PySide6.QtCore import QSettings

    import valisync.gui.views.main_window as mw
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    win._collapse_dock(win.file_dock)
    rail = win._collapse_rails[win.dockWidgetArea(win.file_dock)]
    assert win.file_dock.isHidden()
    assert not rail.is_empty()
    assert "file_dock" in win._collapsed_docks

    # toggleViewAction は QDockWidget 標準の show()/hide() トグルであり、
    # collapse 状態機械 (_expand_dock) を経由しない外部トリガの代表例。
    win.file_dock.toggleViewAction().trigger()

    assert not win.file_dock.isHidden(), "toggleViewAction は show() を呼ぶはず"
    assert rail.is_empty(), "外部 show() 後もレールにタブが残っている (孤立UI)"
    assert "file_dock" not in win._collapsed_docks, (
        "外部 show() 後も _collapsed_docks に残存 (次回起動で意図せず再畳み)"
    )
    settings = QSettings(mw._ORG, mw._APP)
    saved = settings.value("dockCollapsed")
    assert saved["file_dock"] is False, "永続化された畳み状態が更新されていない"


def test_external_show_on_collapsed_diagnostics_dock_reconciles(qtbot):
    """_on_load_error 相当 (diagnostics_dock.show() + raise_()) も同様に自己修復する。"""
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    win._collapse_dock(win.diagnostics_dock)
    rail = win._collapse_rails[win.dockWidgetArea(win.diagnostics_dock)]
    assert win.diagnostics_dock.isHidden()

    # _on_load_error と同型の直接呼び出し (状態機械を経由しない)。
    win.diagnostics_dock.show()
    win.diagnostics_dock.raise_()

    assert not win.diagnostics_dock.isHidden()
    assert rail.is_empty(), "外部 show() 後もレールにタブが残っている (孤立UI)"
    assert "diagnostics_dock" not in win._collapsed_docks


# ---------------------------------------------------------------------------
# 起動時の畳みが未レイアウトの extent を捕捉しない (ブランチレビュー Important 2)
#
# _apply_saved_collapse は window.show() より前 (__init__ 内) に走るため、その
# 時点で _collapse_dock が無条件に捕捉する extent はレイアウト未確定の既定値に
# なり得る。隠れている (=まだ表示・レイアウトされていない) ドックからの捕捉は
# スキップし、Qt 自身の restoreState プレースホルダによる復元に委ねる。
# ---------------------------------------------------------------------------


def test_startup_collapse_does_not_capture_stale_extent(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win._collapse_dock(win.file_dock)
    win.save_state()

    # win2.__init__ は _restore_state() -> _apply_saved_collapse() を実行する
    # (起動時パスの再現)。win2.show() は意図的に呼ばない — 「表示・レイアウト
    # される前」というタイミングそのものを再現するため。
    win2 = build_main_window()
    qtbot.addWidget(win2)

    assert "file_dock" not in win2._expanded_extent, (
        "起動時 (未表示) の畳みで extent を捕捉してしまっている"
        "(未レイアウトの既定値が記録され、後の展開で誤ったサイズへ resize される)"
    )


# ---------------------------------------------------------------------------
# 初期ドック比率 File:Channel = 1:4 (UX-21 応急・spec §1.5-12)
#
# 適用は初回 show 後 (singleShot(0)) — pre-show は dock extent 未確定で
# resizeDocks が no-op になる既知の罠 (_collapse_dock の Important 2 コメントと
# 同型)。ここでは呼出記録 (spy) のみを検証する — offscreen での dock 実寸
# assert は false-green (memory
# gui_dock_toggle_width_change_needs_real_display_and_layout)。実効性は
# Task 9 のカタログを実ディスプレイで確認する。
# ---------------------------------------------------------------------------


def _spy_resize_docks(
    win: object,
) -> list[tuple[list[QDockWidget], list[int], Qt.Orientation]]:
    """win.resizeDocks を差し替えて呼出記録 (docks, sizes, orient) を返す。"""
    calls: list[tuple[list[QDockWidget], list[int], Qt.Orientation]] = []
    original = win.resizeDocks  # type: ignore[attr-defined]

    def _spy(
        docks: list[QDockWidget], sizes: list[int], orient: Qt.Orientation
    ) -> None:
        calls.append((list(docks), list(sizes), orient))
        original(docks, sizes, orient)

    win.resizeDocks = _spy  # type: ignore[attr-defined,method-assign]
    return calls


def test_default_dock_ratio_applied_after_first_show_when_no_saved_state(qtbot):
    """保存 state 無しの初回 show 後、File:Channel=1:4 で resizeDocks が呼ばれる。"""
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    calls = _spy_resize_docks(win)

    win.show()
    qtbot.waitExposed(win)
    qtbot.wait(50)  # singleShot(0) の実行を消化

    ratio_calls = [c for c in calls if set(c[0]) == {win.file_dock, win.channel_dock}]
    assert ratio_calls, "初回 show 後に 1:4 の resizeDocks が呼ばれていない"
    docks, sizes, orient = ratio_calls[-1]
    assert docks == [win.file_dock, win.channel_dock]
    assert sizes == [1, 4]
    assert orient == Qt.Orientation.Vertical


def test_default_dock_ratio_not_applied_when_saved_state_present(qtbot):
    """保存 state ありの場合は初回 show 後に 1:4 を強制適用しない (ユーザー配置を尊重)。"""
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.save_state()

    win2 = build_main_window()
    qtbot.addWidget(win2)
    calls = _spy_resize_docks(win2)

    win2.show()
    qtbot.waitExposed(win2)
    qtbot.wait(50)

    ratio_calls = [c for c in calls if set(c[0]) == {win2.file_dock, win2.channel_dock}]
    assert not ratio_calls, "保存 state があるのに 1:4 が強制適用されている"


def test_reset_layout_reapplies_default_dock_ratio(qtbot):
    """_reset_layout() 後にも同じ 1:4 が再適用される (spec (c) — 初回起動と Reset
    Layout の比率一致)。"""
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    qtbot.wait(50)  # 初回 show 後の適用を消化しておく

    calls = _spy_resize_docks(win)
    win._reset_layout()

    ratio_calls = [c for c in calls if set(c[0]) == {win.file_dock, win.channel_dock}]
    assert ratio_calls, "_reset_layout() 後に 1:4 の resizeDocks が呼ばれていない"
    docks, sizes, orient = ratio_calls[-1]
    assert docks == [win.file_dock, win.channel_dock]
    assert sizes == [1, 4]
    assert orient == Qt.Orientation.Vertical


# ---------------------------------------------------------------------------
# Status bar 刷新 (計測 IA・spec §2.4): 左=即値 / 右=メッセージ・statusTip 横取り
# ---------------------------------------------------------------------------


def test_set_status_message_writes_right_label(qtbot):
    window = _make_window(qtbot)
    window.set_status_message("読み込みました")
    assert window.status_message() == "読み込みました"


def test_set_status_message_timeout_auto_clears(qtbot):
    window = _make_window(qtbot)
    window.set_status_message("一時メッセージ", timeout_ms=50)
    assert window.status_message() == "一時メッセージ"
    qtbot.wait(150)
    assert window.status_message() == ""


def test_set_status_message_restart_cancels_prior_timer(qtbot):
    """再呼び出しは前タイマーを破棄する — 古いクリアが新メッセージを消さない。"""
    window = _make_window(qtbot)
    window.set_status_message("first", timeout_ms=50)
    window.set_status_message("second")  # timeout=0 → 常設
    qtbot.wait(150)
    assert window.status_message() == "second"


def test_status_tip_event_intercepted_keeps_immediate_visible(qtbot):
    """blocker: QStatusTipEvent を横取りし右ラベルへ流す — 左即値は隠れない (§2.4)。

    横取りを外すと Qt 既定処理が内部 showMessage(tip) を駆動し、addWidget した
    左即値ラベル (非常設) を一時的に隠す。sendEvent 後に左が isVisible のまま
    かつ右ラベルに tip が出ることで、既定処理へ通していないことを直接実証する。
    """
    from PySide6.QtGui import QStatusTipEvent
    from PySide6.QtWidgets import QApplication

    window = _make_window(qtbot)
    window.graph_area_vm.active_panel().set_cursor(3.0)  # 左 A ラベルに文字を出す
    window.show()
    qtbot.waitExposed(window)

    QApplication.sendEvent(window, QStatusTipEvent("メニューを開く"))

    assert window.status_message() == "メニューを開く"  # 右ラベルへ反映
    assert window._status_cursor_a.isVisible()  # 左即値は隠れていない


def test_immediate_values_show_on_cursor_set(qtbot):
    """カーソル設置で左即値 (A/B/Δt) が .3f 書式で出る・未設置は空文字。"""
    window = _make_window(qtbot)
    panel = window.graph_area_vm.active_panel()

    assert window._status_cursor_a.text() == ""  # 初期は空
    assert window._status_cursor_b.text() == ""
    assert window._status_cursor_delta.text() == ""

    panel.set_cursor(3.0)
    assert window._status_cursor_a.text() == "A 3.000 s"
    assert window._status_cursor_b.text() == ""  # B 未設置
    assert window._status_cursor_delta.text() == ""  # Δt は A/B 双方要

    panel.set_cursor_b(6.0)  # A 設置済みなので暗黙 delta で B 設置
    assert window._status_cursor_b.text() == "B 6.000 s"
    assert window._status_cursor_delta.text() == "Δt 3.000 s"

    panel.set_cursor(None)  # A 消去 → B/Δt も消える
    assert window._status_cursor_a.text() == ""
    assert window._status_cursor_b.text() == ""
    assert window._status_cursor_delta.text() == ""


def test_immediate_values_swap_on_tab_switch(qtbot):
    """タブ切替で左即値がそのタブの CursorState に入れ替わる (§2.4)。"""
    window = _make_window(qtbot)
    vm = window.graph_area_vm
    vm.active_panel().set_cursor(3.0)
    assert window._status_cursor_a.text() == "A 3.000 s"

    vm.add_tab()  # 新タブ (別 CursorState・アクティブ化 → "tabs" notify)
    assert window._status_cursor_a.text() == ""  # 新タブは未設置

    vm.set_active_tab(0)  # 元タブへ戻る → "active" notify
    assert window._status_cursor_a.text() == "A 3.000 s"


def test_immediate_label_a_uses_chrome_cursor_a_not_cursor_a(qtbot):
    """chrome_cursor_a は cursor_a と DARK 同値の別役割 — 値分岐で誤配線を実証。

    DARK では両者同値のため値ベース assert は盲目。chrome_cursor_a だけを分岐
    させたテーマで A 即値ラベルの色がどちらを参照するか直接実証する。
    """
    import dataclasses

    from valisync.gui.theme.tokens import DARK, Color, set_active

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, chrome_cursor_a=Color(1, 2, 3))
    )
    set_active(alt)
    try:
        window = _make_window(qtbot)
        sheet = window._status_cursor_a.styleSheet()
        assert Color(1, 2, 3).hex in sheet
        assert DARK.colors.cursor_a.hex not in sheet
    finally:
        set_active(DARK)


def test_immediate_label_b_uses_chrome_cursor_b_not_cursor_b(qtbot):
    """chrome_cursor_b は cursor_b と DARK 同値の別役割 — 値分岐で誤配線を実証。"""
    import dataclasses

    from valisync.gui.theme.tokens import DARK, Color, set_active

    alt = dataclasses.replace(
        DARK, colors=dataclasses.replace(DARK.colors, chrome_cursor_b=Color(1, 2, 3))
    )
    set_active(alt)
    try:
        window = _make_window(qtbot)
        sheet = window._status_cursor_b.styleSheet()
        assert Color(1, 2, 3).hex in sheet
        assert DARK.colors.cursor_b.hex not in sheet
    finally:
        set_active(DARK)
