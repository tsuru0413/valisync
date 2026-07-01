"""Layer C: real-OS-input test for the non-active-axis hover provisional frame.

Low-cluster item — hovering a non-active Y axis draws a provisional frame that
signals "clickable to activate". _AlignedAxisItem.paint draws it when
_is_active_or_hover() is True (graph_panel_view.py:328,374); hovering sets
GraphPanelView._hover_axis_index via set_hover_axis (line 1071). The frame is
immediate-mode paint (no separate QGraphicsItem), so _hover_axis_index — the state
that gates the paint — is the honest assertable proxy. The visual appearance is
captured to a screenshot for /verify.

Real OS hover only: pyqtgraph's hoverMove dispatch needs genuine incremental
mouse movement; a one-shot SetCursorPos delivers no hoverMoveEvent
(memory gui_realgui_hover_needs_incremental_move).

Honest RED: make GraphPanelView.set_hover_axis (graph_panel_view.py:1071) a no-op
(early ``return`` before it assigns _hover_axis_index) — hovering never updates the
state, mid_hover_index stays None, and the assertion fails.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import MOVE, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_non_active_axis_hover_sets_hover_index(qtbot: QtBot, tmp_path: Path) -> None:
    """Low: hovering a NON-active axis sets _hover_axis_index (drives the frame paint).

    Axis 0 is made active; then the cursor hovers axis 1 (non-active). The hover
    must set _hover_axis_index == 1 (which drives _AlignedAxisItem's provisional
    frame). This is real-OS-only because hoverMove needs incremental movement.
    """
    skip_unless_real_display()
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # Place fully on-screen (avoid off-screen cursor clamp, memory
    # gui_realgui_zone_widgetspace_and_offscreen_clamp).
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

    axis = view._y_axes[1]  # the NON-active axis (_AlignedAxisItem)
    gv = view.plot_widget
    dpr = view.devicePixelRatioF()
    w = axis.width()
    h = axis.boundingRect().height()

    def item_to_phys(lx: float, ly: float) -> tuple[int, int]:
        sp = axis.mapToScene(QPointF(lx, ly))
        g = gv.viewport().mapToGlobal(gv.mapFromScene(sp))
        return round(g.x() * dpr), round(g.y() * dpr)

    # Sweep onto the axis-1 interior in small steps until the hover registers.
    gx, gy = item_to_phys(w * 0.5, h * 0.5)
    hovered = False
    for _attempt in range(6):
        for off in range(30, -1, -3):
            at(gx, gy - off, MOVE)
            QApplication.processEvents()
            time.sleep(0.012)
        time.sleep(0.04)
        QApplication.processEvents()
        if view._hover_axis_index == 1:
            hovered = True
            break

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "axis_hover_frame.png")
        )

    assert hovered, (
        "hovering the non-active axis 1 never set _hover_axis_index == 1 — the "
        "provisional hover frame is not being driven. "
        f"got {view._hover_axis_index!r}. screenshot: {tmp_path / 'axis_hover_frame.png'}"
    )
    # Active axis is unchanged by a mere hover (hover is transient, never promoted).
    assert view._active_axis_index == 0, "hover must not change the active axis"
