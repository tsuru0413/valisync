"""Layer C: real-OS-input test for the GraphPanel context menu.

Opt-in — run with ``--realgui`` on Windows + a real display. A genuine
right-click on the plot must raise the panel's OWN menu ("Add Panel" …), NOT
pyqtgraph's default "Plot Options" ViewBox menu. This is the conflict that
``ViewBox.setMenuEnabled(False)`` resolves; a synthesized event cannot prove it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import RDOWN, RUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_panel_menu_wins_over_pyqtgraph_on_real_right_click(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()

    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = GraphPanelView(GraphPanelVM(Session()))
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 520, 360)
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(lambda: view.plot_widget.viewport().width() > 0, timeout=3000)

    # Right-click the centre of the plot viewport (inside the master ViewBox,
    # clear of the Y axis on the left and any grips/frame at the edges).
    dpr = view.devicePixelRatioF()
    vp = view.plot_widget.viewport()
    center = vp.rect().center()
    gp = vp.mapToGlobal(center)
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)

    captured: dict[str, object] = {}

    def do_real_right_click() -> None:
        at(phys_x, phys_y, RDOWN)
        at(phys_x, phys_y, RUP)

    loop = QEventLoop()

    def capture() -> None:
        popup = QApplication.activePopupWidget()
        captured["type"] = type(popup).__name__ if popup is not None else None
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "gp.png"))
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
        f"got {captured.get('type')!r}. screenshot: {tmp_path / 'gp.png'}"
    )
    actions = captured.get("actions") or []
    assert "Add Panel" in actions, (
        "real right-click did not raise the panel's own menu (pyqtgraph default "
        f"won?); actions={actions!r}. screenshot: {tmp_path / 'gp.png'}"
    )
