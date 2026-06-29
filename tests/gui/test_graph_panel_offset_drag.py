"""Layer B: オフセットドラッグジェスチャ (R14)。実イベント経路 (sendEvent)。

Honest layering note: ``apply_dialog_fn`` injection proves the dialog *wiring*
(signal/cancel → emit/restore) but NOT the real modal QDialog.exec() and OS
confirm path — that is Layer C (Task 7 realgui).
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.gui._panel_factory import make_single_signal_panel
from valisync.gui.views.graph_panel_view import GraphPanelView


def _shown(qtbot: QtBot, apply_dialog_fn=None) -> GraphPanelView:
    base = make_single_signal_panel()
    # Rebuild with the injected dialog fn (factory builds the default panel).
    view = GraphPanelView(base.vm, apply_dialog_fn=apply_dialog_fn)
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


def _center(view) -> QPointF:
    return view._plot_rect_in_widget().center()


def _send(view, etype, local: QPointF) -> None:
    glob = view.mapToGlobal(local.toPoint())
    ev = QMouseEvent(
        etype,
        local,
        QPointF(glob),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view, ev)


def _press_drag(view, dx_px: float):
    start = _center(view)
    target = QPointF(start.x() + dx_px, start.y())
    _send(view, QEvent.Type.MouseButtonPress, start)
    _send(view, QEvent.Type.MouseMove, target)
    return start, target


def test_press_on_curve_activates_offset_drag(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    _send(view, QEvent.Type.MouseButtonPress, _center(view))
    assert view._offset_drag_key is not None


def test_drag_previews_horizontal_shift(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    key = sorted(view._items.keys())[0]
    x_before = np.asarray(view.curve_xy(key)[0]).copy()
    _press_drag(view, dx_px=120.0)
    x_after = np.asarray(view.curve_xy(key)[0])
    # Rightward drag → positive Δt → every x increased by the same amount.
    delta = x_after - x_before
    assert float(delta.min()) > 0.0
    np.testing.assert_allclose(delta, delta[0])


def test_release_signal_scope_emits_request(qtbot: QtBot) -> None:
    captured: list[tuple] = []
    view = _shown(qtbot, apply_dialog_fn=lambda key, dt: "signal")
    view.offset_apply_requested.connect(lambda k, dt, sc: captured.append((k, dt, sc)))
    key = sorted(view._items.keys())[0]
    _start, target = _press_drag(view, dx_px=120.0)
    _send(view, QEvent.Type.MouseButtonRelease, target)
    for _ in range(3):  # let the deferred (singleShot) dialog resolve
        QApplication.processEvents()
    assert len(captured) == 1
    k, dt, sc = captured[0]
    assert k == key and sc == "signal" and dt > 0.0
    assert view._offset_drag_key is None


def test_cancel_via_dialog_restores_and_no_emit(qtbot: QtBot) -> None:
    captured: list[tuple] = []
    view = _shown(qtbot, apply_dialog_fn=lambda key, dt: None)  # cancel
    view.offset_apply_requested.connect(lambda k, dt, sc: captured.append((k, dt, sc)))
    key = sorted(view._items.keys())[0]
    x_before = np.asarray(view.curve_xy(key)[0]).copy()
    _start, target = _press_drag(view, dx_px=120.0)
    _send(view, QEvent.Type.MouseButtonRelease, target)
    for _ in range(3):
        QApplication.processEvents()
    assert captured == []
    np.testing.assert_allclose(np.asarray(view.curve_xy(key)[0]), x_before)
    assert view._offset_drag_key is None


def test_escape_cancels_drag_and_restores(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    key = sorted(view._items.keys())[0]
    x_before = np.asarray(view.curve_xy(key)[0]).copy()
    _press_drag(view, dx_px=120.0)
    esc = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(view, esc)
    np.testing.assert_allclose(np.asarray(view.curve_xy(key)[0]), x_before)
    assert view._offset_drag_key is None


def test_refresh_cancels_drag_when_curve_removed(qtbot: QtBot) -> None:
    """Guard (§9): drag is cancelled when the active curve disappears during refresh.

    The production guard in refresh() calls _cancel_offset_drag() when
    _offset_drag_key is no longer in _items.  Removing the signal via the VM
    triggers a synchronous refresh() via the subscription; this test verifies
    that path without touching the production guard code.
    """
    captured: list[tuple] = []
    view = _shown(qtbot)
    view.offset_apply_requested.connect(lambda k, dt, sc: captured.append((k, dt, sc)))
    key = sorted(view._items.keys())[0]
    _press_drag(view, dx_px=30.0)
    assert view._offset_drag_key is not None  # drag is active before removal
    # remove_signal notifies the VM subscriber synchronously → refresh() fires,
    # the guard sees _offset_drag_key absent from _items, and cancels the drag.
    view.vm.remove_signal(key)
    assert view._offset_drag_key is None
    assert captured == []  # cancel must NOT emit offset_apply_requested


def _spy_grab(view) -> tuple[list, list]:
    """Shadow grabMouse/releaseMouse with counters (instance-attr shadowing).

    Bug A is fundamentally a Layer C concern: real OS drags deliver MOVE events to
    the child QGraphicsView, not the parent GraphPanelView, so without an explicit
    mouse grab the offset commits Δt=0.  sendEvent bypasses the grab entirely, so a
    Layer B test cannot prove the behaviour — only that begin grabs and every
    terminal path releases (a grab leak would freeze the real app).  realgui
    (test_offset_drag.py) is the behavioural gate.
    """
    grabs: list[int] = []
    releases: list[int] = []
    view.grabMouse = lambda: grabs.append(1)  # type: ignore[method-assign]
    view.releaseMouse = lambda: releases.append(1)  # type: ignore[method-assign]
    return grabs, releases


def test_offset_drag_grabs_on_begin_releases_on_apply(qtbot: QtBot) -> None:
    view = _shown(qtbot, apply_dialog_fn=lambda key, dt: "signal")
    grabs, releases = _spy_grab(view)
    _start, target = _press_drag(view, dx_px=120.0)
    assert view._offset_drag_key is not None
    assert len(grabs) == 1  # begin grabbed the mouse
    _send(view, QEvent.Type.MouseButtonRelease, target)
    for _ in range(3):
        QApplication.processEvents()
    assert view._offset_drag_key is None
    assert len(releases) >= 1  # released so the deferred dialog / next gesture is free


def test_offset_drag_releases_on_escape(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    grabs, releases = _spy_grab(view)
    _press_drag(view, dx_px=120.0)
    assert len(grabs) == 1
    esc = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(view, esc)
    assert view._offset_drag_key is None
    assert len(releases) >= 1  # Escape must not leak the grab


def test_offset_drag_releases_when_curve_removed(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    grabs, releases = _spy_grab(view)
    key = sorted(view._items.keys())[0]
    _press_drag(view, dx_px=30.0)
    assert len(grabs) == 1
    view.vm.remove_signal(key)  # synchronous refresh → guard cancels the drag
    assert view._offset_drag_key is None
    assert len(releases) >= 1  # the cancel path must release the grab


def test_press_zone_plot_no_nearby_curve_no_drag(qtbot: QtBot) -> None:
    """Negative path: ZONE_PLOT press with no nearby curve must not start offset drag.

    The linear signal (v=t) passes through the geometric centre of the plot but
    is far from the top-left corner.  _curve_at returns None there, so the
    ``if key is not None`` guard in mousePressEvent prevents activation.
    """
    view = _shown(qtbot)
    rect = view._plot_rect_in_widget()
    corner = QPointF(rect.left() + 3.0, rect.top() + 3.0)
    _send(view, QEvent.Type.MouseButtonPress, corner)
    assert view._offset_drag_key is None
