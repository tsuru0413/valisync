"""Layer C: タブ操作アフォーダンスの実 OS 入力 (SH-02/04/13)。"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def _make_shown_area(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication, QLabel

    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.graph_area_view import GraphAreaView

    vm = GraphAreaVM(AppViewModel(Session()))
    view = GraphAreaView(vm, panel_factory=lambda _vm: QLabel())
    qtbot.addWidget(view)
    view.resize(600, 400)
    view.show()
    qtbot.waitExposed(view)
    QApplication.processEvents()
    return view


def test_corner_button_click_adds_tab(qtbot: QtBot) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    view = _make_shown_area(qtbot)
    btn = view.tabs.cornerWidget()
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert view.tabs.count() == 2, "コーナー + の実クリックで新規タブが増えない"


def test_double_click_tab_renames(qtbot: QtBot) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    view = _make_shown_area(qtbot)
    bar = view.tabs.tabBar()
    center = bar.tabRect(0).center()
    qtbot.mouseDClick(bar, Qt.MouseButton.LeftButton, pos=center)
    QApplication.processEvents()
    assert view._rename_editor is not None, "ダブルクリックで改名エディタが出ない"
    qtbot.keyClicks(view._rename_editor, "renamed")
    qtbot.keyClick(view._rename_editor, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert view.vm.tabs()[0].name == "renamed"
