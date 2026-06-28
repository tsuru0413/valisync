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
from PySide6.QtCore import QPoint, Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.gui._panel_factory import make_two_axis_panel
from valisync.gui.views.graph_panel_view import GraphPanelView

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
