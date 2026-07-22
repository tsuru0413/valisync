"""SignalPreviewWindow (FU-13): non-modal, single-instance window with a
Preview (read-only waveform) tab and a Signal Properties tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from valisync.gui import strings as S
from valisync.gui.theme import tokens

if TYPE_CHECKING:
    from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM


class SignalPreviewWindow(QWidget):
    def __init__(self, vm: SignalPreviewVM, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle("信号プレビュー")
        self.resize(560, 400)

        self.tabs = QTabWidget(self)

        # --- Preview tab: plot OR "cannot preview" label (QStackedWidget) --------
        self.preview_plot = pg.PlotWidget()
        self.preview_plot.setMouseEnabled(False, False)
        self.preview_plot.setMenuEnabled(False)
        self.preview_plot.hideButtons()
        self._no_preview = QLabel(S.PREVIEW_UNAVAILABLE)
        self._no_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_stack = QStackedWidget()
        self._preview_stack.addWidget(self.preview_plot)  # index 0
        self._preview_stack.addWidget(self._no_preview)  # index 1
        self.tabs.addTab(self._preview_stack, "プレビュー")

        # --- Properties tab ------------------------------------------------------
        self._props_host = QWidget()
        self._props_form = QFormLayout(self._props_host)
        self.tabs.addTab(self._props_host, "信号プロパティ")

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)

    def property_row_count(self) -> int:
        return self._props_form.rowCount()

    def show_signal(self, key: str) -> None:
        self._vm.set_signal(key)
        self._render()
        self.setWindowTitle(S.PREVIEW_TITLE_TMPL.format(key=key))
        self.show()
        self.raise_()
        self.activateWindow()

    def _render(self) -> None:
        # Preview tab.
        self.preview_plot.clear()
        data = self._vm.plot_data()
        if data is not None:
            x, y = data
            self.preview_plot.plot(
                x, y, pen=pg.mkPen(tokens.active().colors.preview_curve.hex, width=1)
            )
            self._preview_stack.setCurrentIndex(0)
        else:
            self._preview_stack.setCurrentIndex(1)
        # Properties tab: rebuild the form.
        while self._props_form.rowCount() > 0:
            self._props_form.removeRow(0)
        for label, value in self._vm.properties():
            self._props_form.addRow(QLabel(label), QLabel(value))
