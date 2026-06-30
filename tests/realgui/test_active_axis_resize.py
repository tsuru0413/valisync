"""Layer C: real-OS grip drag resizes only the active axis (model B)."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    MOVE,
    at,
    skip_unless_real_display,
    to_phys,
)

pytestmark = pytest.mark.realgui


def test_grip_drag_resizes_only_active_axis(qtbot: QtBot, tmp_path: Path) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import QPoint, Qt
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

    # Drag the bottom grip UP to SHRINK axis 0. Growing it by dragging DOWN is
    # correctly impossible here: model B never pushes the neighbour, and with two
    # contiguous axes there is no gap below axis 0 to grow into.
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    for k in range(1, 6):  # drag UP ~60px
        at(gx, gy - k * 12, MOVE)
        QApplication.processEvents()
        time.sleep(0.03)
    at(gx, gy - 60, LUP)
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


def test_grips_track_cursor_to_target(qtbot: QtBot, tmp_path: Path) -> None:
    """Layer C regression guard: each grip edge tracks the cursor to its TARGET panel
    ratio (proportional, not inflated by the axis's own height) and does not collapse.

    Catches the spine-height scaling bug (edge moved ~1/height_ratio too fast →
    cursor/edge mismatch + runaway-to-minimum) and the top-grip coordinate-frame
    feedback (flicker/collapse). The older 'shrank by > 0.03' assertion passed even
    when the axis collapsed; these pin the edge to the cursor's absolute position.
    """
    skip_unless_real_display()
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
    R = view._view_boxes[0].sceneBoundingRect()

    def strip(i: int) -> tuple[float, float]:
        r = view._y_axes[i].sceneBoundingRect()
        return ((r.y() - R.y()) / R.height(), r.height() / R.height())

    def drag_grip_to(axis_idx: int, edge: str, target_ratio: float) -> None:
        view.set_active_axis(axis_idx)
        QApplication.processEvents()
        spine = view._y_axes[axis_idx].sceneBoundingRect()
        grip_x = spine.center().x()
        grip_y = spine.top() + 2 if edge == "top" else spine.bottom() - 2
        gx, gy = to_phys(view, grip_x, grip_y)
        tx, ty = to_phys(view, grip_x, R.y() + target_ratio * R.height())
        at(gx, gy, LDOWN)
        time.sleep(0.05)
        # Move to the target in small uniform steps (~8 phys px each). The zone is
        # classified once, when pyqtgraph crosses its drag threshold; a single large
        # first jump would cross it OUTSIDE the ~12px grip band and mis-route the
        # gesture as zoom/pan. Small steps keep that first crossing inside the grip.
        dy = ty - gy
        n = max(2, (abs(dy) + 7) // 8)
        for k in range(1, n + 1):
            at(gx, gy + dy * k // n, MOVE)
            QApplication.processEvents()
            time.sleep(0.02)
        at(tx, ty, LUP)
        for _ in range(4):
            QApplication.processEvents()

    # Bottom grip of axis 0: drag its bottom edge UP to ratio 0.35 → height ~0.35.
    drag_grip_to(0, "bottom", 0.35)
    _, h0 = strip(0)
    assert h0 == pytest.approx(0.35, abs=0.05), (
        f"bottom grip did not track cursor to 0.35 (got {h0}). Screens: {tmp_path}"
    )
    assert h0 > 0.2, f"axis 0 collapsed instead of tracking the cursor (got {h0})"

    # Top grip of axis 1: drag its top edge DOWN to ratio 0.65 → top ~0.65, height ~0.35.
    drag_grip_to(1, "top", 0.65)
    top1, h1 = strip(1)
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "grips.png"))
    assert top1 == pytest.approx(0.65, abs=0.05), (
        f"top grip did not track cursor to 0.65 (got top={top1}). Screens: {tmp_path}"
    )
    assert h1 == pytest.approx(0.35, abs=0.05), f"axis 1 height wrong (got {h1})"
