"""FileBrowserView — master file list view using QListView.

Binds to FileBrowserVM and FileListModel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QListView, QVBoxLayout, QWidget

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
        self.list_view.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self) -> None:
        """Translate view selection to ViewModel selection."""
        indexes = self.list_view.selectionModel().selectedIndexes()
        if indexes:
            self._vm.select_file(indexes[0].row())
        else:
            self._vm.select_file(-1)
