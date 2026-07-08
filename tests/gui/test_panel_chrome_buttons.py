# tests/gui/test_panel_chrome_buttons.py
from __future__ import annotations

from PySide6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


def _make_panel(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = GraphPanelView(GraphPanelVM(Session()))
    qtbot.addWidget(view)
    return view


def _button(view: object, name: str) -> QToolButton:
    btn = view.findChild(QToolButton, name)  # type: ignore[attr-defined]
    assert isinstance(btn, QToolButton), f"{name} not found"
    return btn


def test_add_panel_button_emits_signal(qtbot: QtBot) -> None:
    view = _make_panel(qtbot)
    fired: list[bool] = []
    view.add_panel_requested.connect(lambda: fired.append(True))
    _button(view, "add_panel_button").click()
    assert fired == [True]


def test_remove_panel_button_emits_signal(qtbot: QtBot) -> None:
    view = _make_panel(qtbot)
    fired: list[bool] = []
    view.remove_panel_requested.connect(lambda: fired.append(True))
    _button(view, "remove_panel_button").click()
    assert fired == [True]


def test_set_removable_toggles_remove_button(qtbot: QtBot) -> None:
    view = _make_panel(qtbot)
    remove_btn = _button(view, "remove_panel_button")
    assert remove_btn.isEnabled()  # default removable
    view.set_removable(False)
    assert not remove_btn.isEnabled()
    view.set_removable(True)
    assert remove_btn.isEnabled()


def test_plot_widget_stays_at_panel_origin(qtbot: QtBot) -> None:
    # SH-06 regression: chrome must overlay (float), not reserve a layout row.
    # A reserved row shifts plot_widget down ~27px so panel-space mouse events
    # (event.position()) diverge from plot_widget-space hit-test rects
    # (_plot_rect_in_widget / mapToScene) -> zone/curve-grab off by ~27px.
    from PySide6.QtCore import QPoint

    view = _make_panel(qtbot)
    view.resize(500, 400)
    view.layout().activate()  # force geometry even offscreen
    assert view.plot_widget.pos() == QPoint(0, 0), (
        f"plot_widget at {view.plot_widget.pos()}, not panel origin (0,0); "
        "chrome row shifts GraphPanelView hit-test coords (SH-06)"
    )
