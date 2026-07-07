"""Layer C: inner drag = range-select zoom-in, outer drag = pan, per-zone cursor.

All gestures are accepted only on the ACTIVE axis and are driven by real OS mouse
input (no QDrag — these paths use pyqtgraph scene drags, so no OLE modal loop).
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING

import pytest
from pytestqt.qtbot import QtBot

if TYPE_CHECKING:
    from valisync.gui.views.graph_panel_view import GraphPanelView

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    MOVE,
    at,
    skip_unless_real_display,
    to_phys,
)

pytestmark = pytest.mark.realgui


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


def test_inner_drag_zooms_in_on_active_axis(qtbot: QtBot, tmp_path) -> None:
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _active_panel(qtbot)
    lo0, hi0 = view._y_axes[0].range
    before = hi0 - lo0

    spine = view._y_axes[0].sceneBoundingRect()
    inner_x = spine.x() + spine.width() * 0.78  # right half = plot-side = zoom zone
    x0, ya = to_phys(view, inner_x, spine.y() + spine.height() * 0.30)
    _, yb = to_phys(view, inner_x, spine.y() + spine.height() * 0.70)

    at(x0, ya, LDOWN)
    time.sleep(0.05)
    for yy in (ya + (yb - ya) // 3, ya + 2 * (yb - ya) // 3, yb):
        at(x0, yy, MOVE)
        QApplication.processEvents()
        time.sleep(0.04)
    at(x0, yb, LUP)
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
    skip_unless_real_display()
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
    x0, ya = to_phys(view, outer_x, spine.y() + spine.height() * 0.40)
    _, yb = to_phys(view, outer_x, spine.y() + spine.height() * 0.75)

    at(x0, ya, LDOWN)
    time.sleep(0.05)
    for yy in (ya + (yb - ya) // 3, ya + 2 * (yb - ya) // 3, yb):
        at(x0, yy, MOVE)
        QApplication.processEvents()
        time.sleep(0.04)
    at(x0, yb, LUP)
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


def test_lod_render_after_resize(qtbot: QtBot, tmp_path) -> None:
    """M11: resize-driven LOD — View applies LOD-reduced arrays to PlotDataItem.

    Existing VM tests only check vm.lod_active / vm.last_rendered_points (ViewModel
    state).  They would stay green even if refresh() passed raw signal arrays to
    pyqtgraph instead of the LOD-reduced ones.  This test closes that gap by
    asserting panel._items[key].getData()[0] point count directly.

    Honest RED: replace ``item.setData(curve.timestamps, curve.values)`` in
    graph_panel_view.py:refresh() with raw ``sig.timestamps, sig.values`` → the
    5000-point signal fills the item; ``len(getData()[0]) <= 2*200 + 10`` fails.
    OR force ``vm.lod_active = False`` just before the check — the assertion catches it.
    """
    skip_unless_real_display()

    import tempfile
    from pathlib import Path

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import GraphPanelView

    # Build a 5 000-point signal — well above any plausible 2*width LOD threshold.
    n = 5000
    d = Path(tempfile.mkdtemp())
    csv = d / "large.csv"
    rows = ["t,sig"] + [f"{i / 1000.0:.6f},{float(i % 100)}" for i in range(n)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    session = Session()
    session.load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    keys = sorted(s.name for s in session.signals())
    key = keys[0]  # namespaced, e.g. "csv_1::sig"

    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(key, 0)
    view = GraphPanelView(vm)

    # ── Narrow viewport ──────────────────────────────────────────────────────────
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 200, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()

    assert vm.panel_width_px <= 200
    assert vm.lod_active is True, "5000-pt signal at 200 px width should activate LOD"

    item = view._items[key]
    xs_narrow, _ = item.getData()
    assert xs_narrow is not None, "PlotDataItem has no data after narrow show"
    narrow_count = len(xs_narrow)
    # The key assertion VM tests lack: the VIEW must have applied the LOD-reduced
    # arrays (≤ 2*width points), not the raw 5000-point signal.
    assert narrow_count <= 2 * vm.panel_width_px + 10, (
        f"View applied raw arrays to PlotDataItem: "
        f"{narrow_count} points > 2*{vm.panel_width_px}+10 "
        f"(screens: {tmp_path})"
    )

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "lod_narrow.png")
        )

    # ── Wide viewport — LOD budget increases, point count must grow ──────────────
    view.setGeometry(300, 300, 1600, 600)
    for _ in range(3):
        QApplication.processEvents()

    xs_wide, _ = view._items[key].getData()
    assert xs_wide is not None, "PlotDataItem has no data after wide resize"
    wide_count = len(xs_wide)
    assert wide_count > narrow_count, (
        f"LOD did not relax at wide viewport: "
        f"wide={wide_count} <= narrow={narrow_count} "
        f"(screens: {tmp_path})"
    )

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "lod_wide.png"))


def test_cursor_changes_per_zone(qtbot: QtBot) -> None:
    """Hovering each zone of the active axis sets a zone-specific cursor on the AxisItem."""
    skip_unless_real_display()
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
                at(gx, gy - off, MOVE)
                QApplication.processEvents()
                time.sleep(0.012)
            time.sleep(0.04)
            QApplication.processEvents()
            if axis.cursor().shape() != Qt.CursorShape.ArrowCursor:
                break
        return axis.cursor().shape()

    # PC-13 unified Y cursors: grip (top-centre) → RESIZE_V (SizeVer) ;
    # frame (left border, mid) → MOVE (SizeAll) ; inner/right interior → ZOOM_V
    # (custom vertical zoom bracket = BitmapCursor) ; outer/left interior → PAN_V
    # (SizeVer). Interior points keep a wide margin from the frame border so small
    # input-to-scene rounding (1.25 DPI) cannot flip the classified zone.
    assert hover_shape(w / 2.0, 4) == Qt.CursorShape.SizeVerCursor
    assert hover_shape(2, h / 2.0) == Qt.CursorShape.SizeAllCursor
    assert hover_shape(w * 0.7, h / 2.0) == Qt.CursorShape.BitmapCursor
    assert hover_shape(w * 0.25, h / 2.0) == Qt.CursorShape.SizeVerCursor
