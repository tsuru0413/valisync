"""M13 Production Fix: Layer B (headless) test — viewport eventFilter hover cursor.

Sends a synthetic no-button QMouseEvent(MouseMove) to ``plot_widget.viewport()``
and asserts that GraphPanelView's cursor updates via the eventFilter.

Proof structure:
- RED before the fix: ``installEventFilter`` not called → the viewport event is
  delivered only to the QGraphicsView; GraphPanelView.mouseMoveEvent is never
  reached → cursor stays ArrowCursor → X-strip assertion FAILS.
- GREEN after the fix: ``GraphPanelView.eventFilter`` intercepts the viewport
  move, maps coords, calls ``self.setCursor(SizeHorCursor)`` → assertion PASSES.

Why this is an honest Layer B gate (not false-green):
  Without the eventFilter, ``QApplication.sendEvent(viewport, ev)`` is delivered
  only to QGraphicsView machinery — the parent GraphPanelView.mouseMoveEvent is
  not called (mirrors the OS-level non-propagation confirmed by the
  `gui_realgui_move_not_reaching_parent_qwidget` memory).  Installing the event
  filter is the ONLY way this test passes; there is no shortcut path.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.gui._panel_factory import make_two_axis_panel
from valisync.gui.views.graph_panel_view import GraphPanelView

# ─── Setup ────────────────────────────────────────────────────────────────────


def _setup_panel(qtbot: QtBot) -> GraphPanelView:
    """Build and expose a two-axis panel so scene geometry is valid."""
    view = make_two_axis_panel()
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    # Wait until the first viewbox has rendered (non-zero scene height).
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 10, timeout=3000
    )
    QApplication.processEvents()
    return view


def _hover(view: GraphPanelView, viewport_pos: QPointF) -> None:
    """Send a synthetic no-button MouseMove to view.plot_widget.viewport()."""
    ev = QMouseEvent(
        QEvent.Type.MouseMove,
        viewport_pos,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.plot_widget.viewport(), ev)
    QApplication.processEvents()


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_x_inner_hover_sets_zoom_cursor(qtbot: QtBot) -> None:
    """Layer B: viewport hover over X inner (zoom) strip → custom zoom cursor (PC-14).

    Coordinate path:
      X-axis strip sceneBoundingRect → inner-zone centre (sy = 25% into strip)
      → plot_widget.mapFromScene → viewport-local QPointF
      → sendEvent(viewport, MouseMove, NoButton)
      → GraphPanelView.eventFilter intercepts
      → viewport.mapTo(self, ...) → panel coords
      → _zone_at → ZONE_X_INNER
      → setCursor(cursor(ZOOM_H)) = custom BitmapCursor.

    PC-14: X inner=zoom now uses the custom horizontal zoom bracket (BitmapCursor),
    distinct from X outer=pan (SizeHor).
    """
    view = _setup_panel(qtbot)

    strip = view._x_axis.sceneBoundingRect()
    sx = strip.x() + strip.width() * 0.5
    sy = strip.y() + strip.height() * 0.25  # top half → ZONE_X_INNER (zoom)
    viewport_pos = QPointF(view.plot_widget.mapFromScene(QPointF(sx, sy)))

    _hover(view, viewport_pos)

    assert view.cursor().shape() == Qt.CursorShape.BitmapCursor, (
        f"Expected custom zoom BitmapCursor after hovering X inner; "
        f"got {view.cursor().shape()}."
    )


def test_empty_plot_zone_hover_resets_to_arrow_cursor(
    qtbot: QtBot, monkeypatch
) -> None:
    """Layer B: viewport hover over an *empty* plot zone → ArrowCursor via eventFilter.

    After the X-inner hover sets the zoom cursor, moving into a plot area with no
    curve underneath must reset to ArrowCursor. `_curve_at` is stubbed to None so
    the point is deterministically curve-free — over a curve the plot area now
    intentionally shows the offset-drag affordance (SizeHor), tested separately in
    test_plot_offset_cursor.py.
    """
    view = _setup_panel(qtbot)
    monkeypatch.setattr(view, "_curve_at", lambda pos: None)  # 空プロット領域

    # Step 1: hover X inner strip (sets the custom zoom cursor).
    strip = view._x_axis.sceneBoundingRect()
    sx = strip.x() + strip.width() * 0.5
    sy = strip.y() + strip.height() * 0.25
    _hover(view, QPointF(view.plot_widget.mapFromScene(QPointF(sx, sy))))

    # Step 2: hover plot centre (curve-free) → expect ArrowCursor.
    vb = view._view_boxes[0]
    plot_rect = vb.sceneBoundingRect()
    px = plot_rect.x() + plot_rect.width() * 0.5
    py = plot_rect.y() + plot_rect.height() * 0.5
    _hover(view, QPointF(view.plot_widget.mapFromScene(QPointF(px, py))))

    assert view.cursor().shape() == Qt.CursorShape.ArrowCursor, (
        f"Expected ArrowCursor after hovering empty plot zone; "
        f"got {view.cursor().shape()}."
    )
