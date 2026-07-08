"""Layer C: Ctrl+E が export_csv へ到達するか (実 OS キー入力).

honest RED: File メニュー/ツールバーに export を載せ忘れる、shortcut を外す、
またはデータ無しで無効のままだと Ctrl+E が届かず fired が空になる。
"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_ctrl_e_triggers_export(qtbot: QtBot, monkeypatch) -> None:
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
    mw.show()
    qtbot.waitExposed(mw)
    QApplication.processEvents()

    qtbot.keyClick(mw, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()

    assert fired == [1], (
        "Ctrl+E が export_csv に届かない (export の shortcut/有効化/配線を確認)"
    )
