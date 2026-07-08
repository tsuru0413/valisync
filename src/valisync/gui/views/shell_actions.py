"""ShellActions — central QAction registry (SH-05/06/14 foundation).

Each shell command is defined ONCE here (text + standard icon + shortcut +
tooltip-with-shortcut + statusTip). Menus, toolbars and context menus mount
these same QAction objects. `triggered` is connected by the owner (MainWindow),
so this class stays a pure definition layer and is testable without a window.
"""

from __future__ import annotations

from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QStyle, QWidget


class ShellActions:
    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        style = parent.style()
        self.actions: dict[str, QAction] = {}

        self._add(
            "open",
            "開く…",
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Ctrl+O",
            "計測ファイルを開く",
        )
        self._add(
            "open_folder",
            "フォルダを開く…",
            style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            "Ctrl+Shift+O",
            "データソースフォルダを登録する",
        )
        exp = self._add(
            "export",
            "エクスポート…",
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
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
