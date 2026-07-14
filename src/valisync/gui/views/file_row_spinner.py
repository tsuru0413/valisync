"""ReleasingSpinnerDelegate -- paints a rotating arc on File Browser rows whose
data is still draining (FU-16). No text ("解放中" は出さない): the spinner alone
signals release-in-progress; the row is dimmed and non-interactive.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QWidget

from valisync.gui.adapters.qt_signal_models import FileListModel
from valisync.gui.theme import tokens


class ReleasingSpinnerDelegate(QStyledItemDelegate):
    """Draws the default item, then a spinner arc for releasing rows at *angle*."""

    def __init__(
        self, angle_provider: Callable[[], int], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._angle = angle_provider  # callable -> int degrees

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        if not index.data(FileListModel.ReleasingRole):
            return
        d = max(0, min(option.rect.height() - 8, 16))  # never negative (tiny rows)
        x = option.rect.left() + 6
        y = option.rect.center().y() - d / 2
        rect = QRectF(x, y, d, d)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(*tokens.active().colors.busy_spinner.rgba), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        start = int(self._angle()) * 16  # Qt angles are in 1/16 deg
        painter.drawArc(rect, -start, 300 * 16)  # 300 deg arc = spinner gap
        painter.restore()
