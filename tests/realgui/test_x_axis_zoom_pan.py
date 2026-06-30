"""Layer C: X-axis horizontal drag → range-select zoom (inner strip) and pan (outer strip);
cross-panel X-range sync via the GraphAreaVM propagation path.

M10: Single-panel, X-strip inner drag (top half of strip) → zoom in;
     outer drag (bottom half) → pan.
M12: Two-panel area, panel-0 X-strip zoom → panel-1 x_range synced via GraphAreaVM.

X zoom/pan is ALWAYS-ON — no set_active_axis needed (unlike Y-axis gestures).
All gestures are plain OS mouse drags (no QDrag / OLE modal loop).

honest RED gates:
  M10: comment ``if zone in (ZONE_X_INNER, ZONE_X_OUTER):`` at graph_panel_view.py
       lines 1573-1575 → _drag_zone never set → mouseReleaseEvent guard fails →
       x_range unchanged → both M10 assertions flip RED.
  M12: call ``view.vm.set_x_sync(0, False)`` before the drag → propagate_x_range
       skips → panel-1 x_range stays at the original auto-fit value → assertion
       ``p0.vm.x_range == p1.vm.x_range`` flips RED.

X-AxisItem press-propagation risk: the shared X AxisItem is a plain pg.AxisItem
(not _AlignedAxisItem).  If it consumes the left-press, GraphPanelView.mousePressEvent
is never reached and _drag_zone stays None.  The realgui gate is the only reliable
check; this risk is noted as gate-determined and cannot be confirmed headlessly.
"""

from __future__ import annotations

import contextlib
import tempfile
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


# ─── Setup helpers ────────────────────────────────────────────────────────────


def _single_panel(qtbot: QtBot):
    """Build a two-axis GraphPanelView shown on the real screen (M10)."""
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
    QApplication.processEvents()
    return view


