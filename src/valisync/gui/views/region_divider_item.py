from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QHoverEvent, QPainter
from PySide6.QtWidgets import QStyleOptionGraphicsItem, QWidget

if TYPE_CHECKING:
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


class RegionDividerItem(pg.GraphicsWidget):
    """A horizontal divider that can be dragged to resize adjacent axes."""

    def __init__(
        self, vm: GraphPanelVM, axis_index: int, column: int | None = None
    ) -> None:
        super().__init__()
        self.vm = vm
        # When ``column`` is set, ``axis_index`` is the upper axis's vertical
        # RANK within that column; otherwise it is the legacy VM index.
        self.axis_index = axis_index
        self.column = column
        self._hovering = False
        self.setAcceptHoverEvents(True)
        # Give it some thickness for easier dragging
        self.thickness = 6
        self.line_color = QColor(100, 100, 100, 150)
        self.hover_color = QColor(255, 165, 0, 200)  # Orange hover

    def boundingRect(self) -> QRectF:
        return QRectF(0, -self.thickness / 2, self.width(), self.thickness)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        rect = self.boundingRect()
        color = self.hover_color if self._hovering else self.line_color
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        # Draw a thin 1px line in the middle of the hit area
        # Use QRectF for drawing to avoid type errors
        painter.drawRect(QRectF(rect.left(), -0.5, rect.width(), 1.0))

    def hoverEnterEvent(self, event: QHoverEvent) -> None:
        self._hovering = True
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.update()

    def hoverLeaveEvent(self, event: QHoverEvent) -> None:
        self._hovering = False
        self.unsetCursor()
        self.update()

    def mouseDragEvent(self, ev: Any) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return

        if ev.isStart() or ev.isFinish():
            ev.accept()
        else:
            # During drag
            delta: QPointF = ev.pos() - ev.lastPos()

            # We need the widget height to calculate the ratio.
            # GraphicsObject can find its ViewBox or GraphicsScene.
            view = self.getViewWidget()
            if view is not None:
                height = view.height()
                if height > 0:
                    delta_ratio = delta.y() / height
                    if self.column is None:
                        # Legacy call kept byte-identical (no column kwarg).
                        self.vm.resize_axis(self.axis_index, delta_ratio)
                    else:
                        self.vm.resize_axis(
                            self.axis_index, delta_ratio, column=self.column
                        )
            ev.accept()
