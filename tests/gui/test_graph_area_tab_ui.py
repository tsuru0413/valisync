"""Tests for GraphAreaView tab UI — SH-02 (corner + button & Ctrl+T).

Tests the affordances for adding a new tab:
- Corner widget "+" button
- Ctrl+T keyboard shortcut
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QToolButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM


def _make_area(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from valisync.gui.views.graph_area_view import GraphAreaView

    vm = GraphAreaVM(AppViewModel(Session()))
    view = GraphAreaView(vm, panel_factory=lambda _vm: QLabel())
    qtbot.addWidget(view)
    return view


def test_corner_new_tab_button_adds_tab(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    btn = view.tabs.cornerWidget()
    assert isinstance(btn, QToolButton)
    assert btn.objectName() == "new_tab_button"
    assert view.tabs.count() == 1
    btn.click()
    assert view.tabs.count() == 2
    assert view.vm.active_tab_index == 1  # add_tab is new tab active


def test_ctrl_t_shortcut_adds_tab(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    assert view._new_tab_shortcut.key() == QKeySequence("Ctrl+T")
    view._new_tab_shortcut.activated.emit()  # verify connection
    assert view.tabs.count() == 2
