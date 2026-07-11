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

Excluded from the default run and CI — see ``.claude/skills/gui-verify/`` (Layer C).

Run deliberately (e.g. before release, or after touching axis-move / drag routing)
on a Windows machine with a real display::

    uv run pytest --realgui tests/realgui/

Note: this hijacks the mouse cursor for ~2 s while it runs. Real-drag behaviour
is unverified in headless / offscreen mode; confirm with the above command on a
real Windows display.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import drive_qdrag, skip_unless_real_display

pytestmark = pytest.mark.realgui


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
      * rendered geometry (spine strips + column band), not VM values: moved
        axis spine paints in the outer-column 0 band at top ~0.0 with height ~0.5;
        inner remainder spine paints in column 1 at top ~0.5 (blank gap above)
    """
    skip_unless_real_display()

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import (
        _Y_AXIS_FIXED_WIDTH,
        GraphPanelView,
    )

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
        # M7: feedback state captured inside dragMoveEvent (GUI thread, safe).
        mid_line_visible: bool = False
        mid_highlight_visible: bool = False
        mid_source_opacity: float = 1.0

        def dragMoveEvent(self, ev: object) -> None:  # type: ignore[override]
            super().dragMoveEvent(ev)  # type: ignore[arg-type]
            if self.mid_path:
                with contextlib.suppress(Exception):
                    QApplication.primaryScreen().grabWindow(0).save(self.mid_path)
            # M7: capture insertion-line / column-highlight visibility and source
            # opacity while the drag is live (GUI thread only — safe to read scene
            # state).  Items are lazily created so guard against None.
            with contextlib.suppress(Exception):
                if self._axis_move_line is not None:  # type: ignore[attr-defined]
                    self.mid_line_visible = self._axis_move_line.isVisible()  # type: ignore[attr-defined]
                if self._axis_move_highlight is not None:  # type: ignore[attr-defined]
                    self.mid_highlight_visible = self._axis_move_highlight.isVisible()  # type: ignore[attr-defined]
                if self._y_axes:  # type: ignore[attr-defined]
                    self.mid_source_opacity = self._y_axes[0].opacity()  # type: ignore[attr-defined]

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

    # Activate axis 0 — the new model accepts move/resize/zoom/pan only on the
    # active axis, so the frame-zone press below is ignored unless it is active.
    view.set_active_axis(0)
    QApplication.processEvents()

    # ─── DPI conversion factor (logical → physical pixels) ────────────────────
    # Qt coordinates are logical pixels.  Win32 SetCursorPos and mouse_event
    # require physical pixels on HiDPI displays.
    dpr = view.devicePixelRatioF()

    # ─── Source: FRAME zone of vm.axes[0]'s spine (left edge, vertical centre) ─
    # The active-axis model launches the move QDrag only from the spine's frame
    # band (left edge within FRAME px); the spine centre is now the zoom zone.
    # _y_axes[0] is the _AlignedAxisItem for vm.axes[0] (column 1, top half).
    src_item = view._y_axes[0]  # type: ignore[attr-defined]
    _src_rect = src_item.sceneBoundingRect()
    scene_src = QPoint(int(_src_rect.x() + 2), int(_src_rect.center().y()))
    src_vp = view.plot_widget.mapFromScene(scene_src)  # type: ignore[attr-defined]
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

    # ─── Real-OS QDrag driven by shared helper ────────────────────────────────
    drive_qdrag(
        (src_phys_x, src_phys_y),
        [(mid_phys_x, mid_phys_y), (tgt_phys_x, tgt_phys_y)],
        done=lambda: view.drop_seen,
    )

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
    # Real-input completion proof (KEEP): the drag actually reached dropEvent.
    assert view.drop_seen, (
        "no dropEvent fired — the real-OS drag never completed (watchdog "
        f"cancelled it). Screenshots saved to {tmp_path}"
    )
    assert len(vm.axes) == 2, f"expected 2 axes after drag, got {len(vm.axes)}"
    # Let the post-drop rebuild settle, then assert RENDERED geometry — NOT VM
    # ratios. The prior column/height_ratio/top_ratio asserts were the
    # false-green: the VM moved the axis but the View never painted the gap.
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: (
            len(view._y_axes) == 2  # type: ignore[attr-defined]
            and view._view_boxes[0].sceneBoundingRect().height() > 100
        ),  # type: ignore[attr-defined]
        timeout=3000,
    )
    R = view._view_boxes[0].sceneBoundingRect()  # type: ignore[attr-defined]

    def _strip(i: int) -> tuple[float, float]:
        r = view._y_axes[i].sceneBoundingRect()  # type: ignore[attr-defined]
        return ((r.y() - R.y()) / R.height(), r.height() / R.height())

    def _center_x(i: int) -> float:
        return view._y_axes[i].sceneBoundingRect().center().x()  # type: ignore[attr-defined]

    # axis 0 = the moved axis; its spine must paint in the OUTER column 0 band,
    # ~0.5 tall at top 0.0 (NOT grown to full height).
    band0 = view._column_containers[0].sceneBoundingRect()  # type: ignore[attr-defined]
    moved_top, moved_h = _strip(0)
    assert band0.x() <= _center_x(0) <= band0.x() + band0.width(), (
        f"moved spine not rendered in outer column 0 band. Screenshots: {tmp_path}"
    )
    assert moved_top == pytest.approx(0.0, abs=0.06), (
        f"moved spine not at top of col0 (got {moved_top}). Screenshots: {tmp_path}"
    )
    assert moved_h == pytest.approx(0.5, abs=0.06), (
        f"moved spine not ~0.5 tall — gap not rendered (got {moved_h}). "
        f"Screenshots: {tmp_path}"
    )
    # axis 1 = inner remainder; its spine must paint in column 1 at top ~0.5
    # (the vacated top half [0.0,0.5] is a genuine blank band).
    band1 = view._column_containers[1].sceneBoundingRect()  # type: ignore[attr-defined]
    rem_top, _rem_h = _strip(1)
    assert band1.x() <= _center_x(1) <= band1.x() + band1.width(), (
        f"inner remainder spine not in column 1 band. Screenshots: {tmp_path}"
    )
    assert rem_top == pytest.approx(0.5, abs=0.06), (
        f"inner remainder spine not at top 0.5 (blank above) — got {rem_top}. "
        f"Screenshots: {tmp_path}"
    )
    # M7: mid-drag feedback — empty-column path uses the highlight rect (col 0 was
    # empty when the drag passed through it); the insertion line stays hidden.
    assert view.mid_highlight_visible, (
        "M7: empty-col highlight not visible mid-drag — feedback not rendered. "
        f"Screenshots: {tmp_path}"
    )
    assert not view.mid_line_visible, (
        "M7: insertion line unexpectedly visible for empty-column drag path. "
        f"Screenshots: {tmp_path}"
    )
    assert view.mid_source_opacity == pytest.approx(0.35, abs=0.01), (
        f"M7: source axis not dimmed to 0.35 mid-drag (got {view.mid_source_opacity}). "
        f"Screenshots: {tmp_path}"
    )


def test_same_col_axis_reorder(qtbot: QtBot, tmp_path: Path) -> None:
    """M4 — drag axis 0 from top to bottom within the same column (col 1 reorder).

    Both axes start in the inner column (col 1).  A real-OS QDrag from the FRAME
    zone of the top axis (_y_axes[0]) to the bottom band of col 1 reorders the
    axes so the formerly-top axis paints below the other.

    M7 feedback (same-column path): col 1 is non-empty so the orange insertion
    line — not the column-highlight rect — must be visible mid-drag, and the
    source axis dimmed to 0.35 opacity.

    Honest RED gate: force ``_apply_deferred_axis_move`` to pass ``position=0``
    (always top-insert) in its call to ``vm.move_axis_to_column(...)``
    (graph_panel_view.py line 1691).  With ``position=0``, axis 0 is always
    inserted at the TOP of the column, so the ``moved_top > 0.4`` assertion
    (which checks that the dragged axis painted *below* the midpoint) flips RED.

    Why ``position=None`` is VACUOUS: ``None`` means always-append, which lands
    axis 0 at the bottom of the column — the SAME observable result as the
    correct bottom-drop reorder — so the test stays GREEN with that mutation.
    """
    skip_unless_real_display()

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import (
        _Y_AXIS_FIXED_WIDTH,
        GraphPanelView,
    )

    # ─── Session with two signals ──────────────────────────────────────────────
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
    signal_keys = sorted(s.name for s in session.signals())
    k0, k1 = signal_keys[0], signal_keys[1]

    # ─── ViewModel: column_count=2, two axes in the inner column ───────────────
    # Same initial layout as the col1→col0 test; neither axis is moved to col 0,
    # so the same-column reorder gesture stays within col 1.
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(k0, 0)  # axis 0, col 1, top half
    vm.create_new_axis(k1)  # axis 1, col 1, bottom half

    assert len(vm.axes) == 2
    assert all(a.column == vm.column_count - 1 for a in vm.axes), (
        "setup error: both axes must start in the inner column for same-col reorder"
    )

    # ─── View: capturing subclass with M7 state ────────────────────────────────
    class _CapturingView(GraphPanelView):
        mid_path: str = ""
        drop_seen: bool = False
        # M7: feedback state captured inside dragMoveEvent (GUI thread, safe).
        mid_line_visible: bool = False
        mid_highlight_visible: bool = False
        mid_source_opacity: float = 1.0

        def dragMoveEvent(self, ev: object) -> None:  # type: ignore[override]
            super().dragMoveEvent(ev)  # type: ignore[arg-type]
            if self.mid_path:
                with contextlib.suppress(Exception):
                    QApplication.primaryScreen().grabWindow(0).save(self.mid_path)
            # M7: col 1 is non-empty → insertion-line path.  Capture feedback
            # state on every dragMove (last captured value wins).
            with contextlib.suppress(Exception):
                if self._axis_move_line is not None:  # type: ignore[attr-defined]
                    self.mid_line_visible = self._axis_move_line.isVisible()  # type: ignore[attr-defined]
                if self._axis_move_highlight is not None:  # type: ignore[attr-defined]
                    self.mid_highlight_visible = self._axis_move_highlight.isVisible()  # type: ignore[attr-defined]
                if self._y_axes:  # type: ignore[attr-defined]
                    self.mid_source_opacity = self._y_axes[0].opacity()  # type: ignore[attr-defined]

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
    QApplication.processEvents()
    QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._y_axes[0].sceneBoundingRect().width() > 0,  # type: ignore[attr-defined]
        timeout=3000,
    )

    # Activate axis 0 — FRAME-zone drag is only accepted on the active axis.
    view.set_active_axis(0)
    QApplication.processEvents()

    dpr = view.devicePixelRatioF()

    # ─── Source: FRAME zone of _y_axes[0] (top axis, left edge, vertical centre) ──
    # _y_axes[0] is vm.axes[0] — column 1, top half.  Press 2 px from the left
    # edge (within FRAME=8 px) so the zone is AXZONE_FRAME → move QDrag fires.
    src_item = view._y_axes[0]  # type: ignore[attr-defined]
    _src_rect = src_item.sceneBoundingRect()
    scene_src = QPoint(int(_src_rect.x() + 2), int(_src_rect.center().y()))
    src_vp = view.plot_widget.mapFromScene(scene_src)  # type: ignore[attr-defined]
    src_global = view.plot_widget.viewport().mapToGlobal(src_vp)  # type: ignore[attr-defined]
    src_phys_x = round(src_global.x() * dpr)
    src_phys_y = round(src_global.y() * dpr)

    # ─── Target: col 1 band, bottom-quarter y ─────────────────────────────────
    # x ∈ [_Y_AXIS_FIXED_WIDTH, 2*_Y_AXIS_FIXED_WIDTH) keeps _axis_drop_target
    # in col 1 (col = int(x // 72) = 1).  y at 85 % of the view height is
    # nearest the bottom boundary → position=2 (after both axes), so the dragged
    # axis appends below axis 1.
    tgt_logi = view.mapToGlobal(
        QPoint(
            _Y_AXIS_FIXED_WIDTH + _Y_AXIS_FIXED_WIDTH // 2,
            int(view.height() * 0.85),
        )
    )
    tgt_phys_x = round(tgt_logi.x() * dpr)
    tgt_phys_y = round(tgt_logi.y() * dpr)

    mid_phys_x = (src_phys_x + tgt_phys_x) // 2
    mid_phys_y = (src_phys_y + tgt_phys_y) // 2

    # ─── Real-OS QDrag ────────────────────────────────────────────────────────
    drive_qdrag(
        (src_phys_x, src_phys_y),
        [(mid_phys_x, mid_phys_y), (tgt_phys_x, tgt_phys_y)],
        done=lambda: view.drop_seen,
    )

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "after_drag.png")
        )

    # ─── Assertions ───────────────────────────────────────────────────────────
    assert view.drop_seen, (
        "no dropEvent fired — the real-OS drag never completed (watchdog "
        f"cancelled it). Screenshots saved to {tmp_path}"
    )
    assert len(vm.axes) == 2, f"expected 2 axes after drag, got {len(vm.axes)}"

    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: (
            len(view._y_axes) == 2  # type: ignore[attr-defined]
            and view._view_boxes[0].sceneBoundingRect().height() > 100  # type: ignore[attr-defined]
        ),
        timeout=3000,
    )
    R = view._view_boxes[0].sceneBoundingRect()  # type: ignore[attr-defined]

    def _strip(i: int) -> tuple[float, float]:
        r = view._y_axes[i].sceneBoundingRect()  # type: ignore[attr-defined]
        return ((r.y() - R.y()) / R.height(), r.height() / R.height())

    # M4: axis 0 (dragged from top) must now paint in the BOTTOM half of col 1.
    # top_ratio > 0.4 proves it is no longer at the top position.
    moved_top, moved_h = _strip(0)
    assert moved_top > 0.4, (
        f"M4: reorder failed — axis 0 still near top (got top={moved_top:.3f}). "
        f"Expected > 0.4 after dragging to bottom. Screenshots: {tmp_path}"
    )
    assert moved_h == pytest.approx(0.5, abs=0.06), (
        f"M4: moved axis height changed unexpectedly (got {moved_h:.3f}). "
        f"Screenshots: {tmp_path}"
    )
    # Axis 1 must now occupy the top half (vacated by axis 0 moving down).
    rem_top, _rem_h = _strip(1)
    assert rem_top < 0.1, (
        f"M4: axis 1 not at top after reorder (got top={rem_top:.3f}). "
        f"Screenshots: {tmp_path}"
    )

    # M7: col 1 is non-empty → insertion-line path (not column-highlight).
    assert view.mid_line_visible, (
        "M7: insertion line not visible mid-drag for same-col gesture "
        f"(col 1 non-empty path). Screenshots: {tmp_path}"
    )
    assert not view.mid_highlight_visible, (
        "M7: column-highlight unexpectedly visible for same-col gesture. "
        f"Screenshots: {tmp_path}"
    )
    assert view.mid_source_opacity == pytest.approx(0.35, abs=0.01), (
        f"M7: source axis not dimmed to 0.35 mid-drag (got {view.mid_source_opacity}). "
        f"Screenshots: {tmp_path}"
    )
