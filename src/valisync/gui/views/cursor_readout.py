"""CursorReadout — プロット上にオーバーレイするカーソル読み取り面 (R15.2)。

既存凡例を置き換え、色↔信号名の識別とカーソル補間値を1つの表に集約する。
カーソル表示に連動して可視/不可視を切り替える (呼び出し側が setVisible)。
Plan B (R16/R17) で Δy・統計列を追加するため、列生成は set_readings 内に閉じる。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from valisync.gui.viewmodels.graph_panel_vm import CursorReading

_OUT_OF_RANGE = "範囲外"


def _format_value(reading: CursorReading) -> str:
    if not reading.in_range or reading.value is None:
        return _OUT_OF_RANGE
    return f"{reading.value:.4g}"


class CursorReadout(QWidget):
    """Floating per-panel readout table.  Rows: [colour swatch | name | value]."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CursorReadout")
        # Semi-opaque dark chip so it reads over the waveforms.
        self.setStyleSheet(
            "#CursorReadout { background: rgba(17,17,27,230);"
            " border: 1px solid #45475a; border-radius: 5px; }"
            " QLabel { color: #cdd6f4; }"
        )
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(6, 5, 6, 5)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(2)
        self._rows: list[tuple[str, str]] = []
        self._drag_offset: QPoint | None = (
            None  # for click-drag repositioning within parent
        )

    def set_readings(self, readings: list[CursorReading]) -> None:
        """Rebuild the table from *readings* (one row per signal)."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._rows = []
        for r, reading in enumerate(readings):
            swatch = QLabel()
            pix = QPixmap(10, 10)
            pix.fill(QColor(reading.color))
            swatch.setPixmap(pix)
            name = QLabel(reading.name)
            value_text = _format_value(reading)
            value = QLabel(value_text)
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._grid.addWidget(swatch, r, 0)
            self._grid.addWidget(name, r, 1)
            self._grid.addWidget(value, r, 2)
            self._rows.append((reading.name, value_text))
        self.adjustSize()

    def row_texts(self) -> list[tuple[str, str]]:
        """Test introspection: [(name, value_text), ...] in row order."""
        return list(self._rows)

    # ── Drag to reposition within the parent plot (R: フロート表は移動可) ──
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(self.pos() + event.position().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)
