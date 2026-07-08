"""Layer C: パネル/ファイル/ソースの可視アフォーダンス実 OS 入力 (SH-06/08/10/15)。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_panel_add_button_click_emits(qtbot: QtBot) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QToolButton

    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = GraphPanelView(GraphPanelVM(Session()))
    qtbot.addWidget(view)
    view.resize(500, 400)
    view.show()
    qtbot.waitExposed(view)
    fired: list[bool] = []
    view.add_panel_requested.connect(lambda: fired.append(True))
    btn = view.findChild(QToolButton, "add_panel_button")
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert fired == [True], "パネル追加ボタンの実クリックでシグナルが飛ばない"


def test_data_source_list_select_roots_tree(qtbot: QtBot, tmp_path: Path) -> None:
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.data_explorer_view import DataExplorerView

    view = DataExplorerView(AppViewModel(), sources_file=None)
    qtbot.addWidget(view)
    view.resize(700, 400)
    view.show()
    qtbot.waitExposed(view)
    d = tmp_path / "src"
    d.mkdir()
    view.add_source(d)
    view.source_list.setCurrentRow(0)
    QApplication.processEvents()
    rooted = Path(view.fs_model.filePath(view.tree.rootIndex()))
    assert rooted == d, "ソースリスト選択で tree の root が切り替わらない"
