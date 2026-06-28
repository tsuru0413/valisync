"""Task 4: active-axis state + click-to-activate tests.

Layer A: state API — set_active_axis sets/clears _active_axis_index directly.
Layer B (handler-path): _AlignedAxisItem.mouseClickEvent driven directly with a
duck-typed _ClickEvent.  This verifies the handler logic but does NOT exercise
the OS → Qt → pyqtgraph scene → mouseClickEvent routing chain.
Layer B (real scene-routing): qtbot.mouseClick on the viewport exercises the
full Qt event path — QGraphicsView.viewport → QGraphicsScene → pyqtgraph
dispatch → mouseClickEvent.  Runs offscreen: the virtual surface delivers
synthetic click events via Qt's normal scene item dispatch.

Why mouseClickEvent (not mousePressEvent):
  pyqtgraph's GraphicsScene accumulates press events and fires mouseClickEvent
  on items only after the button is released without a drag gesture — the same
  event-routing path used by the existing mouseDragEvent override.
  AxisItem.mouseClickEvent (pyqtgraph 0.14) simply delegates to the linked
  ViewBox; since these axes are *unlinked*, the parent is a no-op and our
  override is the only handler in the chain.  That makes it safe, correct, and
  independently verifiable by the Layer B duck-type below.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.gui._panel_factory import make_two_axis_panel
from valisync.gui.views.graph_panel_view import (
    GraphPanelView,
    _AlignedAxisItem,
    reset_scene_drag_state,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────


class _ClickEvent:
    """Duck-typed pyqtgraph MouseClickEvent for Layer B handler-path tests.

    Exposes the interface that _AlignedAxisItem.mouseClickEvent consumes:
    button(), accept(), ignore().  The real pyqtgraph MouseClickEvent is
    constructed by GraphicsScene and carries more fields, but the handler only
    interrogates these three.
    """

    def __init__(self, button: Qt.MouseButton = Qt.MouseButton.LeftButton) -> None:
        self._button = button
        self.accepted: bool = False

    def button(self) -> Qt.MouseButton:
        return self._button

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def panel(qtbot: QtBot) -> GraphPanelView:
    view = make_two_axis_panel()
    qtbot.addWidget(view)
    return view


# ─── Task 8: guard — no widget-level wheel/double-click zoom ─────────────────


def test_widget_has_no_wheel_or_doubleclick_zoom(panel: GraphPanelView) -> None:
    """GraphPanelView must NOT define wheelEvent or mouseDoubleClickEvent.

    Y zoom/pan has moved to _AlignedAxisItem (Task 6).  Neither wheel-zoom nor
    double-click-reset is adopted for X either (those will come via context menu
    later).  This test guards against accidental re-introduction.
    """
    assert "wheelEvent" not in type(panel).__dict__
    assert "mouseDoubleClickEvent" not in type(panel).__dict__


# ─── Layer A: state API ────────────────────────────────────────────────────────


def test_initial_active_axis_is_none(panel: GraphPanelView) -> None:
    """_active_axis_index starts as None (no selection on init)."""
    assert panel._active_axis_index is None


def test_set_active_axis_sets_index(panel: GraphPanelView) -> None:
    """set_active_axis(1) stores 1 in _active_axis_index."""
    panel.set_active_axis(1)
    assert panel._active_axis_index == 1


def test_set_active_axis_clears_to_none(panel: GraphPanelView) -> None:
    """set_active_axis(None) clears the active selection."""
    panel.set_active_axis(1)
    panel.set_active_axis(None)
    assert panel._active_axis_index is None


def test_set_active_axis_idempotent(panel: GraphPanelView) -> None:
    """Calling set_active_axis with the same index is a no-op (no error)."""
    panel.set_active_axis(0)
    panel.set_active_axis(0)
    assert panel._active_axis_index == 0


def test_set_active_axis_switches_index(panel: GraphPanelView) -> None:
    """Switching from one active axis to another updates the stored index."""
    panel.set_active_axis(0)
    panel.set_active_axis(1)
    assert panel._active_axis_index == 1


# ─── Layer B: click handler path ──────────────────────────────────────────────


def test_mouseClickEvent_left_activates_axis(panel: GraphPanelView) -> None:
    """Handler-path: left-click on axis 1 calls set_active_axis(1).

    Drives _AlignedAxisItem.mouseClickEvent directly with a duck-typed
    _ClickEvent (same interface as the real pyqtgraph MouseClickEvent).
    This is the handler-path variant: the handler logic is verified in
    isolation.  The real OS → scene → mouseClickEvent routing chain is
    confirmed by the real scene-routing test below.
    """
    axis = panel._y_axes[1]
    ev = _ClickEvent(Qt.MouseButton.LeftButton)
    axis.mouseClickEvent(ev)
    assert panel._active_axis_index == 1
    assert ev.accepted, "handler must accept the left-click event"


def test_mouseClickEvent_left_on_axis_0(panel: GraphPanelView) -> None:
    """Handler-path: left-click on axis 0 calls set_active_axis(0)."""
    axis = panel._y_axes[0]
    ev = _ClickEvent(Qt.MouseButton.LeftButton)
    axis.mouseClickEvent(ev)
    assert panel._active_axis_index == 0
    assert ev.accepted


def test_mouseClickEvent_right_does_not_activate(panel: GraphPanelView) -> None:
    """Handler-path: right-click on an axis must NOT set the active index.

    Right-click is reserved for the context menu; the activation handler
    must ignore non-left buttons.
    """
    axis = panel._y_axes[1]
    ev = _ClickEvent(Qt.MouseButton.RightButton)
    axis.mouseClickEvent(ev)
    assert panel._active_axis_index is None  # unchanged
    assert not ev.accepted, "non-left click must not be accepted by activation handler"


def test_click_is_noop_without_panel_view() -> None:
    """Handler-path: left-click on a bare axis (no panel view) does not crash.

    A bare _AlignedAxisItem (e.g. unit-tested in isolation) has _panel_view=None.
    The handler skips set_active_axis but still accepts the event — the click is
    consumed so it does not bubble further.  No active-axis state exists to check;
    the important guarantee is that nothing raises.
    """
    from valisync.gui.views.graph_panel_view import _AlignedAxisItem

    axis = _AlignedAxisItem(orientation="left")
    # _panel_view is None (default) — must not raise
    ev = _ClickEvent(Qt.MouseButton.LeftButton)
    axis.mouseClickEvent(ev)
    # Event is accepted even without a panel view (handler falls through to accept).
    assert ev.accepted, "bare axis should still accept the click (no bubble)"


# ─── Layer B: real scene-routing ──────────────────────────────────────────────


def test_real_scene_routing_left_click_activates_axis(qtbot: QtBot) -> None:
    """Layer B (real scene-routing): qtbot.mouseClick on viewport activates axis.

    Exercises the full Qt event path:
        qtbot.mouseClick → QGraphicsView.viewport → QGraphicsScene →
        pyqtgraph scene dispatch → _AlignedAxisItem.mouseClickEvent.

    Unlike the handler-path tests above (direct mouseClickEvent call), this
    confirms the routing chain wires up correctly: scene item-at-point
    resolution, pyqtgraph event delivery, and our override all participate.

    Runs offscreen (QT_QPA_PLATFORM=offscreen): the virtual surface delivers
    synthetic press/release events through Qt's normal scene dispatch, which
    pyqtgraph translates into a mouseClickEvent on the axis item at that
    scene position.
    """
    from PySide6.QtWidgets import QApplication

    view = make_two_axis_panel()
    qtbot.addWidget(view)
    view.resize(600, 400)
    view.show()
    qtbot.waitExposed(view)
    # Process pending layout/geometry events so scene items get their positions.
    for _ in range(10):
        QApplication.processEvents()

    # Locate axis 1's spine center in viewport pixel coordinates.
    # _sync_overlay_geometry calls axis.setGeometry(strip) which sets the item's
    # scene-space bounding rect; mapFromScene converts that to viewport pixels.
    axis1 = view._y_axes[1]
    scene_rect = axis1.sceneBoundingRect()
    scene_center = scene_rect.center()
    vp_pt = view.plot_widget.mapFromScene(scene_center)
    vp_pos = QPoint(round(vp_pt.x()), round(vp_pt.y()))

    # Real click via Qt event dispatch (press + release = mouseClickEvent in scene).
    qtbot.mouseClick(
        view.plot_widget.viewport(),
        Qt.MouseButton.LeftButton,
        pos=vp_pos,
    )
    QApplication.processEvents()

    assert view._active_axis_index == 1, (
        f"Expected axis 1 active after real-scene click at scene {scene_center}, "
        f"viewport {vp_pos}, scene_rect={scene_rect}; "
        f"got _active_axis_index={view._active_axis_index!r}. "
        "If the offscreen platform cannot route clicks to scene items, move this "
        "test to tests/realgui/ with @pytest.mark.realgui."
    )


# ─── Task 5 helpers ───────────────────────────────────────────────────────────


def _bare_axis(w: float = 60.0) -> _AlignedAxisItem:
    """Return a bare _AlignedAxisItem for pure headless tests (no scene/view)."""
    it = _AlignedAxisItem(orientation="left")
    it.setWidth(w)
    return it


class _HoverEvent:
    """Duck-typed QGraphicsSceneHoverEvent for hoverMoveEvent / hoverLeaveEvent tests.

    The handler only calls ``ev.pos()`` so a minimal stub is sufficient.
    """

    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        self._pos = QPointF(x, y)

    def pos(self) -> QPointF:
        return self._pos


# ─── Layer A: cursor_for_local mapping (Task 5) ───────────────────────────────


def test_cursor_resize_move_zoom_pan() -> None:
    """Layer A: cursor_for_local maps each AXZONE_* to the correct Qt cursor shape.

    Uses a bare axis (w=60, h=120 explicit) so no scene geometry is needed.
    Coordinates chosen so each zone is hit according to classify_axis_zone:
      - (30, 2)   → GRIP_TOP  (centred-x ≤ half+tol, y ≤ grip_h+tol) → SizeVer
      - (2, 60)   → FRAME     (lx ≤ frame)                            → SizeAll
      - (45, 60)  → ZOOM      (lx ≥ w/2, not border/grip)            → Cross
      - (15, 60)  → PAN       (lx < w/2, not border/grip)            → OpenHand
    """
    it = _bare_axis()
    h = 120.0
    assert it.cursor_for_local(30.0, 2.0, h) == Qt.CursorShape.SizeVerCursor
    assert it.cursor_for_local(2.0, 60.0, h) == Qt.CursorShape.SizeAllCursor
    assert it.cursor_for_local(45.0, 60.0, h) == Qt.CursorShape.CrossCursor
    assert it.cursor_for_local(15.0, 60.0, h) == Qt.CursorShape.OpenHandCursor


# ─── Layer A: hover axis state (Task 5) ───────────────────────────────────────


def test_initial_hover_axis_is_none(panel: GraphPanelView) -> None:
    """_hover_axis_index starts as None (no hover on init)."""
    assert panel._hover_axis_index is None


def test_set_hover_axis_sets_index(panel: GraphPanelView) -> None:
    """set_hover_axis(0) stores 0 in _hover_axis_index."""
    panel.set_hover_axis(0)
    assert panel._hover_axis_index == 0


def test_set_hover_axis_clears_to_none(panel: GraphPanelView) -> None:
    """set_hover_axis(None) clears the hover selection."""
    panel.set_hover_axis(1)
    panel.set_hover_axis(None)
    assert panel._hover_axis_index is None


def test_set_hover_axis_idempotent(panel: GraphPanelView) -> None:
    """Calling set_hover_axis with the same index twice is a no-op (no error)."""
    panel.set_hover_axis(1)
    panel.set_hover_axis(1)
    assert panel._hover_axis_index == 1


# ─── Layer B: _is_active_or_hover + hover handlers (Task 5) ──────────────────


def test_is_active_or_hover_false_without_panel() -> None:
    """Layer B: bare axis (_panel_view=None) is never active-or-hover."""
    ax = _bare_axis()
    assert not ax._is_active_or_hover()


def test_is_active_or_hover_true_when_active(panel: GraphPanelView) -> None:
    """Layer B: axis returns True from _is_active_or_hover when it is the active axis."""
    panel.set_active_axis(0)
    assert panel._y_axes[0]._is_active_or_hover()
    assert not panel._y_axes[1]._is_active_or_hover()


def test_is_active_or_hover_true_when_hovered(panel: GraphPanelView) -> None:
    """Layer B: axis returns True from _is_active_or_hover when it is the hovered axis."""
    panel.set_hover_axis(1)
    assert panel._y_axes[1]._is_active_or_hover()
    assert not panel._y_axes[0]._is_active_or_hover()


def test_hoverMoveEvent_sets_hover_index(panel: GraphPanelView) -> None:
    """Layer B: hoverMoveEvent on axis 0 sets _hover_axis_index to 0.

    Driven directly (handler-path), not via scene routing — the offscreen
    platform does not deliver real hover events through pyqtgraph's scene.
    Verifies that the handler logic reaches set_hover_axis correctly.
    """
    ax = panel._y_axes[0]
    ax.hoverMoveEvent(_HoverEvent(30.0, 60.0))
    assert panel._hover_axis_index == 0


def test_hoverLeaveEvent_clears_hover_index(panel: GraphPanelView) -> None:
    """Layer B: hoverLeaveEvent on axis 0 clears _hover_axis_index to None."""
    panel.set_hover_axis(0)
    panel._y_axes[0].hoverLeaveEvent(_HoverEvent())
    assert panel._hover_axis_index is None


# ─── Task 6: zone-routed drag helpers (Layer B direct-call) ──────────────────

# Geometry constant used to give axis items a non-zero bounding rect without
# needing a shown/laid-out window (pg.AxisItem.width()/.boundingRect() return
# geometry().width/height(), which is 0 until the layout runs after show()).
_ITEM_GEOM = QRectF(0, 0, 72, 200)


def test_begin_drag_grip_bottom_calls_resize_edge(
    panel: GraphPanelView, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Layer B: bottom-grip drag routes to resize_axis_edge(..., 'bottom', ...).

    Drives _begin_axis_drag / _update_axis_drag directly with a stubbed panel
    region — handler-path only. Real drag delivery (OS → pyqtgraph scene →
    mouseDragEvent) and the real panel geometry are Layer C. Honest layering: this
    confirms the bottom-grip branch routes to the VM; it does NOT prove the real
    event chain fires these helpers. The ratio math is covered by the Layer A
    grip_resize_delta tests.
    """
    from PySide6.QtCore import QRectF

    panel.set_active_axis(0)
    it = panel._y_axes[0]
    it.setGeometry(_ITEM_GEOM)  # give the item real dimensions (no show needed)
    # The absolute-tracking update reads the full panel rect; stub it offscreen.
    monkeypatch.setattr(it, "_panel_region", lambda: QRectF(0.0, 0.0, 72.0, 200.0))
    calls: list[tuple[int, str, float]] = []
    monkeypatch.setattr(
        panel.vm,
        "resize_axis_edge",
        lambda i, e, d: calls.append((i, e, round(d, 4))),
    )
    h = it.boundingRect().height()  # 200 after setGeometry
    # lx=centre, ly=h-2 → classify_axis_zone → AXZONE_GRIP_BOTTOM
    it._begin_axis_drag(it.width() / 2, h - 2.0)
    it._update_axis_drag(120.0)  # cursor scene-y inside the stubbed panel region
    assert calls, "resize_axis_edge should have been called"
    assert calls[0][0] == 0, f"expected axis index 0, got {calls[0][0]}"
    assert calls[0][1] == "bottom", f"expected edge 'bottom', got {calls[0][1]!r}"


