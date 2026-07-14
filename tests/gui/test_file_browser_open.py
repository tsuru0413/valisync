from __future__ import annotations

from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
from valisync.gui.views.file_browser_view import FileBrowserView


def test_no_open_button_or_signal(qtbot: QtBot) -> None:
    """FU-05: the header 'open' button and its open_requested signal are removed.

    Open is reached via the Welcome CTA / toolbar / File>Open / Ctrl+O instead.
    """
    view = FileBrowserView(FileBrowserVM(AppViewModel()))
    qtbot.addWidget(view)
    assert view.findChild(QPushButton, "file_browser_open") is None
    assert not hasattr(view, "open_requested")
