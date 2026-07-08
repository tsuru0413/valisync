from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.views.shell_actions import ShellActions


def test_registry_defines_core_commands(qtbot: QtBot) -> None:
    w = QWidget()
    qtbot.addWidget(w)
    sa = ShellActions(w)
    assert set(sa.actions) >= {"open", "open_folder", "export"}
    assert sa.action("open").shortcut() == QKeySequence("Ctrl+O")
    assert sa.action("export").shortcut() == QKeySequence("Ctrl+E")
    # ツールチップにショートカットが載る(発見性)
    assert "Ctrl+O" in sa.action("open").toolTip()
    # export はデータ無し時 disabled(出口を予告するが押せない)
    assert sa.action("export").isEnabled() is False
    assert sa.action("open").isEnabled() is True