def test_begin_drag_inner_is_zoom(
    panel: GraphPanelView, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Layer B: right-half (inner) drag triggers set_axis_range on finish.

    Verifies the AXZONE_ZOOM branch: _begin_axis_drag captures the start data
    value; _finish_axis_drag calls set_axis_range(idx, y0, y1).
    """
    panel.set_active_axis(0)
    it = panel._y_axes[0]
    it.setGeometry(_ITEM_GEOM)
    got: list[tuple[int, float, float]] = []
    monkeypatch.setattr(
        panel.vm,
        "set_axis_range",
        lambda i, lo, hi: got.append((i, lo, hi)),
    )
    h = it.boundingRect().height()
    # lx=0.75w → right half = AXZONE_ZOOM; ly well inside (not grip/border)
    it._begin_axis_drag(it.width() * 0.75, h * 0.2)
    it._finish_axis_drag(it.width() * 0.75, h * 0.8)
    assert got, "set_axis_range should have been called (zoom)"
    assert got[0][0] == 0, f"expected axis index 0, got {got[0][0]}"


def test_drag_ignored_when_not_active(
    panel: GraphPanelView, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Layer B: _begin_axis_drag returns False (no VM call) when axis is inactive.

    When _active_axis_index is None (or mismatches this axis's index), the
    drag helpers are a no-op.  No geometry setup needed: the guard fires before
    boundingRect() is ever queried.
    """
    panel.set_active_axis(None)
    it = panel._y_axes[0]
    fired: list[object] = []
    monkeypatch.setattr(panel.vm, "resize_axis_edge", lambda *a: fired.append(a))
    started = it._begin_axis_drag(it.width() / 2, 2.0)
    assert started is False, "_begin_axis_drag must return False for inactive axis"
    assert not fired, "resize_axis_edge must not be called for an inactive axis"


# ─── Fix: defer the axis-move rebuild off the QDrag modal stack ───────────────
# Applying the relayout inside dropEvent (which runs inside the move's blocking
# QDrag.exec) rebuilds the axis items while pyqtgraph's GraphicsScene still holds
# press/drag/hover references to the drag's source item. The next gesture is then
# delivered to that destroyed item (first resize/move after a move broke: a no-op,
# or — once the stale press bookkeeping was cleared — a re-entrant QDrag hang). The
# fix defers the move to the next event-loop turn and, after the rebuild, drops the
# scene's stale bookkeeping. End-to-end proof is Layer C
# (tests/realgui/test_move_then_resize.py).


def test_reset_scene_drag_state_clears_bookkeeping() -> None:
    """Layer A: reset_scene_drag_state zeroes the GraphicsScene drag/hover fields."""

    class _Scene:
        def __init__(self) -> None:
            self.dragButtons = [Qt.MouseButton.LeftButton]
            self.dragItem = object()
            self.clickEvents = [object()]
            self.lastDrag = object()
            self.lastHoverEvent = object()

    s = _Scene()
    reset_scene_drag_state(s)
    assert s.dragButtons == []
    assert s.dragItem is None
    assert s.clickEvents == []
    assert s.lastDrag is None
    # lastHoverEvent matters most: pyqtgraph picks a new drag's target from it, so a
    # stale value re-binds the next gesture to the rebuilt-away item.
    assert s.lastHoverEvent is None


def test_reset_scene_drag_state_none_is_safe() -> None:
    """Layer A: reset_scene_drag_state(None) is a no-op (defensive, no crash)."""
    reset_scene_drag_state(None)


def test_apply_deferred_axis_move_moves_and_resets_scene(
    panel: GraphPanelView, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Layer B (wiring): _apply_deferred_axis_move relocates the axis AND drops the
    scene's stale press/drag/hover bookkeeping, so the next gesture re-discovers the
    live item instead of the rebuilt-away one.

    This is the deferred callback dropEvent schedules; it runs after the QDrag has
    unwound. End-to-end proof (real OS drag) is Layer C.
    """
    panel.set_active_axis(0)
    scene = panel.plot_widget.scene()
    assert scene is not None
    # Seed the stale state pyqtgraph leaves when a modal QDrag eats the release.
    scene.dragButtons = [Qt.MouseButton.LeftButton]
    scene.dragItem = object()
    scene.clickEvents = [object()]
    scene.lastDrag = object()
    scene.lastHoverEvent = object()
    calls: list[tuple[int, int, int | None]] = []
    monkeypatch.setattr(panel.vm, "move_axis_to_column", lambda *a: calls.append(a))

    panel._apply_deferred_axis_move(1, 0, None)

    assert calls == [(1, 0, None)], "the deferred callback must relocate the axis"
    assert scene.dragButtons == []
    assert scene.dragItem is None
    assert scene.clickEvents == []
    assert scene.lastDrag is None
    assert scene.lastHoverEvent is None
