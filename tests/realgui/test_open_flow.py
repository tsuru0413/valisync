"""Layer C: Ctrl+O が open_file スロットへ到達するか(実 OS キー入力)。

headless の QTest.keyClick でも配線は検証できるが、ショートカットの
context / focus は実ウィンドウでしか正確に出ない。QFileDialog はモーダルなので
open_file をスタブし「ショートカット→スロット発火」を確認する。

honest RED: File メニュー/ツールバーに open アクションを載せ忘れる、または
shortcut を外すと Ctrl+O がスロットに届かず fired が空になる。
"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_ctrl_o_triggers_open(qtbot: QtBot, monkeypatch) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    fired: list[int] = []
    # Patch the CLASS before constructing: __init__ connects the Open QAction to
    # self.open_file, binding the method at connect() time. An instance-level
    # patch applied after construction would not change what the connected action
    # invokes, and the real open_file opens a modal QFileDialog that would hang
    # the run.
    monkeypatch.setattr(MainWindow, "open_file", lambda self, *a: fired.append(1))
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    mw.show()
    qtbot.waitExposed(mw)
    QApplication.processEvents()

    qtbot.keyClick(mw, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()

    assert fired == [1], (
        "Ctrl+O が open_file に届かない(open アクションの shortcut/配線を確認)"
    )
