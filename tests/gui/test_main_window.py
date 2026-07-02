"""Tests for MainWindow — Task 6.1.

TDD: tests written first; all must FAIL before implementation exists.
"""

from __future__ import annotations

from pathlib import Path

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


# ---------------------------------------------------------------------------
# Dock existence and type
# ---------------------------------------------------------------------------


class TestDocksExist:
    def test_channel_dock_is_qdockwidget(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        assert isinstance(window.channel_dock, QDockWidget)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Central Widget
# ---------------------------------------------------------------------------


class TestCentralWidget:
    def test_graph_area_is_central_widget(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_area_view import GraphAreaView

        window = _make_window(qtbot)
        assert isinstance(window.centralWidget(), GraphAreaView)  # type: ignore[union-attr]


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
