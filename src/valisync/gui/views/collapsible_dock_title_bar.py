"""ドック共通の折りたたみタイトルバー (collapsible-docks 増分C)。

QDockWidget に最小化フラグは無いため setTitleBarWidget で差す。既定タイトルバー
(フロート/閉じる)を置換するので、それらを自前で持つ。折りたたみ=内容 hide+
dock の maxHeight をタイトルバー高へクランプ、展開=クランプ解除+resizeDocks で
高さ復元 (Qt はクランプ解除だけでは自動再拡大しない場合があるため)。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QToolButton,
    QWidget,
)

from valisync.gui.theme import icons

_QWIDGETSIZE_MAX = 16777215  # Qt QWIDGETSIZE_MAX (import 不確実性を避け定数化)
_DEFAULT_EXPANDED_H = 180  # 復元時に前回高が無い場合の既定 (px)


class CollapsibleDockTitleBar(QWidget):
    """chevron トグル+タイトル+フロート+閉じるを持つドックタイトルバー。"""

    collapsed_changed = Signal(bool)

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
        self._collapsed = False
        self._expanded_height = _DEFAULT_EXPANDED_H

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        self._toggle_button = QToolButton()
        self._toggle_button.setAutoRaise(True)
        self._toggle_button.setIcon(icons.icon("chevron_down"))
        self._toggle_button.setToolTip("折りたたむ / 展開")
        self._toggle_button.clicked.connect(
            lambda: self.set_collapsed(not self._collapsed)
        )
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

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        content = self._dock.widget()
        if collapsed:
            # 現在高を控えてから畳む (展開時の復元に使う)。
            h = self._dock.height()
            if h > self.sizeHint().height():
                self._expanded_height = h
            if content is not None:
                content.hide()
            self._dock.setMaximumHeight(self.sizeHint().height())
            self._toggle_button.setIcon(icons.icon("chevron_right"))
        else:
            self._dock.setMaximumHeight(_QWIDGETSIZE_MAX)
            if content is not None:
                content.show()
            self._toggle_button.setIcon(icons.icon("chevron_down"))
            # クランプ解除だけでは自動再拡大しないことがあるため高さを戻す。
            self._main_window.resizeDocks(
                [self._dock], [self._expanded_height], Qt.Orientation.Vertical
            )
        self.collapsed_changed.emit(collapsed)
