"""DiagnosticsView — dockable list of load diagnostics (FB-02 surface).

A QDockWidget with a table (level / order / source / message / signal) plus a
filter (All/Errors/Warnings), Clear, and a counts chip — per design spec
§4.4. Subscribes to DiagnosticsViewModel and rebuilds its rows on the
"diagnostics" change tag. Double-clicking a row emits ``entry_activated`` with
the entry's source (file basename) so MainWindow can activate it; the target
is always the file — signal_name is display-only (see ``_on_double_click``).
When the filtered
entry list is empty, a placeholder replaces the table (spec §7: "ドックは
診断ゼロでも存在。空時はプレースホルダ").
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel

_LEVEL_ICON = {"error": "⛔", "warning": "⚠", "info": "ℹ"}  # noqa: RUF001
# spec §4.4 column order: レベルアイコン / 時刻 / ソース / メッセージ / 対象.
# "時刻" is satisfied by DiagnosticEntry.seq (spec §4.3: wall-clock time OR
# receipt-order sequence number is acceptable) — header kept terse ("#").
_HEADERS = ("レベル", "#", "ソース", "メッセージ", "対象")
_PLACEHOLDER_TEXT = "診断はありません"


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
        self._counts_label = QLabel()
        bar.addWidget(self._counts_label)
        outer.addLayout(bar)

        self._table = QTableWidget(0, len(_HEADERS), container)
        self._table.setHorizontalHeaderLabels(list(_HEADERS))
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.cellDoubleClicked.connect(self._on_double_click)

        self._placeholder = QLabel(_PLACEHOLDER_TEXT)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # QStackedWidget (not overlapping widgets) so the placeholder cleanly
        # replaces the table rather than fighting it for layout space.
        self._stack = QStackedWidget(container)
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._placeholder)
        outer.addWidget(self._stack)

        self.setWidget(container)
        unsubscribe = self._vm.subscribe(self._on_vm_change)
        self._unsubscribe = unsubscribe
        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        self.destroyed.connect(lambda *_: unsubscribe())
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
                str(e.seq),
                e.source,
                e.message,
                e.signal_name or "—",
            )
            for c, text in enumerate(cells):
                self._table.setItem(r, c, QTableWidgetItem(text))

        # placeholder tracks the *filtered* view, not just the VM's raw
        # entries — an empty filter result (e.g. "Errors" with none) reads
        # the same as a truly empty dock (spec §7).
        self._stack.setCurrentWidget(self._table if entries else self._placeholder)

        errors, warnings = self._vm.counts()
        # plain ASCII slash keeps ruff's ambiguous-unicode check (RUF001/003)
        # clean; the fullwidth variant reads identically here.
        self._counts_label.setText(f"⛔ {errors} / ⚠ {warnings}")

    def _on_double_click(self, row: int, _col: int) -> None:
        entries = self._vm.entries(self._filter)
        if 0 <= row < len(entries):
            e = entries[row]
            # Activation target is the FILE (spec §4.4's best-effort jump), not
            # the signal: signal_name is a raw channel name for display only
            # ("対象" column) and matches neither source_name(key) nor a group
            # signal's namespaced "key::name" in
            # MainWindow._on_diagnostic_activated — emitting it verbatim made
            # skipped/duplicate/generic channel names silently unmatchable.
            # source (the file basename) always resolves via the first loop.
            self.entry_activated.emit(e.source)
