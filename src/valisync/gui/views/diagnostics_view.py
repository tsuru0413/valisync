"""DiagnosticsView — dockable list of load diagnostics (FB-02 surface).

A QDockWidget with a table (level / source / message / signal) plus a filter
(All/Errors/Warnings) and Clear. Subscribes to DiagnosticsViewModel and rebuilds
its rows on the "diagnostics" change tag. Double-clicking a row emits
``entry_activated`` with the signal name (or source) so MainWindow can jump to it.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel

_LEVEL_ICON = {"error": "⛔", "warning": "⚠"}
_HEADERS = ("Lv", "ソース", "メッセージ", "対象")


class DiagnosticsView(QDockWidget):
    """Dockable diagnostics list bound to a DiagnosticsViewModel."""

    entry_activated = Signal(str)

    def __init__(self, vm: DiagnosticsViewModel) -> None:
        super().__init__("Diagnostics")
        self.setObjectName("diagnostics_dock")  # required for saveState/restoreState
        self._vm = vm
        self._filter: str | None = None

        container = QWidget(self)
        outer = QVBoxLayout(container)

        bar = QHBoxLayout()
        self._btn_all = QPushButton("All")
        self._btn_err = QPushButton("Errors")
        self._btn_warn = QPushButton("Warnings")
        self._btn_clear = QPushButton("Clear")
        self._btn_all.clicked.connect(lambda: self.set_filter(None))
        self._btn_err.clicked.connect(lambda: self.set_filter("error"))
        self._btn_warn.clicked.connect(lambda: self.set_filter("warning"))
        self._btn_clear.clicked.connect(self.clear_diagnostics)
        for b in (self._btn_all, self._btn_err, self._btn_warn, self._btn_clear):
            bar.addWidget(b)
        bar.addStretch(1)
        outer.addLayout(bar)

        self._table = QTableWidget(0, len(_HEADERS), container)
        self._table.setHorizontalHeaderLabels(list(_HEADERS))
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        outer.addWidget(self._table)

        self.setWidget(container)
        self._unsubscribe = self._vm.subscribe(self._on_vm_change)
        self._rebuild()

    def set_filter(self, level: str | None) -> None:
        self._filter = level
        self._rebuild()

    def clear_diagnostics(self) -> None:
        self._vm.clear()  # triggers "diagnostics" → _rebuild

    def row_count(self) -> int:
        """Number of rows currently displayed (test-facing)."""
        return self._table.rowCount()

    def _on_vm_change(self, change: str) -> None:
        if change == "diagnostics":
            self._rebuild()

    def _rebuild(self) -> None:
        entries = self._vm.entries(self._filter)
        self._table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            cells = (
                _LEVEL_ICON.get(e.level, "?"),
                e.source,
                e.message,
                e.signal_name or "—",
            )
            for c, text in enumerate(cells):
                self._table.setItem(r, c, QTableWidgetItem(text))

    def _on_double_click(self, row: int, _col: int) -> None:
        entries = self._vm.entries(self._filter)
        if 0 <= row < len(entries):
            e = entries[row]
            self.entry_activated.emit(e.signal_name or e.source)
