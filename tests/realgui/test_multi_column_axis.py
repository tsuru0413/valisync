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
  3. ``QDrag.exec`` starts and blocks the GUI thread inside Windows' OLE
     ``DoDragDrop`` modal loop.  That loop does NOT pump Qt single-shot timers,
     so the move/release sequence is injected from a BACKGROUND OS THREAD on
     wall-clock time (real ``mouse_event`` input drives the modal loop).  Driving
     it from ``QTimer`` instead would stall forever — the original bug.
  4. More WM_MOUSEMOVE events drive the view's ``dragMoveEvent`` (drop feedback).
  5. WM_LBUTTONUP → ``dropEvent`` on the view → ``move_axis_to_column`` on the VM.

A watchdog (ESC + LEFTUP after 3 s) guarantees the drag can never hang the
machine even if the synthetic drop fails to complete.

Excluded from the default run and CI — see ``docs/gui-testing-layers.md`` (Layer C).

Run deliberately (e.g. before release, or after touching axis-move / drag routing)
on a Windows machine with a real display::

    uv run pytest --realgui tests/realgui/

Note: this hijacks the mouse cursor for ~2 s while it runs. Real-drag behaviour
is unverified in headless / offscreen mode; confirm with the above command on a
real Windows display.
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

# Win32 input constants
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_KEYEVENTF_KEYUP = 0x0002
_VK_ESCAPE = 0x1B


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
      * heights are preserved: moved axis keeps ~0.5, inner remainder stays at
        top 0.5 with a blank gap above (no equal-split on move)
    """
    if sys.platform != "win32":
        pytest.skip("real OS drag uses Win32 mouse_event (Windows-only)")

    from PySide6.QtCore import QPoint, Qt
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

    # ─── View: a thin capturing subclass ──────────────────────────────────────
    # Inherits all drag/drop behaviour unchanged; it only adds two harness side
    # effects so we can observe the *real* path: (1) grab a screenshot from
    # inside dragMoveEvent — the GUI thread, while the drag is live, is the only
    # safe moment to capture the drop-feedback overlay — and (2) flag when
    # dropEvent actually fires so the main loop knows the drag resolved.

    class _CapturingView(GraphPanelView):
        mid_path: str = ""
        drop_seen: bool = False

        def dragMoveEvent(self, ev: object) -> None:  # type: ignore[override]
            super().dragMoveEvent(ev)  # type: ignore[arg-type]
            if self.mid_path:
                with contextlib.suppress(Exception):
                    QApplication.primaryScreen().grabWindow(0).save(self.mid_path)

        def dropEvent(self, ev: object) -> None:  # type: ignore[override]
            super().dropEvent(ev)  # type: ignore[arg-type]
            self.drop_seen = True

    view = _CapturingView(vm)
    view.mid_path = str(tmp_path / "mid_drag.png")
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
    # mapFromScene converts to the plot_widget's viewport pixel coords (QPoint).
    src_item = view._y_axes[0]  # type: ignore[attr-defined]
    scene_center = src_item.sceneBoundingRect().center()
    src_vp = view.plot_widget.mapFromScene(scene_center)  # type: ignore[attr-defined]
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

    # ─── Real-OS gesture driven from a BACKGROUND THREAD ──────────────────────
    # WHY a thread (not QTimer): QDrag.exec() enters Windows' OLE DoDragDrop
    # modal loop, which does NOT pump Qt single-shot timers, so QTimer-driven
    # moves/release stall forever (the original bug — see module docstring).  A
    # plain OS thread issues real mouse_event() input on wall-clock time, which
    # DOES drive the modal loop, so the drop completes.
    finished = threading.Event()  # main → worker: the gesture resolved

    def _at(x: int, y: int, flag: int) -> None:
        user32.SetCursorPos(int(x), int(y))
        user32.mouse_event(flag, 0, 0, 0, 0)

    def drive() -> None:
        time.sleep(0.3)  # let the main thread reach its event pump
        _at(src_phys_x, src_phys_y, _MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.1)
        # Cross pyqtgraph's 4-px threshold → QDrag.exec starts on the main thread.
        _at(src_phys_x + 15, src_phys_y, _MOUSEEVENTF_MOVE)
        time.sleep(0.2)
        _at(mid_phys_x, mid_phys_y, _MOUSEEVENTF_MOVE)
        time.sleep(0.2)
        _at(tgt_phys_x, tgt_phys_y, _MOUSEEVENTF_MOVE)
        time.sleep(0.3)  # let dragMoveEvent render feedback + grab the mid shot
        _at(tgt_phys_x, tgt_phys_y, _MOUSEEVENTF_LEFTUP)  # drop
        # Watchdog: if the drop did not unblock the main thread within 3 s, the
        # drag is stuck — cancel with ESC and force the button up.
        if not finished.wait(timeout=3.0):
            user32.keybd_event(_VK_ESCAPE, 0, 0, 0)
            user32.keybd_event(_VK_ESCAPE, 0, _KEYEVENTF_KEYUP, 0)
            user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    worker = threading.Thread(target=drive, daemon=True)
    worker.start()

    # Pump the GUI thread until the drop fires or the worker gives up.
    # processEvents() blocks inside QDrag.exec while the drag is live; the
    # worker's LEFTUP (or watchdog ESC) is what lets it return.
    deadline = time.monotonic() + 15.0
    while not view.drop_seen and worker.is_alive() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    finished.set()  # release the worker's watchdog wait
    worker.join(timeout=4.0)

    # Settle the layout, then grab the post-drop screenshot on the GUI thread.
    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "after_drag.png")
        )

    # ─── Assertions ───────────────────────────────────────────────────────────
    # After the drag: axis 0 (k0) must have relocated to outer column 0, and the
    # panel must still hold exactly 2 axes (axis 1 stays in column 1).
    assert view.drop_seen, (
        "no dropEvent fired — the real-OS drag never completed (watchdog "
        f"cancelled it). Screenshots saved to {tmp_path}"
    )
    assert vm.axes[0].column == 0, (
        "axis did not relocate to outer column 0 after real-OS drag; "
        f"got column={vm.axes[0].column!r}. Screenshots saved to {tmp_path}"
    )
    assert len(vm.axes) == 2, f"expected 2 axes after drag, got {len(vm.axes)}"
    # Height preservation (root fix): the moved axis keeps its height (~0.5) —
    # it must NOT be equal-split to full height — and the inner column's
    # remaining axis keeps its absolute position with a blank gap at the top.
    assert vm.axes[0].height_ratio == pytest.approx(0.5, abs=0.05), (
        "moved axis should keep its height (~0.5), not grow to full height; "
        f"got {vm.axes[0].height_ratio!r}. Screenshots saved to {tmp_path}"
    )
    inner_axes = [a for a in vm.axes if a.column == 1]
    assert len(inner_axes) == 1, (
        f"expected 1 axis in inner column, got {len(inner_axes)}. "
        f"Screenshots saved to {tmp_path}"
    )
    assert inner_axes[0].top_ratio == pytest.approx(0.5, abs=0.05), (
        "inner remaining axis should keep its absolute top (blank gap above); "
        f"got top_ratio={inner_axes[0].top_ratio!r}. Screenshots saved to {tmp_path}"
    )
    assert inner_axes[0].height_ratio == pytest.approx(0.5, abs=0.05)
