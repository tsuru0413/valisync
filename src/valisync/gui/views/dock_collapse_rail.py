"""辺対応の折りたたみレール (edge-aware-dock-collapse)。

畳んだドックは hide され、その辺のレールに content サイズのタブが出る。左/右=縦
レール(縦書きタブ・幅を詰める)、下=横帯(横チップ・高さを詰める)。上は対象外。
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt


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
