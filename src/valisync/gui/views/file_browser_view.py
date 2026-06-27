"""FileBrowserView — master file list view using QListView.

Binds to FileBrowserVM and FileListModel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint
from PySide6.QtGui import QContextMenuEvent
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list_view)

        # Connect selection changes to VM
        self.list_view.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )

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

    def _select_row_at(self, global_pos: QPoint) -> int | None:
        """Resolve the list row under *global_pos*, select it, and return it.

        Returns None when the position is not over a valid row (e.g. the empty
        area below the list), so the caller shows no menu. Extracted from
        contextMenuEvent so this resolution is unit-testable without the modal
        ``QMenu.exec()``.
        """
        pos = self.list_view.viewport().mapFromGlobal(global_pos)
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            return None
        self.list_view.setCurrentIndex(index)  # right-click selects the row
        return index.row()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Right-click a row: select it, then offer 'Remove File' (R7.1)."""
        row = self._select_row_at(event.globalPos())
        if row is None:
            return
        self.build_context_menu(row).exec(event.globalPos())
