"""ShellActions — central QAction registry (SH-05/06/14 foundation).

Each shell command is defined ONCE here (text + registry icon + shortcut +
tooltip-with-shortcut + statusTip). Menus, toolbars and context menus mount
these same QAction objects. `triggered` is connected by the owner (MainWindow),
so this class stays a pure definition layer and is testable without a window.
"""

from __future__ import annotations

from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QWidget

from valisync.gui import strings as S
from valisync.gui.strings import mn
from valisync.gui.theme import icons


class ShellActions:
    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self.actions: dict[str, QAction] = {}

        self._add(
            "open",
            S.ACTION_OPEN,
            icons.icon("open"),
            "Ctrl+O",
            S.WELCOME_OPEN_LABEL,
        )
        self._add(
            "open_folder",
            # File メニューにのみ掲載される QAction (mn() 合成形)。ツールバー側は
            # main_window.py の action_data_explorer が同じ素形 (S.ACTION_DATA_EXPLORER)
            # を非付与のまま使う (G-39 — 同一ハンドラの別文言を解消)。
            mn(S.ACTION_DATA_EXPLORER, "D"),
            icons.icon("open_folder"),
            "Ctrl+Shift+O",
            S.STATUS_OPEN_DATA_EXPLORER,
        )
        exp = self._add(
            "export",
            S.ACTION_EXPORT,
            icons.icon("export"),
            "Ctrl+E",
            "表示中の信号を CSV に書き出す",
        )
        exp.setEnabled(False)  # データ読込まで無効(1b で状態連動)

    def _add(
        self,
        key: str,
        text: str,
        icon: QIcon,
        shortcut: str | None,
        status: str,
    ) -> QAction:
        act = QAction(icon, text, self._parent)
        tip = status
        if shortcut is not None:
            act.setShortcut(QKeySequence(shortcut))
            tip = f"{status} ({shortcut})"
        act.setToolTip(tip)
        act.setStatusTip(status)
        self.actions[key] = act
        return act

    def action(self, key: str) -> QAction:
        return self.actions[key]
