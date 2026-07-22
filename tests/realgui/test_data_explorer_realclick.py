"""Layer C: real-OS-input test for the DataExplorer file context menu.

Opt-in — run with ``--realgui`` on Windows + a real display. Issues a genuine
right-click via Win32 and asserts the application's own QMenu pops up.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.mdf4_helpers import CAN, write_mdf4
from tests.realgui._realgui_input import RDOWN, RUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_file_menu_appears_on_real_os_right_click(qtbot: QtBot, tmp_path: Path) -> None:
    skip_unless_real_display()

    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.data_explorer_view import DataExplorerView

    mf4 = write_mdf4(
        tmp_path / "log.mf4",
        [
            {
                "name": "s",
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
                "bus_type": CAN,
            }
        ],
    )

    view = DataExplorerView(AppViewModel())
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 480, 320)
    view.show()
    qtbot.waitExposed(view)

    # Root the tree at tmp_path and wait for the file row (QFileSystemModel
    # populates the directory asynchronously).
    view.add_source(tmp_path)
    file_index = view.fs_model.index(str(mf4))
    qtbot.waitUntil(
        lambda: file_index.isValid() and view.tree.visualRect(file_index).height() > 0,
        timeout=5000,
    )

    dpr = view.devicePixelRatioF()
    center = view.tree.visualRect(file_index).center()
    gp = view.tree.viewport().mapToGlobal(center)
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)

    captured: dict[str, object] = {}

    def do_real_right_click() -> None:
        at(phys_x, phys_y, RDOWN)
        at(phys_x, phys_y, RUP)

    loop = QEventLoop()

    def capture() -> None:
        popup = QApplication.activePopupWidget()
        captured["type"] = type(popup).__name__ if popup is not None else None
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "de.png"))
        if isinstance(popup, QMenu):
            captured["actions"] = [a.text() for a in popup.actions()]
            popup.close()
        loop.quit()

    QTimer.singleShot(300, do_real_right_click)
    QTimer.singleShot(900, capture)
    QTimer.singleShot(4000, loop.quit)  # safety net
    loop.exec()

    assert captured.get("type") == "QMenu", (
        "no context menu on a real OS right-click; "
        f"got {captured.get('type')!r}. screenshot: {tmp_path / 'de.png'}"
    )
    assert captured.get("actions") == [
        "ファイルを開く",
        "データソースから削除",
    ]
