"""Layer C: real-OS grip drag resizes only the active axis (model B)."""

from __future__ import annotations

import contextlib
import ctypes
import sys
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.realgui
_MOVE, _LDOWN, _LUP = 0x0001, 0x0002, 0x0004


def test_grip_drag_resizes_only_active_axis(qtbot: QtBot, tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("real OS input is Windows-only")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    if QGuiApplication.platformName() == "offscreen":
        pytest.skip(
            "requires a real display — run: uv run pytest --realgui tests/realgui/"
        )
    from tests.gui._panel_factory import make_two_axis_panel

    user32 = ctypes.windll.user32
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

    view.set_active_axis(0)  # activate top axis
    QApplication.processEvents()

    R = view._view_boxes[0].sceneBoundingRect()

    def strip(i: int) -> tuple[float, float]:
        r = view._y_axes[i].sceneBoundingRect()
        return ((r.y() - R.y()) / R.height(), r.height() / R.height())

    top0, h0 = strip(0)
    top1, h1 = strip(1)

    # bottom grip of axis 0 = bottom-centre of its spine
    spine0 = view._y_axes[0].sceneBoundingRect()
    grip_scene = QPoint(int(spine0.center().x()), int(spine0.bottom() - 2))
    vp = view.plot_widget.mapFromScene(grip_scene)
    g = view.plot_widget.viewport().mapToGlobal(vp)
    dpr = view.devicePixelRatioF()
    gx, gy = round(g.x() * dpr), round(g.y() * dpr)

    def at(x: float, y: float, f: int) -> None:
        user32.SetCursorPos(int(x), int(y))
        user32.mouse_event(f, 0, 0, 0, 0)

    # Drag the bottom grip UP to SHRINK axis 0. Growing it by dragging DOWN is
    # correctly impossible here: model B never pushes the neighbour, and with two
    # contiguous axes there is no gap below axis 0 to grow into.
    at(gx, gy, _LDOWN)
    time.sleep(0.05)
    for k in range(1, 6):  # drag UP ~60px
        at(gx, gy - k * 12, _MOVE)
        QApplication.processEvents()
        time.sleep(0.03)
    at(gx, gy - 60, _LUP)
    for _ in range(4):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "after_resize.png")
        )

    ntop0, nh0 = strip(0)
    ntop1, nh1 = strip(1)
    assert nh0 < h0 - 0.03, (
        f"active axis 0 did not shrink (screens: {tmp_path})"
    )  # rendered
    assert ntop0 == pytest.approx(top0, abs=0.02)  # axis 0 top edge anchored
    # model B: the neighbour is untouched in BOTH position and height; the gap absorbs it.
    assert ntop1 == pytest.approx(top1, abs=0.02), "neighbour moved (model B violated)"
    assert nh1 == pytest.approx(h1, abs=0.02), (
        "neighbour height changed (model B violated)"
    )
