"""Layer C: パネル/ソースの可視アフォーダンス実 OS 入力 (SH-06/08/10/15)。

合成 qtbot ではなく実クリック(_realgui_input.at)でボタン/リスト項目を押下し、
OS→Qt ヒットテスト経由でシグナル/選択が起きることを検証する(Layer B との違い)。
視覚結果(tree の root 切替)はスクショで目視判定する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def _show_top(qtbot: QtBot, w, size: tuple[int, int]) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    qtbot.addWidget(w)
    w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    w.setGeometry(220, 220, size[0], size[1])
    w.show()
    w.raise_()
    w.activateWindow()
    qtbot.waitExposed(w)
    QApplication.processEvents()


def _real_click_global(w, gp) -> None:  # type: ignore[no-untyped-def]
    dpr = w.devicePixelRatioF()
    x, y = round(gp.x() * dpr), round(gp.y() * dpr)
    at(x, y, LDOWN)
    at(x, y, LUP)


def test_panel_add_button_click_emits(qtbot: QtBot) -> None:
    skip_unless_real_display()
    from PySide6.QtWidgets import QToolButton

    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = GraphPanelView(GraphPanelVM(Session()))
    _show_top(qtbot, view, (500, 400))
    fired: list[bool] = []
    view.add_panel_requested.connect(lambda: fired.append(True))
    btn = view.findChild(QToolButton, "add_panel_button")
    qtbot.waitUntil(lambda: btn.isVisible() and btn.width() > 0, timeout=3000)
    _real_click_global(view, btn.mapToGlobal(btn.rect().center()))
    qtbot.waitUntil(lambda: fired == [True], timeout=2000)
    assert fired == [True], "パネル追加ボタンの実クリックでシグナルが飛ばない"


def test_data_source_list_select_roots_tree(qtbot: QtBot, tmp_path: Path) -> None:
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.data_explorer_view import DataExplorerView

    view = DataExplorerView(AppViewModel(), sources_file=None)
    _show_top(qtbot, view, (700, 400))
    d = tmp_path / "src"
    d.mkdir()
    view.add_source(d)
    QApplication.processEvents()
    item = view.source_list.item(0)
    qtbot.waitUntil(
        lambda: view.source_list.visualItemRect(item).height() > 0, timeout=3000
    )
    from PySide6.QtCore import QPoint

    # visualItemRect の幅は項目の論理幅で viewport 幅を超えうる(その center.x は
    # viewport 外=右隣ペインに着弾する)。クリック x を viewport 内へクランプする。
    rect = view.source_list.visualItemRect(item)
    vp = view.source_list.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    gp = vp.mapToGlobal(local)
    _real_click_global(view, gp)
    QApplication.processEvents()
    qtbot.waitUntil(lambda: view.source_list.currentRow() == 0, timeout=2000)
    QApplication.processEvents()
    # 選択反映後(tree が root 切替済み)の状態をスクショ判定。
    shot = tmp_path / "source_select_roots_tree.png"
    QApplication.primaryScreen().grabWindow(0).save(str(shot))
    rooted = Path(view.fs_model.filePath(view.tree.rootIndex()))
    print(
        f"[panel_source] currentRow={view.source_list.currentRow()} rooted={rooted} screenshot={shot}"
    )
    assert rooted == d, (
        f"ソースリスト実クリックで tree の root が切り替わらない。screenshot: {shot}"
    )
