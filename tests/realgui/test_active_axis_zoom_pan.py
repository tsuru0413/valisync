"""Layer C: inner drag = range-select zoom-in, outer drag = pan, per-zone cursor.

All gestures are accepted only on the ACTIVE axis and are driven by real OS mouse
input (no QDrag — these paths use pyqtgraph scene drags, so no OLE modal loop).
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
import time
from typing import TYPE_CHECKING

import pytest
from pytestqt.qtbot import QtBot

if TYPE_CHECKING:
    from valisync.gui.views.graph_panel_view import GraphPanelView

pytestmark = pytest.mark.realgui
_MOVE, _LDOWN, _LUP = 0x0001, 0x0002, 0x0004


def _skip_unless_real_display() -> None:
    if sys.platform != "win32":
        pytest.skip("real OS input is Windows-only")
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() == "offscreen":
        pytest.skip(
            "requires a real display — run: uv run pytest --realgui tests/realgui/"
        )


def _active_panel(qtbot: QtBot) -> GraphPanelView:
    """Build a two-axis panel, show it on the real screen, activate axis 0."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 800, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    view.set_active_axis(0)
    QApplication.processEvents()
    return view


def _to_phys(view: GraphPanelView, sx: float, sy: float) -> tuple[int, int]:
    """Map a SCENE point to a physical-pixel global coordinate for SetCursorPos."""
    from PySide6.QtCore import QPoint

    vp = view.plot_widget.mapFromScene(QPoint(int(sx), int(sy)))
    g = view.plot_widget.viewport().mapToGlobal(vp)
    dpr = view.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _at(x: float, y: float, flag: int) -> None:
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(flag, 0, 0, 0, 0)


def test_inner_drag_zooms_in_on_active_axis(qtbot: QtBot, tmp_path) -> None:
    _skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _active_panel(qtbot)
    lo0, hi0 = view._y_axes[0].range
    before = hi0 - lo0

    spine = view._y_axes[0].sceneBoundingRect()
    inner_x = spine.x() + spine.width() * 0.78  # right half = plot-side = zoom zone
    x0, ya = _to_phys(view, inner_x, spine.y() + spine.height() * 0.30)
    _, yb = _to_phys(view, inner_x, spine.y() + spine.height() * 0.70)

    _at(x0, ya, _LDOWN)
    time.sleep(0.05)
    for yy in (ya + (yb - ya) // 3, ya + 2 * (yb - ya) // 3, yb):
        _at(x0, yy, _MOVE)
        QApplication.processEvents()
        time.sleep(0.04)
    _at(x0, yb, _LUP)
    for _ in range(4):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "after_zoom.png")
        )

    lo1, hi1 = view._y_axes[0].range
    after = hi1 - lo1
    assert after < before * 0.9, f"inner drag did not zoom in (screens: {tmp_path})"


def test_outer_drag_pans_on_active_axis(qtbot: QtBot, tmp_path) -> None:
    _skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _active_panel(qtbot)
    lo0, hi0 = view._y_axes[0].range
    before_span = hi0 - lo0
    before_center = (hi0 + lo0) / 2.0

    spine = view._y_axes[0].sceneBoundingRect()
    # Pan zone = left interior, now lx∈[FRAME, w/2]. Grab at 0.25 (well clear of the
    # widened 8 px move-frame on the left edge, which would otherwise launch a move
    # QDrag); the cursor test pins this same fraction as OpenHand/pan.
    outer_x = spine.x() + spine.width() * 0.25  # left = window-edge side = pan zone
    x0, ya = _to_phys(view, outer_x, spine.y() + spine.height() * 0.40)
    _, yb = _to_phys(view, outer_x, spine.y() + spine.height() * 0.75)

    _at(x0, ya, _LDOWN)
    time.sleep(0.05)
    for yy in (ya + (yb - ya) // 3, ya + 2 * (yb - ya) // 3, yb):
        _at(x0, yy, _MOVE)
        QApplication.processEvents()
        time.sleep(0.04)
    _at(x0, yb, _LUP)
    for _ in range(4):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "after_pan.png"))

    lo1, hi1 = view._y_axes[0].range
    after_span = hi1 - lo1
    after_center = (hi1 + lo1) / 2.0
    assert after_span == pytest.approx(before_span, rel=0.1), "pan changed the span"
    assert abs(after_center - before_center) > before_span * 0.05, (
        f"outer drag did not pan (screens: {tmp_path})"
    )


def test_cursor_changes_per_zone(qtbot: QtBot) -> None:
    """Hovering each zone of the active axis sets a zone-specific cursor on the AxisItem."""
    _skip_unless_real_display()
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import Qt
    from PySide6.QtWidgets import QApplication

    view = _active_panel(qtbot)
    axis = view._y_axes[0]
    gv = view.plot_widget
    dpr = view.devicePixelRatioF()
    # Use the SAME coordinate system classify_axis_zone reads (item width / bounding
    # height), not sceneBoundingRect, so chosen points land in the intended zones.
    w = axis.width()
    h = axis.boundingRect().height()

    def item_to_phys(lx: float, ly: float) -> tuple[int, int]:
        sp = axis.mapToScene(QPointF(lx, ly))
        g = gv.viewport().mapToGlobal(gv.mapFromScene(sp))
        return round(g.x() * dpr), round(g.y() * dpr)

    def hover_shape(lx: float, ly: float) -> Qt.CursorShape:
        gx, gy = item_to_phys(lx, ly)
        # pyqtgraph's hover dispatch needs genuine incremental movement, not a single
        # jump (one-shot SetCursorPos delivers no hoverMoveEvent). Sweep onto the point
        # in small steps so a hoverMove lands on it and sets that zone's cursor. Retry
        # the sweep until a cursor is actually delivered — the first hover after a fresh
        # window can be dropped, which makes the read order-dependent otherwise. This
        # only waits for *delivery*; the specific shape is still asserted by the caller.
        for _attempt in range(6):
            for off in range(30, -1, -3):
                _at(gx, gy - off, _MOVE)
                QApplication.processEvents()
                time.sleep(0.012)
            time.sleep(0.04)
            QApplication.processEvents()
            if axis.cursor().shape() != Qt.CursorShape.ArrowCursor:
                break
        return axis.cursor().shape()

    # grip (top-centre) → SizeVer ; frame (left border, mid) → SizeAll ;
    # inner/right interior → Cross ; outer/left interior → OpenHand.
    # Interior points keep a wide margin from the frame border so small input-to-scene
    # rounding (1.25 DPI) cannot flip the classified zone.
    assert hover_shape(w / 2.0, 4) == Qt.CursorShape.SizeVerCursor
    assert hover_shape(2, h / 2.0) == Qt.CursorShape.SizeAllCursor
    assert hover_shape(w * 0.7, h / 2.0) == Qt.CursorShape.CrossCursor
    assert hover_shape(w * 0.25, h / 2.0) == Qt.CursorShape.OpenHandCursor
