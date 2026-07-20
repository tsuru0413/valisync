"""辺対応の折りたたみレール (edge-aware-dock-collapse)。

畳んだドックは hide され、その辺のレールに content サイズのタブが出る。左/右=縦
レール(縦書きタブ・幅を詰める)、下=横帯(横チップ・高さを詰める)。上は対象外。
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QShowEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.theme import icons

_TAB_ICON_PX = 14


class RailKind(Enum):
    VERTICAL = "vertical"  # 左/右ドック — 縦レール・縦書きタブ
    HORIZONTAL = "horizontal"  # 下ドック — 横帯・横チップ


def rail_kind_for_area(area: Qt.DockWidgetArea) -> RailKind | None:
    """ドック領域からレール種別を引く。対応外 (上/なし) は None。"""
    if area in (
        Qt.DockWidgetArea.LeftDockWidgetArea,
        Qt.DockWidgetArea.RightDockWidgetArea,
    ):
        return RailKind.VERTICAL
    if area == Qt.DockWidgetArea.BottomDockWidgetArea:
        return RailKind.HORIZONTAL
    return None


# 展開シェブロンは「開く方向」を指す。
EXPAND_ICON: dict[Qt.DockWidgetArea, str] = {
    Qt.DockWidgetArea.LeftDockWidgetArea: "chevron_right",
    Qt.DockWidgetArea.RightDockWidgetArea: "chevron_left",
    Qt.DockWidgetArea.BottomDockWidgetArea: "chevron_up",
}


class _VerticalLabel(QLabel):
    """テキストを 90° 回転して描く縦書きラベル (縦タブ用)。"""

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.translate(self.width(), 0)
        painter.rotate(90)
        painter.drawText(
            QRect(0, 0, self.height(), self.width()),
            Qt.AlignmentFlag.AlignCenter,
            self.text(),
        )

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        return QSize(s.height(), s.width())  # 縦横入替

    def minimumSizeHint(self) -> QSize:
        s = super().minimumSizeHint()
        return QSize(s.height(), s.width())


class _CollapsedDockTab(QWidget):
    """畳んだドック 1 個ぶんのタブ (クリックで展開のみ)。"""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        kind: RailKind,
        expand_icon_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        chevron = QLabel()
        chevron.setPixmap(
            icons.icon(expand_icon_name).pixmap(_TAB_ICON_PX, _TAB_ICON_PX)
        )
        lay: QBoxLayout
        if kind is RailKind.VERTICAL:
            lay = QVBoxLayout(self)
            label: QLabel = _VerticalLabel(title)
        else:
            lay = QHBoxLayout(self)
            label = QLabel(title)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)
        lay.addWidget(chevron, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(label, 0, Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("CollapsedDockTab")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()


class DockCollapseRail(QWidget):
    """1 辺ぶんの畳みレール。content サイズのタブを位置順に積む。空なら隠れる。"""

    expand_requested = Signal(QDockWidget)

    def __init__(self, edge: Qt.DockWidgetArea, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._edge = edge
        self._kind = rail_kind_for_area(edge) or RailKind.VERTICAL
        self._expand_icon = EXPAND_ICON.get(edge, "chevron_left")
        self._tabs: dict[QDockWidget, _CollapsedDockTab] = {}
        self._orders: dict[QDockWidget, int] = {}
        self.setObjectName("DockCollapseRail")
        layout: QBoxLayout
        if self._kind is RailKind.VERTICAL:
            layout = QVBoxLayout(self)  # 上寄せ (末尾 stretch)
        else:
            layout = QHBoxLayout(self)  # 左寄せ (末尾 stretch)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        layout.addStretch(1)
        self._layout = layout
        self.setVisible(False)  # 空なので隠す

    def showEvent(self, event: QShowEvent) -> None:
        # 親 (MainWindow レイアウト等) からの無条件 show() でも空なら隠れたままにする。
        # Qt の show()/setVisible(True) は明示 hide 状態を無条件に解除するため、
        # 空判定は showEvent 側で都度再確認し直す必要がある。
        super().showEvent(event)
        if self.is_empty():
            self.hide()

    def is_empty(self) -> bool:
        return not self._tabs

    def add_tab(self, dock: QDockWidget, title: str, order: int) -> None:
        if dock in self._tabs:
            return
        tab = _CollapsedDockTab(title, self._kind, self._expand_icon)
        tab.clicked.connect(lambda: self.expand_requested.emit(dock))
        self._tabs[dock] = tab
        self._orders[dock] = order
        # order 昇順で挿入位置を決める (末尾 stretch の手前)。
        insert_at = 0
        for existing, existing_tab in self._tabs.items():
            if existing is dock:
                continue
            if self._orders[existing] < order:
                insert_at = max(insert_at, self._layout.indexOf(existing_tab) + 1)
        self._layout.insertWidget(insert_at, tab)
        self.setVisible(True)

    def remove_tab(self, dock: QDockWidget) -> None:
        tab = self._tabs.pop(dock, None)
        if tab is None:
            return
        self._orders.pop(dock, None)
        self._layout.removeWidget(tab)
        tab.deleteLater()
        if self.is_empty():
            self.setVisible(False)
