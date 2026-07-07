"""Layer C: real-OS-input test for axis pointer shapes (増分② PC-13).

Hovering a NON-active Y axis must apply the PointingHand cursor ("click to
activate") via _AlignedAxisItem.hoverMoveEvent (graph_panel_view.py). Synthetic
hover events can false-green the QCursor application path (hoverMove dispatch and
setCursor go through Qt's real event machinery), so real OS hover is the honest
gate — mirrors memory gui_realgui_move_not_reaching_parent_qwidget /
gui_realgui_hover_needs_incremental_move.

Real OS hover only: pyqtgraph's hoverMove dispatch needs genuine incremental
mouse movement; a one-shot SetCursorPos delivers no hoverMoveEvent.

Honest RED: revert hoverMoveEvent's non-active branch to ``self.unsetCursor()`` —
the non-active axis then keeps ArrowCursor and the PointingHand assertion fails.

X inner=zoom (BitmapCursor) / outer=pan (SizeHor) and the cursor-line SizeHor can
be verified similarly by sweeping the viewport strip / the cursor line; kept out
of this skeleton to stay focused on the axis-gate honest gate.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import MOVE, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_non_active_axis_hover_shows_pointing_hand(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """PC-13: hovering a NON-active Y axis applies the PointingHand (activate) cursor."""
    skip_unless_real_display()
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    view.setGeometry(screen.x() + 80, screen.y() + 80, 800, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )

    view.set_active_axis(0)  # axis 0 active → axis 1 is the non-active hover target
    QApplication.processEvents()
    assert view._active_axis_index == 0

    axis = view._y_axes[1]  # NON-active axis
    gv = view.plot_widget
    dpr = view.devicePixelRatioF()
    w = axis.width()
    h = axis.boundingRect().height()

    def item_to_phys(lx: float, ly: float) -> tuple[int, int]:
        sp = axis.mapToScene(QPointF(lx, ly))
        g = gv.viewport().mapToGlobal(gv.mapFromScene(sp))
        return round(g.x() * dpr), round(g.y() * dpr)

    gx, gy = item_to_phys(w * 0.5, h * 0.5)
    got = None
    for _attempt in range(6):
        for off in range(30, -1, -3):
            at(gx, gy - off, MOVE)
            QApplication.processEvents()
            time.sleep(0.012)
        time.sleep(0.04)
        QApplication.processEvents()
        if axis.cursor().shape() == Qt.CursorShape.PointingHandCursor:
            got = axis.cursor().shape()
            break

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "axis_cursor_pointing_hand.png")
        )

    assert got == Qt.CursorShape.PointingHandCursor, (
        "hovering the non-active axis 1 never applied PointingHandCursor — the "
        "activate-hint cursor is not being driven. "
        f"got {axis.cursor().shape()!r}. screenshot: "
        f"{tmp_path / 'axis_cursor_pointing_hand.png'}"
    )
