"""Layer C: real-OS-input GUI test for the multi-column axis-move drag.

Opt-in — run with ``--realgui``. Requires a real display + Windows: it presses
the physical left mouse button over a Y-axis strip in the inner column (column 1)
of a 2-column GraphPanelView and drags it to the empty outer column (column 0) via
Win32 ``mouse_event``, then asserts the axis relocated to column 0 in the ViewModel.

This is the only tier that exercises the full OS → pyqtgraph → QDrag → dropEvent
chain that synthetic events cannot:

  1. Real WM_LBUTTONDOWN on the inner-column AxisItem.
  2. WM_MOUSEMOVE events cross pyqtgraph's drag threshold → ``_AlignedAxisItem.
     mouseDragEvent`` fires with ``isStart()==True``.
  3. ``QDrag.exec`` starts (blocking, with its own nested Qt event loop) —
     QTimers keep firing inside it, so the move/release sequence continues.
  4. More WM_MOUSEMOVE events drive the view's ``dragMoveEvent`` (drop feedback).
  5. WM_LBUTTONUP → ``dropEvent`` on the view → ``move_axis_to_column`` on the VM.

Excluded from the default run and CI — see ``docs/gui-testing-layers.md`` (Layer C).

Run deliberately (e.g. before release, or after touching axis-move / drag routing)
on a Windows machine with a real display::

    uv run pytest --realgui tests/realgui/

Note: this hijacks the mouse cursor for ~2 s while it runs. Real-drag behaviour
is unverified in headless / offscreen mode; confirm with the above command on a
real Windows display.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.realgui

# Win32 mouse_event flag constants
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004


def test_axis_drag_from_inner_column_to_outer_column(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Drag a Y-axis from inner column (col 1) to the empty outer column (col 0).

    Verifies the full axis-move drag path end-to-end:
      * real left-press on the AxisItem in the inner Y-axis band
      * WM_MOUSEMOVE events cross pyqtgraph's 4-px threshold →
        ``_AlignedAxisItem.mouseDragEvent`` starts ``QDrag.exec``
      * moves drive ``dragMoveEvent`` (column-highlight / insertion-line feedback)
      * release over the outer-column band → ``dropEvent`` →
        ``vm.move_axis_to_column(0, 0)``
      * ViewModel reflects ``vm.axes[0].column == 0``
    """
    if sys.platform != "win32":
        pytest.skip("real OS drag uses Win32 mouse_event (Windows-only)")

    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    if QGuiApplication.platformName() == "offscreen":
        pytest.skip(
            "requires a real display — run: uv run pytest --realgui tests/realgui/"
        )

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import (
        _Y_AXIS_FIXED_WIDTH,
        GraphPanelView,
    )

    user32 = ctypes.windll.user32

    # ─── Session with two signals ──────────────────────────────────────────────
    # A tiny CSV is sufficient: the axis-move gesture only needs two axes to exist.

    def _write_tiny_csv(path: Path) -> Path:
        lines = ["t,s1,s2"]
        for i in range(50):
            t = i * 0.01
            lines.append(f"{t:.3f},{float(i % 50):.1f},{float((i * 2) % 50):.1f}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    csv = _write_tiny_csv(tmp_path / "data.csv")
    session = Session()
    session.load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=2,
            has_header=True,
        ),
    )
    # Sort for deterministic order; both keys are valid drag sources.
    signal_keys = sorted(s.name for s in session.signals())
    k0, k1 = signal_keys[0], signal_keys[1]

    # ─── ViewModel: column_count=2, two axes stacked in the inner column ───────
    # GraphPanelVM defaults to column_count=2 with one placeholder axis in
    # column 1 (inner).  Reusing the placeholder for k0 and creating a new axis
    # for k1 produces two equal-height regions, both in column 1.

    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(k0, 0)  # fills the placeholder → axis 0, col 1, top half
    vm.create_new_axis(k1)  # axis 1, col 1, bottom half

    assert len(vm.axes) == 2
    assert all(a.column == vm.column_count - 1 for a in vm.axes), (
        "setup error: both axes must start in the inner column before the drag"
    )

    # ─── View: fixed geometry so cursor math is deterministic ─────────────────

    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 800, 600)
    view.show()
    qtbot.waitExposed(view)
    # Two processEvents passes let the pyqtgraph GraphicsLayout compute its
    # item geometry before we query sceneBoundingRect().
    QApplication.processEvents()
    QApplication.processEvents()
    # Wait for the first AxisItem's scene rect to be non-zero (layout settled).
    qtbot.waitUntil(
        lambda: view._y_axes[0].sceneBoundingRect().width() > 0,  # type: ignore[attr-defined]
        timeout=3000,
    )

    # ─── DPI conversion factor (logical → physical pixels) ────────────────────
    # Qt coordinates are logical pixels.  Win32 SetCursorPos and mouse_event
    # require physical pixels on HiDPI displays.

    dpr = view.devicePixelRatioF()

    # ─── Source: centre of vm.axes[0]'s AxisItem in the inner column ──────────
    # _y_axes[0] is the _AlignedAxisItem for vm.axes[0] (column 1, top half).
    # sceneBoundingRect() gives the bounding rect in pyqtgraph scene coords;
    # mapFromScene converts to the plot_widget's viewport pixel coords.

    src_item = view._y_axes[0]  # type: ignore[attr-defined]
    scene_center = src_item.sceneBoundingRect().center()
    src_vp = view.plot_widget.mapFromScene(scene_center).toPoint()  # type: ignore[attr-defined]
    src_global = view.plot_widget.viewport().mapToGlobal(src_vp)  # type: ignore[attr-defined]
    src_phys_x = round(src_global.x() * dpr)
    src_phys_y = round(src_global.y() * dpr)

    # ─── Target: centre of the empty outer column 0 band ─────────────────────
    # Column 0 occupies x ∈ [0, _Y_AXIS_FIXED_WIDTH) in view widget space.
    # Dropping at x = W//2 makes _axis_drop_target() return column=0:
    #   col = int(W//2 // W) = 0.

    tgt_logi = view.mapToGlobal(QPoint(_Y_AXIS_FIXED_WIDTH // 2, view.height() // 2))
    tgt_phys_x = round(tgt_logi.x() * dpr)
    tgt_phys_y = round(tgt_logi.y() * dpr)

    # Intermediate stop halfway between source and target for a smoother path.
    mid_phys_x = (src_phys_x + tgt_phys_x) // 2
    mid_phys_y = (src_phys_y + tgt_phys_y) // 2

    # ─── Event sequence ───────────────────────────────────────────────────────

    captured: dict[str, object] = {}
    loop = QEventLoop()

    def do_press() -> None:
        user32.SetCursorPos(int(src_phys_x), int(src_phys_y))
        user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    def do_move_threshold() -> None:
        # Cross pyqtgraph's default 4-px drag threshold.  Moving 15 physical
        # pixels guarantees > 4 logical pixels even at 2x DPI (15 / 2 = 7.5).
        user32.SetCursorPos(int(src_phys_x + 15), int(src_phys_y))
        user32.mouse_event(_MOUSEEVENTF_MOVE, 0, 0, 0, 0)

    def do_move_mid() -> None:
        user32.SetCursorPos(int(mid_phys_x), int(mid_phys_y))
        user32.mouse_event(_MOUSEEVENTF_MOVE, 0, 0, 0, 0)

    def do_move_to_target() -> None:
        user32.SetCursorPos(int(tgt_phys_x), int(tgt_phys_y))
        user32.mouse_event(_MOUSEEVENTF_MOVE, 0, 0, 0, 0)

    def do_screenshot_mid() -> None:
        # QDrag.exec runs its own nested event loop; QTimer shots continue to
        # fire inside it.  Grab the full screen while the drag is in-flight to
        # capture the drop-feedback overlay (column highlight / insertion line /
        # dimmed source axis).
        QApplication.primaryScreen().grabWindow(0).save(  # type: ignore[attr-defined]
            str(tmp_path / "mid_drag.png")
        )

    def do_release() -> None:
        user32.SetCursorPos(int(tgt_phys_x), int(tgt_phys_y))
        user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def do_screenshot_after() -> None:
        # dropEvent has been called; view.refresh() has updated the layout.
        # Snapshot the VM state and grab a post-drag screenshot.
        QApplication.primaryScreen().grabWindow(0).save(  # type: ignore[attr-defined]
            str(tmp_path / "after_drag.png")
        )
        captured["column"] = vm.axes[0].column
        captured["n_axes"] = len(vm.axes)
        loop.quit()

    # Timings (ms from loop.exec start):
    #   200  - press at source
    #   400  - small threshold move (ensures pyqtgraph sees a drag, not a click)
    #   600  - move to midpoint
    #   800  - move to target (inside QDrag.exec nested loop at this point)
    #   900  - mid-drag screenshot
    #   1000 - release at target, dropEvent fires, move_axis_to_column called
    #   1500 - post-drop screenshot + capture VM state
    #   6000 - safety net quit (if something stalls)
    QTimer.singleShot(200, do_press)
    QTimer.singleShot(400, do_move_threshold)
    QTimer.singleShot(600, do_move_mid)
    QTimer.singleShot(800, do_move_to_target)
    QTimer.singleShot(900, do_screenshot_mid)
    QTimer.singleShot(1000, do_release)
    QTimer.singleShot(1500, do_screenshot_after)
    QTimer.singleShot(6000, loop.quit)  # safety net

    loop.exec()

    # ─── Assertions ───────────────────────────────────────────────────────────
    # After the drag: axis 0 (k0) must have relocated to outer column 0.
    # The panel must still hold exactly 2 axes (axis 1 stays in column 1).

    assert captured.get("column") == 0, (
        "axis did not relocate to outer column 0 after real-OS drag; "
        f"got column={captured.get('column')!r}. "
        f"Screenshots saved to {tmp_path}"
    )
    assert captured.get("n_axes") == 2, (
        f"expected 2 axes after drag, got n_axes={captured.get('n_axes')!r}"
    )
