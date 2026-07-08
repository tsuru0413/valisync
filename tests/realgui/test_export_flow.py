"""Layer C: Ctrl+E が export_csv へ到達するか (実 OS キー入力)。

実 OS キー(`keybd_event`)は前面ウィンドウへ届くため、実クリックで前面化/フォーカス
してから Ctrl+E を発行する。合成 QTest.keyClick は OS→Qt キー経路と focus/有効化を
迂回する(Layer B)。

honest RED: File メニュー/ツールバーに export を載せ忘れる、shortcut を外す、
またはデータ無しで無効のままだと Ctrl+E が届かず fired が空になる。
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

VK_E = 0x45


def _focus_by_real_click(mw) -> None:  # type: ignore[no-untyped-def]
    """メニューバー右端の空き領域を実クリックしてウィンドウを前面/フォーカスへ。"""
    from PySide6.QtCore import QPoint

    mb = mw.menuBar()
    p = mb.mapToGlobal(QPoint(mb.width() - 8, mb.height() // 2))
    dpr = mw.devicePixelRatioF()
    x, y = round(p.x() * dpr), round(p.y() * dpr)
    at(x, y, LDOWN)
    at(x, y, LUP)


def test_ctrl_e_triggers_export(qtbot: QtBot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    fired: list[int] = []
    # 構築前にクラスを patch (connect が捕捉する bound method を stub 化)。
    monkeypatch.setattr(MainWindow, "export_csv", lambda self, *a: fired.append(1))
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    # export はデータ有りで有効。ロード成功を模擬して有効化する。
    mw.app_vm.register_loaded("csv_1")
    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    mw.setGeometry(200, 200, 900, 600)
    mw.show()
    mw.raise_()
    mw.activateWindow()
    qtbot.waitExposed(mw)
    QApplication.processEvents()

    _focus_by_real_click(mw)
    QApplication.processEvents()

    # 実 OS キー: Ctrl 保持 → E → Ctrl 解放。
    key(VK_CONTROL, up=False)
    key(VK_E)
    key(VK_CONTROL, down=False)

    qtbot.waitUntil(lambda: fired == [1], timeout=2000)
    assert fired == [1], (
        "Ctrl+E(実キー)が export_csv に届かない (export の shortcut/有効化/配線/focus を確認)"
    )
