"""Tests for GraphPanelView zoom/pan interaction — Task 8.3.

The interaction logic is decomposed so it can be verified headlessly:
- pure range math (zoom_range / pan_range / ordered_pair)
- pixel-zone classification (classify_zone) and cursor mapping (cursor_for_zone)
- data-coordinate drag gesture methods on the view (apply_zone_drag, X axis only)
  that update the VM range — R9.2-9.3, R10.2-10.3

Task 8 removed widget-level Y zoom/pan (apply_zone_wheel, reset_zone, wheelEvent,
mouseDoubleClickEvent) and Y drag gestures.  Y interaction now lives entirely on
_AlignedAxisItem.  Y zone classification (classify_zone) is KEPT because dropEvent
uses ZONE_Y_INNER / ZONE_Y_OUTER for drop-target routing.

TDD: written before the implementation; all must FAIL first.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import (
    ZONE_NONE,
    ZONE_PLOT,
    ZONE_X_INNER,
    ZONE_X_OUTER,
    ZONE_Y_INNER,
    ZONE_Y_OUTER,
    classify_zone,
    cursor_for_zone,
    ordered_pair,
    pan_range,
    zoom_range,
)

# ─── Helpers ────────────────────────────────────────────────────────────────


def _loaded_vm(tmp_path: Path) -> tuple[GraphPanelVM, str]:
    fmt = FormatDefinition(
        name="fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    lines = ["t,v"] + [f"{i * 0.01},{float(i % 50)}" for i in range(100)]
    path = tmp_path / "d.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    session = Session()
    session.load(path, fmt)
    vm = GraphPanelVM(session)
    return vm, session.signals()[0].name


def _view_with_signal(qtbot: QtBot, tmp_path: Path) -> object:
    from valisync.gui.views.graph_panel_view import GraphPanelView

    vm, key = _loaded_vm(tmp_path)
    vm.add_signal(key)  # auto-fits x_range≈(0,0.99), y_range≈(0,49)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    return view


# ─── Pure range math ──────────────────────────────────────────────────────────


class TestRangeMath:
    def test_ordered_pair_sorts(self) -> None:
        assert ordered_pair(0.5, 0.2) == (0.2, 0.5)
        assert ordered_pair(0.2, 0.5) == (0.2, 0.5)

    def test_zoom_range_in_narrows_about_center(self) -> None:
        lo, hi = zoom_range(0.0, 1.0, center=0.5, factor=0.8)
        assert lo == pytest.approx(0.1)
        assert hi == pytest.approx(0.9)

    def test_zoom_range_out_widens_about_center(self) -> None:
        lo, hi = zoom_range(0.0, 1.0, center=0.5, factor=1.25)
        assert lo < 0.0
        assert hi > 1.0

    def test_zoom_keeps_center_fixed(self) -> None:
        lo, hi = zoom_range(0.0, 1.0, center=0.25, factor=0.5)
        # the zoom center maps to itself
        assert (lo + (hi - lo) * 0.25) == pytest.approx(0.25)

    def test_pan_range_shifts(self) -> None:
        assert pan_range(0.0, 1.0, 0.3) == pytest.approx((0.3, 1.3))


# ─── Zone classification (R9.1/R10.1) + cursor (R9.7/R10.7) ─────────────────────


class TestZones:
    # plot_rect: x in [50,250], y in [10,110]; widget 300x150.
    RECT = QRectF(50.0, 10.0, 200.0, 100.0)
    W, H = 300.0, 150.0

    def _z(self, px: float, py: float) -> str:
        return classify_zone(px, py, self.RECT, self.W, self.H, inner_frac=0.5)

    def test_inside_plot(self) -> None:
        assert self._z(100.0, 50.0) == ZONE_PLOT

    def test_x_inner_just_below_plot(self) -> None:
        # strip y∈(110,150]; inner half = (110,130]
        assert self._z(150.0, 120.0) == ZONE_X_INNER

    def test_x_outer_near_window_bottom(self) -> None:
        assert self._z(150.0, 145.0) == ZONE_X_OUTER

    def test_y_inner_just_left_of_plot(self) -> None:
        # strip x∈[0,50); inner half (near plot) = [25,50)
        assert self._z(40.0, 60.0) == ZONE_Y_INNER

    def test_y_outer_near_window_left(self) -> None:
        assert self._z(10.0, 60.0) == ZONE_Y_OUTER

    def test_corner_is_none(self) -> None:
        assert self._z(10.0, 145.0) == ZONE_NONE

    def test_cursor_shapes(self) -> None:
        assert cursor_for_zone(ZONE_X_INNER) == Qt.CursorShape.SizeHorCursor
        assert cursor_for_zone(ZONE_X_OUTER) == Qt.CursorShape.SizeHorCursor
        # Y zones return ArrowCursor: widget no longer imposes a Y cursor.
        # _AlignedAxisItem owns the Y hover cursor (Task 8).
        assert cursor_for_zone(ZONE_Y_INNER) == Qt.CursorShape.ArrowCursor
        assert cursor_for_zone(ZONE_Y_OUTER) == Qt.CursorShape.ArrowCursor
        assert cursor_for_zone(ZONE_PLOT) == Qt.CursorShape.ArrowCursor


# ─── Drag gestures → VM range (X only; Y moved to _AlignedAxisItem) ────────────


class TestDragGestures:
    def test_inner_x_drag_sets_range(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        view.apply_zone_drag(ZONE_X_INNER, 0.5, 0.2)  # type: ignore[attr-defined]
        assert view.vm.x_range == pytest.approx((0.2, 0.5))  # type: ignore[attr-defined]

    def test_outer_x_drag_pans(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        lo0, hi0 = view.vm.x_range  # type: ignore[attr-defined]
        view.apply_zone_drag(ZONE_X_OUTER, 0.5, 0.3)  # type: ignore[attr-defined]
        # delta = start - end = +0.2 → window shifts to later data
        assert view.vm.x_range == pytest.approx((lo0 + 0.2, hi0 + 0.2))  # type: ignore[attr-defined]

    # NOTE: Y drag tests removed (Task 8) — Y zoom/pan lives on _AlignedAxisItem.
