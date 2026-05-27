"""Tests for app.py entry point — Task 6.2.

TDD: tests written first; all must FAIL before implementation exists.
NOTE: app.exec() is never called in tests (it would block).
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDockWidget
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel

# ---------------------------------------------------------------------------
# build_main_window helper
# ---------------------------------------------------------------------------


class TestBuildMainWindow:
    def test_returns_main_window_instance(
        self, qapp: QApplication, qtbot: QtBot
    ) -> None:
        from valisync.gui.app import build_main_window
        from valisync.gui.views.main_window import MainWindow

        window = build_main_window()
        qtbot.addWidget(window)
        assert isinstance(window, MainWindow)

    def test_window_title_is_valisync(self, qapp: QApplication, qtbot: QtBot) -> None:
        from valisync.gui.app import build_main_window

        window = build_main_window()
        qtbot.addWidget(window)
        assert window.windowTitle() == "ValiSync"

    def test_channel_dock_present(self, qapp: QApplication, qtbot: QtBot) -> None:
        from valisync.gui.app import build_main_window

        window = build_main_window()
        qtbot.addWidget(window)
        assert isinstance(window.channel_dock, QDockWidget)

    def test_graph_dock_present(self, qapp: QApplication, qtbot: QtBot) -> None:
        from valisync.gui.app import build_main_window

        window = build_main_window()
        qtbot.addWidget(window)
        assert isinstance(window.graph_dock, QDockWidget)

    def test_accepts_explicit_app_vm(self, qapp: QApplication, qtbot: QtBot) -> None:
        from valisync.gui.app import build_main_window

        app_vm = AppViewModel()
        window = build_main_window(app_vm=app_vm)
        qtbot.addWidget(window)
        assert window.windowTitle() == "ValiSync"

    def test_window_can_be_shown(self, qapp: QApplication, qtbot: QtBot) -> None:
        """show() must not raise on the offscreen platform."""
        from valisync.gui.app import build_main_window

        window = build_main_window()
        qtbot.addWidget(window)
        window.show()
        assert window.isVisible()


# ---------------------------------------------------------------------------
# main() is callable (we do NOT call it because exec() would block)
# ---------------------------------------------------------------------------


class TestMainCallable:
    def test_main_is_callable(self) -> None:
        from valisync.gui.app import main

        assert callable(main)
