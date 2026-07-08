"""Layer C: Ctrl+O が open_file スロットへ到達するか(実 OS キー入力)。

実 OS キー(`keybd_event`)は前面ウィンドウへ届くため、実クリックで前面化/フォーカス
してから Ctrl+O を発行する。QFileDialog はモーダルなので open_file をスタブし
「実キー→ショートカット context→スロット発火」を確認する。合成 QTest.keyClick は
この OS→Qt キー経路と focus を迂回する(Layer B)。

honest RED: File メニュー/ツールバーに open アクションを載せ忘れる、または
shortcut を外すと Ctrl+O がスロットに届かず fired が空になる。
"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    VK_CONTROL,
    at,
    key,
    skip_unless_real_display,
)

pytestmark = pytest.mark.realgui

VK_O = 0x4F


def _focus_by_real_click(mw) -> None:  # type: ignore[no-untyped-def]
    """メニューバー右端の空き領域を実クリックしてウィンドウを前面/フォーカスへ。

    メニュー項目の外側なので誤ってメニューを開かない。
    """
    from PySide6.QtCore import QPoint

    mb = mw.menuBar()
    p = mb.mapToGlobal(QPoint(mb.width() - 8, mb.height() // 2))
    dpr = mw.devicePixelRatioF()
    x, y = round(p.x() * dpr), round(p.y() * dpr)
    at(x, y, LDOWN)
    at(x, y, LUP)


def test_ctrl_o_triggers_open(qtbot: QtBot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    fired: list[int] = []
    # 構築前にクラスを patch(connect が捕捉する bound method を stub 化。実 open_file
    # のモーダル QFileDialog がハングするため)。
    monkeypatch.setattr(MainWindow, "open_file", lambda self, *a: fired.append(1))
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    mw.setGeometry(200, 200, 900, 600)
    mw.show()
    mw.raise_()
    mw.activateWindow()
    qtbot.waitExposed(mw)
    QApplication.processEvents()

    _focus_by_real_click(mw)
    QApplication.processEvents()

    # 実 OS キー: Ctrl 保持 → O → Ctrl 解放。
    key(VK_CONTROL, up=False)
    key(VK_O)
    key(VK_CONTROL, down=False)

    qtbot.waitUntil(lambda: fired == [1], timeout=2000)
    assert fired == [1], (
        "Ctrl+O(実キー)が open_file に届かない(open アクションの shortcut/配線/focus を確認)"
    )