def _two_panel_area(qtbot: QtBot):
    """Real GraphAreaView + two panels both holding a signal for M12 sync test.

    Mirrors the _two_panel_area pattern from test_offset_drag.py.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.graph_area_view import GraphAreaView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    d = Path(tempfile.mkdtemp())
    csv = d / "lin.csv"
    rows = ["t,lin"] + [f"{i / 50.0:.4f},{i / 50.0:.4f}" for i in range(50)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    app = AppViewModel()
    app.request_load(
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
    signal_key = sorted(s.name for s in app.signals())[0]
    area_vm = GraphAreaVM(app)
    area_vm.add_panel(0)  # tab 0 now holds two panels
    for p in area_vm.panels(0):
        p.add_signal_to_axis(signal_key, 0)

    view = GraphAreaView(area_vm)
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(200, 100, 900, 800)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()

    splitter = view.tabs.widget(0)
    panels = [
        splitter.widget(i)
        for i in range(splitter.count())
        if isinstance(splitter.widget(i), GraphPanelView)
    ]
    assert len(panels) == 2
    qtbot.waitUntil(
        lambda: all(
            p._view_boxes[0].sceneBoundingRect().height() > 100 for p in panels
        ),
        timeout=3000,
    )
    return view, panels


def _x_strip_drag(panel, y_frac: float) -> None:
    """Drive a horizontal left→right drag on panel's X-axis strip.

    y_frac=0.25 → inner zone (top half, closer to plot) → range-select zoom.
    y_frac=0.75 → outer zone (bottom half, closer to window edge) → pan.
    Drag covers 30%-70% of the strip width for a significant effect.
    """
    from PySide6.QtWidgets import QApplication

    strip = panel._x_axis.sceneBoundingRect()
    sy = strip.y() + strip.height() * y_frac
    left_x = strip.x() + strip.width() * 0.30
    right_x = strip.x() + strip.width() * 0.70

    gx_start, gy = to_phys(panel, left_x, sy)
    gx_end, _ = to_phys(panel, right_x, sy)

    at(gx_start, gy, LDOWN)
    time.sleep(0.05)
    steps = max(3, abs(gx_end - gx_start) // 8)
    for k in range(1, steps + 1):
        at(gx_start + (gx_end - gx_start) * k // steps, gy, MOVE)
        QApplication.processEvents()
        time.sleep(0.03)
    at(gx_end, gy, LUP)
    for _ in range(4):
        QApplication.processEvents()


# ─── M10: X-axis zoom/pan (single panel) ─────────────────────────────────────


def test_x_inner_drag_zooms_in(qtbot: QtBot, tmp_path) -> None:
    """M10-zoom: X-strip inner drag (top half) selects a range → zooms in.

    After a left→right drag covering 40% of the strip in ZONE_X_INNER,
    apply_zone_drag sets x_range to ordered_pair(start_value, end_value) which
    is ~40% of the original span.  The assertion checks span < 90% of original.

    honest RED: comment graph_panel_view.py lines 1573-1575 → _drag_zone never
    set → mouseReleaseEvent apply is skipped → x_range stays at full original span.
    """
    skip_unless_real_display()

    view = _single_panel(qtbot)
    assert view.vm.x_range is not None, "x_range not set after add_signal"
    lo0, hi0 = view.vm.x_range
    orig_span = hi0 - lo0

    _x_strip_drag(view, y_frac=0.25)  # ZONE_X_INNER = top half

    with contextlib.suppress(Exception):
        from PySide6.QtWidgets import QApplication

        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "x_zoom.png"))

    assert view.vm.x_range is not None
    lo1, hi1 = view.vm.x_range
    after_span = hi1 - lo1
    assert after_span < orig_span * 0.9, (
        f"X inner drag did not zoom in: span_after={after_span:.4f} "
        f"orig={orig_span:.4f}. "
        "Risk: pg.AxisItem may consume the left-press (gate-determined)."
    )


def test_x_outer_drag_pans(qtbot: QtBot, tmp_path) -> None:
    """M10-pan: X-strip outer drag (bottom half) pans without changing the span.

    After a left→right drag in ZONE_X_OUTER, apply_zone_drag calls
    pan_range(lo, hi, start-end) where start<end → negative delta → pans left.
    The assertion checks span unchanged and center shifted by > 5% of span.

    honest RED: same as M10-zoom (comment lines 1573-1575 → _drag_zone None →
    x_range unchanged → center shift = 0 → assertion flips RED).
    """
    skip_unless_real_display()

    view = _single_panel(qtbot)
    assert view.vm.x_range is not None, "x_range not set after add_signal"
    lo0, hi0 = view.vm.x_range
    orig_span = hi0 - lo0
    center_before = (lo0 + hi0) / 2.0

    _x_strip_drag(view, y_frac=0.75)  # ZONE_X_OUTER = bottom half

    with contextlib.suppress(Exception):
        from PySide6.QtWidgets import QApplication

        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "x_pan.png"))

    assert view.vm.x_range is not None
    lo1, hi1 = view.vm.x_range
    after_span = hi1 - lo1
    center_after = (lo1 + hi1) / 2.0
    assert after_span == pytest.approx(orig_span, rel=0.1), (
        f"X outer drag changed span: after={after_span:.4f} orig={orig_span:.4f}"
    )
    assert abs(center_after - center_before) > orig_span * 0.05, (
        f"X outer drag did not pan: shift={abs(center_after - center_before):.4f} "
        f"(required > {orig_span * 0.05:.4f})"
    )


# ─── M12: X-axis cross-panel sync ────────────────────────────────────────────


def test_x_sync_cross_panel(qtbot: QtBot, tmp_path) -> None:
    """M12: X-strip zoom on panel-0 propagates to panel-1 via GraphAreaVM x-sync.

    GraphAreaVM._subscribe_panel watches each panel's 'range' notifications.
    When panel-0.set_x_range fires, _on_panel_change propagates the range to all
    siblings (x_sync_enabled=True by default), so panel-1.x_range becomes equal.

    Assertions: p0.x_range == p1.x_range (synced) AND span < 90% of original
    (real zoom happened, not just stale range equality).

    honest RED: call ``view.vm.set_x_sync(0, False)`` before the drag →
    propagate_x_range returns early → panel-1 stays at original auto-fit range →
    ``p0.vm.x_range == p1.vm.x_range`` flips RED.
    """
    skip_unless_real_display()

    _view, panels = _two_panel_area(qtbot)
    p0, p1 = panels[0], panels[1]

    assert p0.vm.x_range is not None, "p0 x_range not set"
    assert p1.vm.x_range is not None, "p1 x_range not set"
    lo0_init, hi0_init = p0.vm.x_range
    orig_span = hi0_init - lo0_init

    _x_strip_drag(p0, y_frac=0.25)  # ZONE_X_INNER zoom on panel-0

    with contextlib.suppress(Exception):
        from PySide6.QtWidgets import QApplication

        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "x_sync.png"))

    assert p0.vm.x_range is not None, "p0 x_range is None after drag"
    assert p1.vm.x_range is not None, "p1 x_range is None after drag"
    assert p0.vm.x_range == p1.vm.x_range, (
        f"x_range not synced after cross-panel X drag: "
        f"p0={p0.vm.x_range} p1={p1.vm.x_range}"
    )
    after_span = p0.vm.x_range[1] - p0.vm.x_range[0]
    assert after_span < orig_span * 0.9, (
        f"zoom did not happen on p0 (sync may read stale range): "
        f"span={after_span:.4f} orig={orig_span:.4f}"
    )
