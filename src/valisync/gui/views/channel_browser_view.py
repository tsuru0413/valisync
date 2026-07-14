"""Channel_Browser view — refactored for master-detail (Task 2.3).

A search box atop a hierarchical QTreeView. Array bases (LD-14 Name[i]/.field)
collapse under a parent node; scalars stay top-level leaves (FU-22 B). User
gestures are forwarded to the VM. Displays signals for the currently active
file in AppViewModel.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QItemSelection,
    QMimeData,
    QModelIndex,
    QPoint,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QStackedWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.adapters.qt_signal_models import encode_signal_keys
from valisync.gui.adapters.signal_tree_model import SignalTreeModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM

_FILTER_DEBOUNCE_MS = 200  # prod 264k のフィルタ scan ~170ms を入力停止後 1 回に集約

# Empty-state placeholder text (FB-05/08/09); no_match takes a format arg.
_EMPTY_MESSAGES = {
    "none_selected": "File Browser でファイルを選択すると\n信号一覧を表示します",
    "no_match": "「{query}」に一致する信号はありません",
    "no_channels": "このファイルに信号がありません\n（Diagnostics に詳細）",  # noqa: RUF001
}


class ChannelBrowserView(QWidget):
    """Search box + hierarchical tree view bound to a :class:`ChannelBrowserVM`."""

    # Emitted with the selected signal keys; the integration connects this to
    # the active Graph_Panel's add_signal (R14.1).
    add_to_panel_requested = Signal(list)
    preview_requested = Signal(str)  # FU-13: double-click a leaf -> open preview

    def __init__(self, vm: ChannelBrowserVM, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self.model = SignalTreeModel(vm)

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Filter signals…")
        self.search_box.setClearButtonEnabled(True)

        # FU-22 B increment 2: debounce the filter scan (~170ms at prod 264k)
        # so rapid typing does not lag; the scan runs once after typing pauses.
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(_FILTER_DEBOUNCE_MS)
        self._filter_timer.timeout.connect(self._apply_filter)

        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        # QHeaderView's un-set sort indicator defaults to (column=0, Descending);
        # setSortingEnabled(True) fires that stale default as a real sort *before*
        # our own passthrough call below runs, silently reordering the tree on
        # every fresh view. Clear it first so there is nothing to fire.
        self.tree.header().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.tree.setSortingEnabled(True)
        # Default: session order until a header is clicked (PC-20 DP2). -1 = passthrough.
        self.tree.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.tree.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.tree.setDragEnabled(True)
        self.tree.setUniformRowHeights(True)

        # CustomContextMenu so a real right-click on the child tree emits
        # customContextMenuRequested. Overriding contextMenuEvent on this
        # container does not fire reliably from the child item view, so the
        # menu would not appear in the real GUI (mirrors FileBrowser PR#11).
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.header_label = QLabel(self)
        self.placeholder_label = QLabel(self)
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setWordWrap(True)
        # QLabel は既定で plain text — クエリ文字列を HTML 解釈させない (spec §6)
        self.placeholder_label.setTextFormat(Qt.TextFormat.PlainText)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.tree)  # index 0
        self._stack.addWidget(self.placeholder_label)  # index 1

        controls = QHBoxLayout()
        controls.addWidget(self.search_box, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header_label)
        layout.addLayout(controls)
        layout.addWidget(self._stack)

        # ── Wiring ───────────────────────────────────────────────────────────
        # set_filter() synchronously notifies "filter" -> _on_vm_change() ->
        # _refresh_state(), so a second direct textChanged->_refresh_state
        # connection would double-call it on every keystroke; the VM notify
        # path alone is sufficient (see _on_vm_change below). textChanged only
        # restarts the debounce timer; _apply_filter (below) calls set_filter.
        self.search_box.textChanged.connect(lambda _text: self._filter_timer.start())
        self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        # FU-13: double-click (not Enter) opens the preview window. doubleClicked
        # fires only on double-click, so Enter never triggers it.
        self.tree.doubleClicked.connect(self._emit_preview)

        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        unsubscribe = self._vm.subscribe(self._on_vm_change)
        self.destroyed.connect(lambda *_: unsubscribe())

        self._refresh_state()

    # ─── VM reactions ──────────────────────────────────────────────────────────

    def is_showing_placeholder(self) -> bool:
        """True when the placeholder (not the tree) is visible (test-facing)."""
        return self._stack.currentWidget() is self.placeholder_label

    def _refresh_state(self) -> None:
        """Sync header + tree/placeholder switch with the VM (FB-05/08/09)."""
        self.header_label.setText(self._vm.header_text())
        state = self._vm.empty_state()
        if state == "has_rows":
            self._stack.setCurrentWidget(self.tree)
            return
        message = _EMPTY_MESSAGES[state]
        if state == "no_match":
            message = message.format(query=self._vm.filter_query())
        self.placeholder_label.setText(message)
        self._stack.setCurrentWidget(self.placeholder_label)

    def _apply_filter(self) -> None:
        """Apply the (debounced) search text to the VM filter."""
        self._vm.set_filter(self.search_box.text())

    def _on_vm_change(self, change: str) -> None:
        """Handle notifications from ChannelBrowserVM."""
        if change in ("signals", "filter"):
            self._refresh_state()

    def _on_selection_changed(
        self, _selected: QItemSelection, _deselected: QItemSelection
    ) -> None:
        keys = self.selected_signal_keys()
        self._vm.set_selection(keys)

    # ─── Queries ───────────────────────────────────────────────────────────────

    def selected_signal_keys(self) -> list[str]:
        """Return the namespaced keys of the selected leaf rows.

        The tree is bound directly to SignalTreeModel (no proxy -- a proxy would
        eagerly materialize all array children on reset, defeating the lazy tree,
        see FU-22 B). So selection indexes are model indexes; resolve each key
        directly. Parent (array) nodes return None and are skipped (parent-as-signal
        lands in increment 4)."""
        keys: list[str] = []
        for index in self.tree.selectionModel().selectedRows(0):
            key = self.model.signal_key_at(index)
            if key is not None:
                keys.append(key)
        return keys

    def mime_data_for_selection(self) -> QMimeData:
        """Build the drag payload for the current selection (signal keys)."""
        return encode_signal_keys(self.selected_signal_keys())

    # ─── Commands ────────────────────────────────────────────────────────────--

    def _emit_add_selected(self) -> None:
        """Emit add_to_panel_requested for the current selection (right-click menu / D&D)."""
        keys = self.selected_signal_keys()
        if keys:
            self.add_to_panel_requested.emit(keys)

    def _emit_preview(self, index: QModelIndex) -> None:
        """Emit preview_requested for a leaf; parents (key is None) are ignored."""
        key = self.model.signal_key_at(index)
        if key is not None:
            self.preview_requested.emit(key)

    # ─── Context menu (R14.1) ──────────────────────────────────────────────────

    def build_context_menu(self) -> QMenu:
        """Build the signal context menu, greyed out per current selection."""
        menu = QMenu(self)
        add = menu.addAction("Add to Active Panel")
        add.setEnabled(bool(self.selected_signal_keys()))
        # Route through _emit_add_selected so the empty-selection guard is shared
        # with D&D (action is already disabled when empty; add is menu/D&D only).
        add.triggered.connect(lambda *_: self._emit_add_selected())
        return menu

    def _show_context_menu(self, pos: QPoint) -> None:
        """Show the signal menu on a real right-click (CustomContextMenu).

        Driven by ``QTreeView.customContextMenuRequested`` so the menu appears on
        the real OS path (overriding contextMenuEvent on this container does not
        fire from the child item view). The menu operates on the current
        multi-selection (R14.1 / H4), so this deliberately does NOT change the
        selection — right-clicking with several rows selected keeps them all for
        a bulk "Add to Active Panel".
        """
        global_pos = self.tree.viewport().mapToGlobal(pos)
        self.build_context_menu().exec(global_pos)
