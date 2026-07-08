from __future__ import annotations

from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
from valisync.gui.views.file_browser_view import FileBrowserView


def test_open_button_emits_open_requested(qtbot: QtBot) -> None:
    view = FileBrowserView(FileBrowserVM(AppViewModel()))
    qtbot.addWidget(view)
    fired: list[int] = []
    view.open_requested.connect(lambda: fired.append(1))
    btn = view.findChild(QPushButton, "file_browser_open")
    assert btn is not None
    btn.click()
    assert fired == [1]
