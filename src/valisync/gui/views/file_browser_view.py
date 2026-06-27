"""FileBrowserView — master file list view using QListView.

Binds to FileBrowserVM and FileListModel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QListView, QMenu, QVBoxLayout, QWidget

from valisync.gui.adapters.qt_signal_models import FileListModel

if TYPE_CHECKING:
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM


class FileBrowserView(QWidget):
    """View component for the FileBrowser list.

    Parameters
    ----------
    vm:
        The FileBrowser ViewModel providing the file list and handling selection.
    """

    def __init__(self, vm: FileBrowserVM) -> None:
        super().__init__()
        self._vm = vm
        self.model = FileListModel(vm, self)

        # UI Setup
        self.list_view = QListView()
        self.list_view.setModel(self.model)
        # CustomContextMenu so a real right-click on the list emits
        # customContextMenuRequested (handled by _show_context_menu). Overriding
        # contextMenuEvent on this container does not fire reliably from the child
        # item view, so the menu would not appear in the real GUI.
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list_view)

        # Connect selection changes to VM
        self.list_view.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )
        self.list_view.customContextMenuRequested.connect(self._show_context_menu)

    def _on_selection_changed(self) -> None:
        """Translate view selection to ViewModel selection."""
        indexes = self.list_view.selectionModel().selectedIndexes()
        if indexes:
            self._vm.select_file(indexes[0].row())
        else:
            self._vm.select_file(-1)

    def build_context_menu(self, row: int) -> QMenu:
        """Single-action menu ('Remove File') wired to unload list *row*."""
        menu = QMenu(self)
        menu.addAction("Remove File").triggered.connect(lambda *_: self._vm.unload(row))
        return menu

    def _show_context_menu(self, pos: QPoint) -> None:
        """Show the 'Remove File' menu for the row at *pos* (viewport coords).

        Wired to ``QListView.customContextMenuRequested`` — the signal Qt emits on
        a real right-click when the list uses CustomContextMenu policy. Driving the
        menu from this signal (rather than overriding contextMenuEvent on the
        container) is what makes it appear in the real GUI: it does not depend on
        the right-click event propagating up from the child item view (R7.1).
        """
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            return
        self.list_view.setCurrentIndex(index)  # right-click selects the row
        global_pos = self.list_view.viewport().mapToGlobal(pos)
        self.build_context_menu(index.row()).exec(global_pos)
