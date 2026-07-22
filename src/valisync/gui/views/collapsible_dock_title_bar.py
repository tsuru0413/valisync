"""ドック共通の展開時タイトルバー (edge-aware-dock-collapse で辺対応レールへ移行)。

QDockWidget に最小化フラグは無いため setTitleBarWidget で差す。既定タイトルバー
(フロート/閉じる)を置換するので自前で持つ。chevron は「畳み要求」を出すだけで、
実際の畳み (dock.hide()+辺レールにタブ) は MainWindow が担う。フロート中は送り先の
辺が無いので chevron を無効化する。
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
from valisync.gui.views.dock_collapse_rail import collapse_chevron_for_area


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

        # シェブロンはドックの辺 (畳む方向) から解決する (B4/UX-44)。構築順は
        # addDockWidget → タイトルバー構築で、この時点で area は既に有効値
        # (main_window.py 実査済み)。
        initial_area = main_window.dockWidgetArea(dock)
        self._chevron_name = collapse_chevron_for_area(initial_area) or "chevron_right"

        self._toggle_button = QToolButton()
        self._toggle_button.setAutoRaise(True)
        self._toggle_button.setIcon(icons.icon(self._chevron_name))
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
        # UX-38: 当たり判定の高さを 24px へ (text ボタンは既定 ~19px と縦不足)。
        # fixedSize は使わない — 幅を縮めるとヒット幅がむしろ縮む。
        self._float_button.setMinimumHeight(24)
        self._float_button.clicked.connect(
            lambda: self._dock.setFloating(not self._dock.isFloating())
        )
        lay.addWidget(self._float_button)

        self._close_button = QToolButton()
        self._close_button.setAutoRaise(True)
        self._close_button.setText("✕")
        self._close_button.setToolTip("閉じる")
        self._close_button.setMinimumHeight(24)  # UX-38: 当たり判定の高さ 24px。
        self._close_button.clicked.connect(self._dock.close)
        lay.addWidget(self._close_button)

        # フロート中は畳み先の辺が無いので無効化 (再ドッキングで有効化)。
        dock.topLevelChanged.connect(self._on_floating_changed)
        # 実行時のドック移動 (D&D・restoreState) に追随 (B4/UX-44)。実測: フロート
        # 開始時は NoDockWidgetArea で発火するため写像は None を返し早期 return
        # する — 直前のシェブロンを維持する。
        dock.dockLocationChanged.connect(self._on_dock_area_changed)

    def _on_floating_changed(self, floating: bool) -> None:
        self._toggle_button.setEnabled(not floating)

    def _on_dock_area_changed(self, area: Qt.DockWidgetArea) -> None:
        name = collapse_chevron_for_area(area)
        if name is None or name == self._chevron_name:
            return
        self._chevron_name = name
        self._toggle_button.setIcon(icons.icon(name))

    def chevron_icon_name(self) -> str:
        """現在解決済みのシェブロンの意味名 (introspection・テスト用)。"""
        return self._chevron_name
