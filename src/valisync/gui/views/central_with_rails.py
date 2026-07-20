"""中央 widget をエッジレール枠で包むコンテナ (edge-aware-dock-collapse Task 1)。

畳んだドックのレールを「dock リングの外」でなく「中央 widget の内側の縁」に置く。
ドックを hide すると dock 領域が畳まれて中央がそのぶん拡張し、拡張した中央の縁に
レールが乗る = レールが窓の縁に一致する。setCorner (FU-10・dock 用) と無干渉。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget


class CentralWithRails(QWidget):
    """center を中央に据え、左/右=縦・下=横のレールスロットを縁に持つ。"""

    def __init__(self, center: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._center = center
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        # row0: [left(0,0)] [center(0,1 stretch)] [right(0,2)]
        # row1: [bottom(1, 0..2 span)]
        grid.addWidget(center, 0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        self._grid = grid
        self._rails: dict[Qt.DockWidgetArea, QWidget] = {}

    def set_rail(self, edge: Qt.DockWidgetArea, rail: QWidget) -> None:
        """辺に対応するグリッドセルへレール widget を据える (1回限り)。"""
        cell = {
            Qt.DockWidgetArea.LeftDockWidgetArea: (0, 0, 1, 1),
            Qt.DockWidgetArea.RightDockWidgetArea: (0, 2, 1, 1),
            Qt.DockWidgetArea.BottomDockWidgetArea: (1, 0, 1, 3),
        }[edge]
        self._grid.addWidget(rail, *cell)
        self._rails[edge] = rail
