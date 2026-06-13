from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QStyleOptionGraphicsItem, QWidget


class RegionDividerItem(pg.GraphicsObject):
    """A horizontal divider that can be dragged to resize adjacent axes."""

    def __init__(self, vm: any, axis_index: int) -> None:
        super().__init__()
        self.vm = vm
        self.axis_index = axis_index
        self._hovering = False
        self.setAcceptHoverEvents(True)
        # Give it some thickness for easier dragging
        self.thickness = 6
        self.line_color = QColor(100, 100, 100, 150)
        self.hover_color = QColor(255, 165, 0, 200)  # Orange hover

    def boundingRect(self) -> QRectF:
        if self.parentItem() is None:
            return QRectF(0, 0, 0, 0)
        parent_rect = self.parentItem().boundingRect()
        return QRectF(0, -self.thickness / 2, parent_rect.width(), self.thickness)

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
        painter.drawRect(rect.left(), -0.5, rect.width(), 1.0)

    def hoverEnterEvent(self, event) -> None:
        self._hovering = True
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hovering = False
        self.unsetCursor()
        self.update()

    def mouseDragEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return

        if ev.isStart():
            ev.accept()
        elif ev.isFinish():
            ev.accept()
        else:
            # During drag
            delta = ev.pos() - ev.lastPos()
            
            # We need the widget height to calculate the ratio.
            # GraphicsObject can find its ViewBox or GraphicsScene.
            view = self.getViewWidget()
            if view is not None:
                height = view.height()
                if height > 0:
                    delta_ratio = delta.y() / height
                    self.vm.resize_axis(self.axis_index, delta_ratio)
            ev.accept()
