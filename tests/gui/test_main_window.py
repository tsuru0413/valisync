"""Tests for MainWindow — Task 6.1.

TDD: tests written first; all must FAIL before implementation exists.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDockWidget
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

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


# ---------------------------------------------------------------------------
# Dock existence and type
# ---------------------------------------------------------------------------


class TestDocksExist:
    def test_channel_dock_is_qdockwidget(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        assert isinstance(window.channel_dock, QDockWidget)  # type: ignore[union-attr]

    def test_graph_dock_is_qdockwidget(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        assert isinstance(window.graph_dock, QDockWidget)  # type: ignore[union-attr]


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

    def test_graph_dock_is_floatable(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        features = window.graph_dock.features()  # type: ignore[union-attr]
        assert features & QDockWidget.DockWidgetFeature.DockWidgetFloatable

    def test_graph_dock_is_closable(self, qtbot: QtBot) -> None:
        window = _make_window(qtbot)
        features = window.graph_dock.features()  # type: ignore[union-attr]
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
        # NOTE (offscreen): isVisible() only reflects the shown hierarchy, so we
        # must show the window before testing dock visibility toggling.
        window = _make_window(qtbot)
        window.show()  # type: ignore[union-attr]
        dock = window.channel_dock  # type: ignore[union-attr]
        assert dock.isVisible()
        # Close the dock (sets invisible within the shown hierarchy)
        dock.close()
        assert not dock.isVisible()
        # Trigger the toggle action to re-show
        action = dock.toggleViewAction()
        action.trigger()
        assert dock.isVisible()

    def test_graph_dock_toggle_action_reshows_closed_dock(self, qtbot: QtBot) -> None:
        # NOTE (offscreen): same rationale as the channel dock test above.
        window = _make_window(qtbot)
        window.show()  # type: ignore[union-attr]
        dock = window.graph_dock  # type: ignore[union-attr]
        assert dock.isVisible()
        dock.close()
        assert not dock.isVisible()
        action = dock.toggleViewAction()
        action.trigger()
        assert dock.isVisible()


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
    def test_save_state_runs_without_error(
        self, qtbot: QtBot, tmp_path: object
    ) -> None:
        from PySide6.QtCore import QSettings

        # Redirect settings to a temp location to avoid polluting user settings
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(tmp_path),  # type: ignore[arg-type]
        )
        window = _make_window(qtbot)
        window.save_state()  # type: ignore[union-attr]

    def test_second_mainwindow_restore_does_not_crash(
        self, qtbot: QtBot, tmp_path: object
    ) -> None:
        """After save_state, constructing a new MainWindow must not raise."""
        from PySide6.QtCore import QSettings

        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            str(tmp_path),  # type: ignore[arg-type]
        )
        from valisync.gui.views.main_window import MainWindow

        app_vm = AppViewModel()
        w1 = MainWindow(app_vm)
        qtbot.addWidget(w1)
        w1.save_state()

        # Second construction exercises the restore path
        w2 = MainWindow(app_vm)
        qtbot.addWidget(w2)
        assert w2.windowTitle() == "ValiSync"

    def test_first_run_no_stored_state_does_not_crash(
        self, qtbot: QtBot, tmp_path: object
    ) -> None:
        """First run with an empty settings store must not crash."""
        # Point to a fresh empty directory — no prior state exists
        import uuid

        from PySide6.QtCore import QSettings

        fresh = str(tmp_path) + "/" + str(uuid.uuid4())  # type: ignore[operator]
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            fresh,
        )
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

    def test_graph_dock_holds_graph_area_view(self, qtbot: QtBot) -> None:
        from valisync.gui.views.graph_area_view import GraphAreaView

        window = _make_window(qtbot)
        assert isinstance(window.graph_dock.widget(), GraphAreaView)  # type: ignore[union-attr]


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
