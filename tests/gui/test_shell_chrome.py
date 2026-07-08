"""Shell chrome tests — shortcuts and menu mnemonics (SH-05)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def _mw(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    mw = MainWindow(AppViewModel())
    mw.recent_files = mw.recent_files.__class__(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(mw)
    return mw


def test_open_folder_has_shortcut(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    assert mw.shell_actions.action("open_folder").shortcut() == QKeySequence(
        "Ctrl+Shift+O"
    )


def test_exit_has_quit_shortcut(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    assert mw.action_exit.shortcut() == QKeySequence(QKeySequence.StandardKey.Quit)


def test_menu_titles_have_mnemonics(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    titles = [a.text() for a in mw.menuBar().actions()]
    assert "&File" in titles
    assert "&View" in titles
    assert "&Help" in titles


def test_toolbar_has_dock_toggles(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QToolBar

    mw = _mw(qtbot, tmp_path)
    toolbar = mw.findChild(QToolBar, "main_toolbar")
    assert toolbar is not None
    toolbar_actions = toolbar.actions()
    assert mw.file_dock.toggleViewAction() in toolbar_actions
    assert mw.channel_dock.toggleViewAction() in toolbar_actions
    assert mw.diagnostics_dock.toggleViewAction() in toolbar_actions


def test_toolbar_toggle_hides_dock(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    mw.show()
    qtbot.waitExposed(mw)
    toggle = mw.file_dock.toggleViewAction()
    assert mw.file_dock.isVisible()
    toggle.trigger()  # ツールバーボタンと同一 action
    assert not mw.file_dock.isVisible()
