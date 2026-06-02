"""Channel_Browser view — thin Qt adapter over ChannelBrowserVM (Task 7.2).

A search box atop a QTreeView.  User gestures are forwarded to the VM
(filter / selection / visibility); the tree itself is rendered by
ChannelTreeModel.  No signal state lives here — the VM owns it all, so the
widget stays a dumb projection that headless VM tests already cover.
"""

from __future__ import annotations

from PySide6.QtCore import QItemSelection, QMimeData
from PySide6.QtWidgets import (
    QLineEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.adapters.qt_signal_models import (
    ChannelTreeModel,
    encode_signal_keys,
)
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM


class ChannelBrowserView(QWidget):
    """Search box + tree view bound to a :class:`ChannelBrowserVM`."""

    def __init__(self, vm: ChannelBrowserVM, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self.tree_model = ChannelTreeModel(vm)

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Filter signals…")
        self.search_box.setClearButtonEnabled(True)

        self.tree = QTreeView(self)
        self.tree.setModel(self.tree_model)
        self.tree.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.tree.setDragEnabled(True)
        self.tree.setUniformRowHeights(True)
        self.tree.expandAll()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.search_box)
        layout.addWidget(self.tree)

        # ── Wiring ───────────────────────────────────────────────────────────
        self.search_box.textChanged.connect(self._vm.set_filter)
        self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)
        # Re-render whenever the VM's state changes (filter typed, signals
        # loaded externally, etc.).  beginResetModel clears the selection, so
        # we re-expand to keep the tree usable after a refresh.
        unsubscribe = self._vm.subscribe(self._on_vm_change)
        self._unsubscribe = unsubscribe
        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        self.destroyed.connect(lambda *_: unsubscribe())

    # ─── VM reactions ──────────────────────────────────────────────────────────

    def _on_vm_change(self, _change: str) -> None:
        self.tree_model.refresh()
        self.tree.expandAll()

    def _on_selection_changed(
        self, _selected: QItemSelection, _deselected: QItemSelection
    ) -> None:
        self._vm.set_selection(self.selected_signal_keys())

    # ─── Queries ───────────────────────────────────────────────────────────────

    def selected_signal_keys(self) -> list[str]:
        """Return the namespaced keys of the currently-selected signal leaves.

        Group-header rows contribute nothing (``signal_key_at`` returns None).
        """
        keys: list[str] = []
        for index in self.tree.selectionModel().selectedRows(0):
            key = self.tree_model.signal_key_at(index)
            if key is not None:
                keys.append(key)
        return keys

    def mime_data_for_selection(self) -> QMimeData:
        """Build the drag payload for the current selection (signal keys)."""
        return encode_signal_keys(self.selected_signal_keys())

    # ─── Commands ────────────────────────────────────────────────────────────--

    def toggle_visibility_for_selection(self) -> None:
        """Flip visibility on every selected signal (used by toolbar/context)."""
        for key in self.selected_signal_keys():
            self._vm.toggle_visibility(key)
