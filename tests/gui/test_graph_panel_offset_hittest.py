"""Layer B: 曲線ヒットテスト _curve_at (R14)。実 ViewBox 幾何で検証。"""

from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.gui._panel_factory import make_single_signal_panel


def _shown(qtbot: QtBot):
    view = make_single_signal_panel()
    qtbot.addWidget(view)
    view.resize(700, 500)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return view


def _plot_center_widget_pos(view) -> QPointF:
    return view._plot_rect_in_widget().center()


def test_curve_at_hits_curve_center(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    key = sorted(view._items.keys())[0]
    hit = view._curve_at(_plot_center_widget_pos(view))
    assert hit == key


def test_curve_at_misses_empty_corner(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    rect = view._plot_rect_in_widget()
    # Top-left corner: the linear curve is at its minimum (bottom) here → far away.
    corner = QPointF(rect.left() + 3.0, rect.top() + 3.0)
    assert view._curve_at(corner) is None


def test_curve_at_yields_to_visible_cursor_line(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    # Cursor line A appears at the visible-width 50% — i.e. the plot centre x,
    # which is exactly where the curve centre is. The guard must return None so
    # the InfiniteLine D&D wins (priority: cursor line > curve, §4).
    view.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible()
    # Geometric sanity: cursor A must sit at the plot-centre data-x so the
    # hit-test overlap tested above is not vacuous.  Data is v=t over [0, 1)
    # (50 pts, max=0.98) → x_range=[0, 0.98] → 50% midpoint ≈ 0.49.
    cursor_val = view.cursor_line_value()
    assert abs(cursor_val - 0.49) < 0.1, (
        f"Cursor expected near 0.49 but got {cursor_val!r}; "
        "factory data-range may have changed — update tolerance or factory."
    )
    assert view._curve_at(_plot_center_widget_pos(view)) is None
