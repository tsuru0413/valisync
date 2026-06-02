"""Tests for GraphPanelView zoom/pan interaction — Task 8.3.

The interaction logic is decomposed so it can be verified headlessly:
- pure range math (zoom_range / pan_range / ordered_pair)
- pixel-zone classification (classify_zone) and cursor mapping (cursor_for_zone)
- data-coordinate gesture methods on the view (apply_zone_drag / apply_zone_wheel
  / reset_zone) that update the VM range — these are the "drag/wheel/double-click
  reflected in VM range" contract (R9.2-9.4/9.6, R10.2-10.4/10.6)

The thin Qt event handlers (mouse/wheel/double-click) translate raw events into
these methods; they get a no-crash smoke test.

TDD: written before the implementation; all must FAIL first.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QWheelEvent
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
        assert cursor_for_zone(ZONE_Y_INNER) == Qt.CursorShape.SizeVerCursor
        assert cursor_for_zone(ZONE_Y_OUTER) == Qt.CursorShape.SizeVerCursor
        assert cursor_for_zone(ZONE_PLOT) == Qt.CursorShape.ArrowCursor


# ─── Drag gestures → VM range (R9.2/9.3, R10.2/10.3) ───────────────────────────


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

    def test_inner_y_drag_sets_range(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        view.apply_zone_drag(ZONE_Y_INNER, 30.0, 10.0)  # type: ignore[attr-defined]
        assert view.vm.y_range == pytest.approx((10.0, 30.0))  # type: ignore[attr-defined]

    def test_outer_y_drag_pans(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        lo0, hi0 = view.vm.y_range  # type: ignore[attr-defined]
        view.apply_zone_drag(ZONE_Y_OUTER, 20.0, 5.0)  # type: ignore[attr-defined]
        assert view.vm.y_range == pytest.approx((lo0 + 15.0, hi0 + 15.0))  # type: ignore[attr-defined]


# ─── Wheel zoom → VM range (R9.4/R10.4) ────────────────────────────────────────


class TestWheelZoom:
    def test_wheel_zoom_in_x_narrows(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        lo0, hi0 = view.vm.x_range  # type: ignore[attr-defined]
        view.apply_zone_wheel(ZONE_X_INNER, 0.5, 0.8)  # type: ignore[attr-defined]
        lo, hi = view.vm.x_range  # type: ignore[attr-defined]
        assert lo > lo0 and hi < hi0

    def test_wheel_zoom_out_x_widens(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        lo0, hi0 = view.vm.x_range  # type: ignore[attr-defined]
        view.apply_zone_wheel(ZONE_X_OUTER, 0.5, 1.25)  # type: ignore[attr-defined]
        lo, hi = view.vm.x_range  # type: ignore[attr-defined]
        assert lo < lo0 and hi > hi0

    def test_wheel_zoom_y(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        lo0, hi0 = view.vm.y_range  # type: ignore[attr-defined]
        view.apply_zone_wheel(ZONE_Y_INNER, 25.0, 0.8)  # type: ignore[attr-defined]
        lo, hi = view.vm.y_range  # type: ignore[attr-defined]
        assert lo > lo0 and hi < hi0


# ─── Double-click reset → VM range (R9.6/R10.6) ────────────────────────────────


class TestReset:
    def test_reset_x_zone_refits(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        view.vm.set_x_range(0.2, 0.5)  # type: ignore[attr-defined]  # zoom in first
        view.reset_zone(ZONE_X_INNER)  # type: ignore[attr-defined]
        assert view.vm.x_range == pytest.approx((0.0, 0.99))  # type: ignore[attr-defined]

    def test_reset_y_zone_refits(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        view.vm.set_y_range(10.0, 20.0)  # type: ignore[attr-defined]
        view.reset_zone(ZONE_Y_OUTER)  # type: ignore[attr-defined]
        assert view.vm.y_range == pytest.approx((0.0, 49.0))  # type: ignore[attr-defined]

    def test_reset_plot_zone_is_noop(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        view.vm.set_x_range(0.2, 0.5)  # type: ignore[attr-defined]
        view.reset_zone(ZONE_PLOT)  # type: ignore[attr-defined]
        assert view.vm.x_range == pytest.approx((0.2, 0.5))  # type: ignore[attr-defined]


# ─── Qt event glue smoke (no crash) ────────────────────────────────────────────


class TestEventSmoke:
    def test_wheel_event_does_not_crash(self, qtbot: QtBot, tmp_path: Path) -> None:
        view = _view_with_signal(qtbot, tmp_path)
        view.resize(400, 300)  # type: ignore[attr-defined]
        event = QWheelEvent(
            QPointF(200.0, 290.0),
            QPointF(200.0, 290.0),
            QPointF(0, 0).toPoint(),
            QPointF(0, 120).toPoint(),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        view.wheelEvent(event)  # type: ignore[attr-defined]  # must not raise
