"""Layer C: the FIRST resize after an axis-move must work (stale-scene-state bug).

Opt-in — run with ``--realgui``. Requires a real display + Windows.

Regression guard for the axis-move → first-resize no-op. Moving an axis launches
``QDrag.exec``, whose Windows OLE modal loop swallows the mouse-release, so
pyqtgraph's ``GraphicsScene.mouseReleaseEvent`` never runs its cleanup. That left
``dragButtons``/``dragItem``/``clickEvents`` stale, and the NEXT press was
misrouted to the (rebuilt-away) source item with ``isStart=False`` — so the first
grip-resize after a move silently did nothing. The fix resets the scene's drag
bookkeeping after ``drag.exec`` returns.

This can only be reproduced with real OS input: the bug lives in pyqtgraph's real
press→move→release state machine, which synthetic events bypass.
"""

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
    drive_qdrag,
    skip_unless_real_display,
    to_phys,
)

pytestmark = pytest.mark.realgui


def test_first_resize_after_axis_move_works(qtbot: QtBot, tmp_path: Path) -> None:
    """Move axis 0 to the outer column, then immediately grip-resize it.

    The resize must take effect on the FIRST attempt (no spurious extra click
    needed). Pre-fix, pyqtgraph's stale post-QDrag drag state misrouted the first
    drag to the deleted source item, so the height stayed put.
    """
    skip_unless_real_display()
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_panel
    from valisync.gui.views.graph_panel_view import _Y_AXIS_FIXED_WIDTH

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
    view.set_active_axis(0)  # axis 0 is the move source AND the resize target
    QApplication.processEvents()

    dpr = view.devicePixelRatioF()

    # ── Move axis 0 (inner col 1) → outer col 0 via real QDrag ──────────────
    src = view._y_axes[0].sceneBoundingRect()
    s_x, s_y = to_phys(view, src.x() + 2, src.center().y())  # left-edge frame band
    tgt = view.mapToGlobal(QPoint(_Y_AXIS_FIXED_WIDTH // 2, view.height() // 2))
    t_x, t_y = round(tgt.x() * dpr), round(tgt.y() * dpr)
    m_x, m_y = (s_x + t_x) // 2, (s_y + t_y) // 2
    drive_qdrag(
        (s_x, s_y),
        [(m_x, m_y), (t_x, t_y)],
        done=lambda: view.vm.axes[0].column == 0,
    )
    for _ in range(5):
        QApplication.processEvents()

    # Guard: the move itself must have succeeded, else a resize failure below
    # would be misattributed. (If this fails, fix the move test first.)
    assert view.vm.axes[0].column == 0, (
        f"axis 0 did not move to column 0 (got col {view.vm.axes[0].column}); "
        f"resize result below would be meaningless. Screens: {tmp_path}"
    )
    assert view._active_axis_index == 0, "axis 0 lost active status across the move"
    h0_before = view.vm.axes[0].height_ratio
    # ② honest gate: capture the RENDERED height of axis 0's SPINE (not viewbox).
    # The multi-axis layout is region-based: _view_boxes[0] is the master ViewBox
    # spanning the full plot height (fixed, ~537 for 800x600) -- it never shrinks.
    # Only _y_axes[i].setGeometry(strip) tracks height_ratio*R.height() per axis.
    spine0_h_before = view._y_axes[0].sceneBoundingRect().height()

    # ── Immediately grip-resize axis 0 (still active) — FIRST attempt only ──
    # Small uniform steps keep the threshold-crossing inside the thin grip band.
    spine = view._y_axes[0].sceneBoundingRect()
    R = view._view_boxes[0].sceneBoundingRect()
    gx, gy = to_phys(view, spine.center().x(), spine.bottom() - 2)
    tx, ty = to_phys(view, spine.center().x(), R.y() + 0.30 * R.height())
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    dy = ty - gy
    n = max(2, (abs(dy) + 7) // 8)
    for k in range(1, n + 1):
        at(gx, gy + dy * k // n, MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    at(tx, ty, LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "after_move_resize.png")
        )

    h0_after = view.vm.axes[0].height_ratio
    spine0_h_after = view._y_axes[0].sceneBoundingRect().height()
    # ② honest gate: the RENDERED spine must actually shrink (~0.5→0.30, ~40% drop).
    # _y_axes[0].sceneBoundingRect().height() == height_ratio * R.height(), which is
    # set by _sync_overlay_geometry. If the resize was a paint no-op the spine stays put.
    assert spine0_h_after < spine0_h_before * 0.80, (
        f"axis 0 spine did not shrink on screen: {spine0_h_after:.1f} "
        f"(was {spine0_h_before:.1f}) — VM ratio changed but the paint may be a no-op. "
        f"Screens: {tmp_path}"
    )
    assert h0_after < h0_before - 0.05, (
        f"FIRST resize after a move was a no-op: height stayed {h0_after} "
        f"(was {h0_before}). Stale post-QDrag scene state misrouted the drag. "
        f"Screens: {tmp_path}"
    )
    assert h0_after == pytest.approx(0.30, abs=0.07), (
        f"resize did not track the cursor to ~0.30 (got {h0_after}). "
        f"Screens: {tmp_path}"
    )
