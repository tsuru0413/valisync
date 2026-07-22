"""DiagnosticsView — dockable list of load diagnostics (FB-02 surface).

A QDockWidget with a table (level / order / source / message / signal) plus a
filter (All/Errors/Warnings), Clear, and a counts chip — per design spec
§4.4. Subscribes to DiagnosticsViewModel and rebuilds its rows on the
"diagnostics" change tag. Double-clicking a row emits ``entry_activated`` with
the entry's source (file basename) so MainWindow can activate it; the target
is always the file — signal_name is display-only (see ``_on_double_click``).
When the filtered entry list is empty, a placeholder replaces the table
(spec §7: "ドックは診断ゼロでも存在。空時はプレースホルダ"). The placeholder
text distinguishes a true-zero dock (``DIAG_EMPTY``) from a filtered-zero
result (``DIAG_EMPTY_FILTERED_TMPL`` — names the active filter and the
unfiltered total) so a filtered-to-nothing view is never mistaken for an
empty dock; this supersedes the prior same-display reading of
2026-07-02-gui-feedback-errors-design.md §7 (see
2026-07-22-diag-readout-consistency-design.md §2.2, B2/UX-06).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from valisync.gui import strings as S
from valisync.gui.viewmodels.diagnostics_vm import DiagnosticsViewModel

_LEVEL_ICON = {"error": "⛔", "warning": "⚠", "info": "ℹ"}  # noqa: RUF001
# spec §4.4 column order: レベルアイコン / 時刻 / ソース / メッセージ / 対象.
# "時刻" is satisfied by DiagnosticEntry.seq (spec §4.3: wall-clock time OR
# receipt-order sequence number is acceptable) — header kept terse ("#").
_HEADERS = ("レベル", "#", S.DIAG_COL_SOURCE, "メッセージ", "対象")
_MESSAGE_COLUMN = 3  # index of "メッセージ" within _HEADERS
# level -> display label used in DIAG_EMPTY_FILTERED_TMPL (B2).
_FILTER_LABEL = {"error": S.DIAG_FILTER_ERRORS, "warning": S.DIAG_FILTER_WARNINGS}


class DiagnosticsView(QDockWidget):
    """Dockable diagnostics list bound to a DiagnosticsViewModel."""

    entry_activated = Signal(str)

    def __init__(self, vm: DiagnosticsViewModel) -> None:
        super().__init__(S.DOCK_DIAGNOSTICS)
        self.setObjectName("diagnostics_dock")  # required for saveState/restoreState
        self._vm = vm
        self._filter: str | None = None
        # G-14/file_browser_view._confirm_fn 同型の属性 DI: tests replace this
        # with a stub to avoid QMessageBox.exec()'s modal loop (B5).
        self._confirm_fn: Callable[[int], bool] = self._default_confirm

        container = QWidget(self)
        outer = QVBoxLayout(container)

        bar = QHBoxLayout()
        self._btn_all = QPushButton(S.DIAG_FILTER_ALL)
        self._btn_err = QPushButton(S.DIAG_FILTER_ERRORS)
        self._btn_warn = QPushButton(S.DIAG_FILTER_WARNINGS)
        self._btn_clear = QPushButton(S.DIAG_CLEAR)
        # B2: the 3 filter buttons are checkable and mutually exclusive so the
        # active filter is always visible; Clear stays a plain (non-checkable)
        # action button. _filter is the single source of truth — set_filter()
        # below re-syncs the checked button whenever it changes (including
        # programmatic calls, which do not go through `clicked`).
        for b in (self._btn_all, self._btn_err, self._btn_warn):
            b.setCheckable(True)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        for b in (self._btn_all, self._btn_err, self._btn_warn):
            self._filter_group.addButton(b)
        self._btn_all.setChecked(True)
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

        # UX-07 応急: メッセージ列は残り幅いっぱいに広げ、他は内容幅で詰める。
        # 診断件数は有界(ResizeToContents の O(n) sizeHint 走査でも安全 — spec
        # §1.5-14、ChannelBrowser Unit 列とは前提が異なる)。
        table_header = self._table.horizontalHeader()
        for col in range(len(_HEADERS)):
            table_header.setSectionResizeMode(
                col,
                QHeaderView.ResizeMode.Stretch
                if col == _MESSAGE_COLUMN
                else QHeaderView.ResizeMode.ResizeToContents,
            )

        self._placeholder = QLabel(S.DIAG_EMPTY)
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
        # _filter is the truth source; keep the checkable buttons in sync even
        # when called programmatically (setChecked does not emit `clicked`, so
        # this never re-enters set_filter — B2 §2.2).
        btn = {None: self._btn_all, "error": self._btn_err, "warning": self._btn_warn}[
            level
        ]
        btn.setChecked(True)
        self._rebuild()

    def _default_confirm(self, n: int) -> bool:
        # Explicit QMessageBox (not QMessageBox.question) so the standard
        # Yes/No can be relabelled to match the body's verb — same pattern as
        # file_browser_view.FileBrowserView._default_confirm (G-14).
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(S.DIAG_CLEAR_CONFIRM_TITLE)
        box.setText(S.DIAG_CLEAR_CONFIRM_BODY_TMPL.format(n=n))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        yes_button = box.button(QMessageBox.StandardButton.Yes)
        no_button = box.button(QMessageBox.StandardButton.No)
        assert yes_button is not None
        assert no_button is not None
        yes_button.setText(S.DIAG_CLEAR_CONFIRM_YES)
        no_button.setText(S.DIAG_CLEAR_CONFIRM_NO)
        reply = box.exec()
        return reply == QMessageBox.StandardButton.Yes

    def clear_diagnostics(self) -> None:
        n = len(self._vm.entries(None))
        if n == 0:
            return
        if not self._confirm_fn(n):
            return
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
                str(e.seq + 1),  # E-2/UX-55: display is 1-based; index unchanged
                e.source,
                e.message,
                e.signal_name or "—",
            )
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == _MESSAGE_COLUMN:
                    # B3: Stretch can still clip a long message — hover shows
                    # the full text regardless of column width.
                    item.setToolTip(e.message)
                self._table.setItem(r, c, item)

        if entries:
            self._stack.setCurrentWidget(self._table)
        else:
            # placeholder tracks the *filtered* view, not just the VM's raw
            # entries — an empty filter result (e.g. "Errors" with none) now
            # shows a filter-contextual message distinct from a truly empty
            # dock, so it is never mistaken for "no diagnostics at all" (B2 —
            # supersedes the prior same-display reading of
            # 2026-07-02-gui-feedback-errors-design.md §7; see
            # 2026-07-22-diag-readout-consistency-design.md §2.2).
            if self._filter is None:
                self._placeholder.setText(S.DIAG_EMPTY)
            else:
                total = len(self._vm.entries(None))
                self._placeholder.setText(
                    S.DIAG_EMPTY_FILTERED_TMPL.format(
                        level=_FILTER_LABEL[self._filter], n=total
                    )
                )
            self._stack.setCurrentWidget(self._placeholder)

        errors, warnings, infos = self._vm.counts()
        # plain ASCII slash keeps ruff's ambiguous-unicode check (RUF001/003)
        # clean; the fullwidth variant reads identically here.
        self._counts_label.setText(f"⛔ {errors} / ⚠ {warnings} / ℹ {infos}")  # noqa: RUF001

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
