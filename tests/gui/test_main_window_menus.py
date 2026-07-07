from __future__ import annotations

from PySide6.QtWidgets import QToolBar
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def _menu_titles(mw: MainWindow) -> list[str]:
    return [a.text() for a in mw.menuBar().actions()]


def test_menubar_has_file_view_analyze_help(qtbot: QtBot) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    titles = _menu_titles(mw)
    assert titles[0] == "File"
    assert {"File", "View", "Analyze", "Help"} <= set(titles)


def test_toolbar_exposes_open_and_export(qtbot: QtBot) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    tb = mw.findChild(QToolBar, "main_toolbar")
    assert tb is not None
    acts = set(tb.actions())
    assert mw.shell_actions.action("open") in acts
    assert mw.shell_actions.action("export") in acts
