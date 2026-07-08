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
