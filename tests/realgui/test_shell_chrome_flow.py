# tests/realgui/test_shell_chrome_flow.py
"""Layer C: shell chrome no jitsu OS input (SH-11/12)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def _shown_mw(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    mw.recent_files = mw.recent_files.__class__(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(mw)
    mw.resize(1000, 700)
    mw.show()
    qtbot.waitExposed(mw)
    QApplication.processEvents()
    return mw


def test_toolbar_dock_toggle_real_click(qtbot: QtBot, tmp_path: Path) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

    mw = _shown_mw(qtbot, tmp_path)
    toolbar = mw.findChild(QToolBar, "main_toolbar")
    toggle = mw.file_dock.toggleViewAction()
    btn = toolbar.widgetForAction(toggle)
    assert isinstance(btn, QToolButton)
    assert mw.file_dock.isVisible()
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not mw.file_dock.isVisible(), "toolbar toggle real click de dock ga kakurenu"


def test_reset_layout_real(qtbot: QtBot, tmp_path: Path) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    mw = _shown_mw(qtbot, tmp_path)
    mw.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, mw.file_dock)
    QApplication.processEvents()
    mw.action_reset_layout.trigger()
    QApplication.processEvents()
    assert mw.dockWidgetArea(mw.file_dock) == Qt.DockWidgetArea.RightDockWidgetArea
