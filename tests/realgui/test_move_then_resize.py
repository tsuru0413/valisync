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
import ctypes
import sys
import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.realgui
_MOVE, _LDOWN, _LUP = 0x0001, 0x0002, 0x0004
_KEYUP, _VK_ESC = 0x0002, 0x1B


def test_first_resize_after_axis_move_works(qtbot: QtBot, tmp_path: Path) -> None:
    """Move axis 0 to the outer column, then immediately grip-resize it.

    The resize must take effect on the FIRST attempt (no spurious extra click
    needed). Pre-fix, pyqtgraph's stale post-QDrag drag state misrouted the first
    drag to the deleted source item, so the height stayed put.
    """
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
    from valisync.gui.views.graph_panel_view import _Y_AXIS_FIXED_WIDTH

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
    view.set_active_axis(0)  # axis 0 is the move source AND the resize target
    QApplication.processEvents()

    dpr = view.devicePixelRatioF()

    def at(x: float, y: float, f: int) -> None:
        user32.SetCursorPos(int(x), int(y))
        user32.mouse_event(f, 0, 0, 0, 0)

    def to_phys(sx: float, sy: float) -> tuple[int, int]:
        vp = view.plot_widget.mapFromScene(QPoint(int(sx), int(sy)))
        g = view.plot_widget.viewport().mapToGlobal(vp)
        return round(g.x() * dpr), round(g.y() * dpr)

    # ── Move axis 0 (inner col 1) → outer col 0 via real QDrag (bg-thread drive) ──
    # QDrag.exec enters Windows' OLE modal loop, which does NOT pump Qt timers, so
    # the move/release sequence must come from a real OS thread on wall-clock time.
    src = view._y_axes[0].sceneBoundingRect()
    s_x, s_y = to_phys(src.x() + 2, src.center().y())  # left-edge frame band
    tgt = view.mapToGlobal(QPoint(_Y_AXIS_FIXED_WIDTH // 2, view.height() // 2))
    t_x, t_y = round(tgt.x() * dpr), round(tgt.y() * dpr)
    m_x, m_y = (s_x + t_x) // 2, (s_y + t_y) // 2
    finished = threading.Event()

    def drive() -> None:
        time.sleep(0.3)
        at(s_x, s_y, _LDOWN)
        time.sleep(0.1)
        at(s_x, s_y + 15, _MOVE)  # vertical → start in frame zone → QDrag.exec
        time.sleep(0.2)
        at(m_x, m_y, _MOVE)
        time.sleep(0.2)
        at(t_x, t_y, _MOVE)
        time.sleep(0.3)
        at(t_x, t_y, _LUP)  # drop
        if not finished.wait(timeout=3.0):  # watchdog: never hang the machine
            user32.keybd_event(_VK_ESC, 0, 0, 0)
            user32.keybd_event(_VK_ESC, 0, _KEYUP, 0)
            user32.mouse_event(_LUP, 0, 0, 0, 0)

    worker = threading.Thread(target=drive, daemon=True)
    worker.start()
    deadline = time.monotonic() + 15.0
    while worker.is_alive() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
        if view.vm.axes[0].column == 0:
            break
    finished.set()
    worker.join(timeout=4.0)
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

    # ── Immediately grip-resize axis 0 (still active) — FIRST attempt only ──
    # Small uniform steps keep the threshold-crossing inside the thin grip band.
    spine = view._y_axes[0].sceneBoundingRect()
    R = view._view_boxes[0].sceneBoundingRect()
    gx, gy = to_phys(spine.center().x(), spine.bottom() - 2)
    tx, ty = to_phys(spine.center().x(), R.y() + 0.30 * R.height())
    at(gx, gy, _LDOWN)
    time.sleep(0.05)
    dy = ty - gy
    n = max(2, (abs(dy) + 7) // 8)
    for k in range(1, n + 1):
        at(gx, gy + dy * k // n, _MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    at(tx, ty, _LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "after_move_resize.png")
        )

    h0_after = view.vm.axes[0].height_ratio
    assert h0_after < h0_before - 0.05, (
        f"FIRST resize after a move was a no-op: height stayed {h0_after} "
        f"(was {h0_before}). Stale post-QDrag scene state misrouted the drag. "
        f"Screens: {tmp_path}"
    )
    assert h0_after == pytest.approx(0.30, abs=0.07), (
        f"resize did not track the cursor to ~0.30 (got {h0_after}). "
        f"Screens: {tmp_path}"
    )
