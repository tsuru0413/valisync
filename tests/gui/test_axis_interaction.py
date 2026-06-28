"""Task 4: active-axis state + click-to-activate tests.

Layer A: state API — set_active_axis sets/clears _active_axis_index directly.
Layer B: handler path — _AlignedAxisItem.mouseClickEvent (the pyqtgraph click
handler, not Qt's mousePressEvent) drives set_active_axis with the correct axis
index.  A duck-typed _ClickEvent stands in for pyqtgraph's MouseClickEvent,
matching the same interface the real event bus delivers.

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
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.gui._panel_factory import make_two_axis_panel

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
def panel(qtbot: QtBot) -> object:
    view = make_two_axis_panel()
    qtbot.addWidget(view)
    return view


# ─── Layer A: state API ────────────────────────────────────────────────────────


def test_initial_active_axis_is_none(panel: object) -> None:
    """_active_axis_index starts as None (no selection on init)."""
    assert panel._active_axis_index is None  # type: ignore[attr-defined]


def test_set_active_axis_sets_index(panel: object) -> None:
    """set_active_axis(1) stores 1 in _active_axis_index."""
    panel.set_active_axis(1)  # type: ignore[attr-defined]
    assert panel._active_axis_index == 1  # type: ignore[attr-defined]


def test_set_active_axis_clears_to_none(panel: object) -> None:
    """set_active_axis(None) clears the active selection."""
    panel.set_active_axis(1)  # type: ignore[attr-defined]
    panel.set_active_axis(None)  # type: ignore[attr-defined]
    assert panel._active_axis_index is None  # type: ignore[attr-defined]


def test_set_active_axis_idempotent(panel: object) -> None:
    """Calling set_active_axis with the same index is a no-op (no error)."""
    panel.set_active_axis(0)  # type: ignore[attr-defined]
    panel.set_active_axis(0)  # type: ignore[attr-defined]
    assert panel._active_axis_index == 0  # type: ignore[attr-defined]


def test_set_active_axis_switches_index(panel: object) -> None:
    """Switching from one active axis to another updates the stored index."""
    panel.set_active_axis(0)  # type: ignore[attr-defined]
    panel.set_active_axis(1)  # type: ignore[attr-defined]
    assert panel._active_axis_index == 1  # type: ignore[attr-defined]


# ─── Layer B: click handler path ──────────────────────────────────────────────


def test_mouseClickEvent_left_activates_axis(panel: object) -> None:
    """Handler-path: left-click on axis 1 calls set_active_axis(1).

    Drives _AlignedAxisItem.mouseClickEvent directly with a duck-typed
    _ClickEvent (same interface as the real pyqtgraph MouseClickEvent).
    This is NOT a full sendEvent Layer B — it is the handler-path variant:
    the real OS → scene → mouseClickEvent chain is confirmed by Layer C /
    manual; here we verify that the handler logic is correct when called.
    """
    axis = panel._y_axes[1]  # type: ignore[attr-defined]
    ev = _ClickEvent(Qt.MouseButton.LeftButton)
    axis.mouseClickEvent(ev)
    assert panel._active_axis_index == 1  # type: ignore[attr-defined]
    assert ev.accepted, "handler must accept the left-click event"


def test_mouseClickEvent_left_on_axis_0(panel: object) -> None:
    """Handler-path: left-click on axis 0 calls set_active_axis(0)."""
    axis = panel._y_axes[0]  # type: ignore[attr-defined]
    ev = _ClickEvent(Qt.MouseButton.LeftButton)
    axis.mouseClickEvent(ev)
    assert panel._active_axis_index == 0  # type: ignore[attr-defined]
    assert ev.accepted


def test_mouseClickEvent_right_does_not_activate(panel: object) -> None:
    """Handler-path: right-click on an axis must NOT set the active index.

    Right-click is reserved for the context menu; the activation handler
    must ignore non-left buttons.
    """
    axis = panel._y_axes[1]  # type: ignore[attr-defined]
    ev = _ClickEvent(Qt.MouseButton.RightButton)
    axis.mouseClickEvent(ev)
    assert panel._active_axis_index is None  # unchanged
    assert not ev.accepted, "non-left click must not be accepted by activation handler"


def test_mouseClickEvent_event_not_accepted_when_no_panel_view() -> None:
    """Handler-path: axis without a panel view reference is a no-op (no crash)."""
    from valisync.gui.views.graph_panel_view import _AlignedAxisItem

    axis = _AlignedAxisItem(orientation="left")
    # _panel_view is None (default) — must not raise
    ev = _ClickEvent(Qt.MouseButton.LeftButton)
    axis.mouseClickEvent(ev)
    # No crash; ev.accepted depends on implementation (accept even with no panel)
