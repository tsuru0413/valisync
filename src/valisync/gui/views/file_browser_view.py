"""FileBrowserView — master file list view using QListView.

Binds to FileBrowserVM and FileListModel.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.adapters.qt_signal_models import FileListModel
from valisync.gui.views.file_row_spinner import ReleasingSpinnerDelegate

if TYPE_CHECKING:
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM


class FileBrowserView(QWidget):
    """View component for the FileBrowser list.

    Parameters
    ----------
    vm:
        The FileBrowser ViewModel providing the file list and handling selection.
    """

    open_requested = Signal()

    def __init__(
        self,
        vm: FileBrowserVM,
        *,
        confirm_fn: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__()
        self._vm = vm
        self._confirm_fn: Callable[[str], bool] = confirm_fn or self._default_confirm
        self.model = FileListModel(vm, self)

        # UI Setup
        self.list_view = QListView()
        self.list_view.setModel(self.model)
        # CustomContextMenu so a real right-click on the list emits
        # customContextMenuRequested (handled by _show_context_menu). Overriding
        # contextMenuEvent on this container does not fire reliably from the child
        # item view, so the menu would not appear in the real GUI.
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Spinner animation: advance an angle and repaint releasing rows only.
        self._spin_angle = 0
        self.list_view.setItemDelegate(
            ReleasingSpinnerDelegate(lambda: self._spin_angle, self)
        )
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(80)
        self._spin_timer.timeout.connect(self._advance_spinner)
        self._spin_timer.start()

        self.placeholder_label = QLabel(
            "ファイルが読み込まれていません\n\nウィンドウへファイルをドロップして追加",
            self,
        )
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setWordWrap(True)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.list_view)  # index 0
        self._stack.addWidget(self.placeholder_label)  # index 1

        # Header row: Open button (allows advancing from empty list - SH-07)
        self.open_button = QPushButton("開く...")
        self.open_button.setObjectName("file_browser_open")
        self.open_button.clicked.connect(self.open_requested)
        self.close_button = QPushButton("閉じる")
        self.close_button.setObjectName("file_browser_close")
        self.close_button.setToolTip("選択中のファイルを閉じる")
        self.close_button.clicked.connect(self._close_selected)
        header = QHBoxLayout()
        header.addWidget(self.open_button)
        header.addStretch(1)
        header.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self._stack)

        # Connect selection changes to VM
        self.list_view.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )
        self.list_view.customContextMenuRequested.connect(self._show_context_menu)

        # The VM outlives this widget; drop the subscription when the C++ object
        # is destroyed so a later notify never calls into a deleted view.
        unsubscribe = self._vm.subscribe(self._on_vm_change)
        self.destroyed.connect(lambda *_: unsubscribe())
        self._refresh_state()

    def _on_selection_changed(self) -> None:
        """Translate view selection to ViewModel selection."""
        indexes = self.list_view.selectionModel().selectedIndexes()
        if indexes:
            self._vm.select_file(indexes[0].row())
        else:
            self._vm.select_file(-1)

    def build_context_menu(self, row: int) -> QMenu:
        """Single-action menu ('Remove File') — confirms before unloading list *row*."""
        menu = QMenu(self)
        menu.addAction("Remove File").triggered.connect(
            lambda *_: self._confirm_and_unload(row)
        )
        return menu

    def _default_confirm(self, filename: str) -> bool:
        reply = QMessageBox.question(
            self,
            "ファイルを閉じる",
            f"{filename} を閉じますか? プロット中の信号も消えます。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _confirm_and_unload(self, row: int) -> None:
        files = self._vm.files
        if row < 0 or row >= len(files):
            return
        if self._confirm_fn(files[row]):
            self._vm.unload(row)

    def _close_selected(self) -> None:
        index = self.list_view.currentIndex()
        if index.isValid():
            self._confirm_and_unload(index.row())

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

    def is_showing_placeholder(self) -> bool:
        """True when the placeholder (not the list) is visible (test-facing)."""
        return self._stack.currentWidget() is self.placeholder_label

    def _on_vm_change(self, change: str) -> None:
        if change == "files":
            self._refresh_state()

    def _refresh_state(self) -> None:
        if self._vm.files:
            self._stack.setCurrentWidget(self.list_view)
        else:
            self._stack.setCurrentWidget(self.placeholder_label)

    def _advance_spinner(self) -> None:
        self._spin_angle = (self._spin_angle + 30) % 360
        # releasing 行がある時だけ再描画(無ければ無駄描画しない)。
        if any(self._vm.is_releasing(r) for r in range(len(self._vm.files))):
            self.list_view.viewport().update()
