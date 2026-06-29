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
