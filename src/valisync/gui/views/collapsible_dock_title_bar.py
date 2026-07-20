"""ドック共通の展開時タイトルバー (edge-aware-dock-collapse で辺対応レールへ移行)。

QDockWidget に最小化フラグは無いため setTitleBarWidget で差す。既定タイトルバー
(フロート/閉じる)を置換するので自前で持つ。chevron は「畳み要求」を出すだけで、
実際の畳み (dock.hide()+辺レールにタブ) は MainWindow が担う。フロート中は送り先の
辺が無いので chevron を無効化する。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QToolButton,
    QWidget,
)

from valisync.gui.theme import icons


class CollapsibleDockTitleBar(QWidget):
    """chevron(畳み要求)+タイトル+フロート+閉じるを持つ展開時タイトルバー。"""

    collapse_requested = Signal()

    def __init__(
        self,
        dock: QDockWidget,
        main_window: QMainWindow,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dock = dock
        self._main_window = main_window

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        self._toggle_button = QToolButton()
        self._toggle_button.setAutoRaise(True)
        self._toggle_button.setIcon(icons.icon("chevron_right"))
        self._toggle_button.setToolTip("折りたたむ")
        self._toggle_button.clicked.connect(self.collapse_requested.emit)
        lay.addWidget(self._toggle_button)

        self._title = QLabel(title)
        lay.addWidget(self._title)
        lay.addStretch(1)

        self._float_button = QToolButton()
        self._float_button.setAutoRaise(True)
        self._float_button.setText("❐")
        self._float_button.setToolTip("フロート")
        self._float_button.clicked.connect(
            lambda: self._dock.setFloating(not self._dock.isFloating())
        )
        lay.addWidget(self._float_button)

        self._close_button = QToolButton()
        self._close_button.setAutoRaise(True)
        self._close_button.setText("✕")
        self._close_button.setToolTip("閉じる")
        self._close_button.clicked.connect(self._dock.close)
        lay.addWidget(self._close_button)

        # フロート中は畳み先の辺が無いので無効化 (再ドッキングで有効化)。
        dock.topLevelChanged.connect(self._on_floating_changed)

    def _on_floating_changed(self, floating: bool) -> None:
        self._toggle_button.setEnabled(not floating)
