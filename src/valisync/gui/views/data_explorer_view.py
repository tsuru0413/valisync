"""Data_Explorer view — standalone filesystem browser (Task 7.3).

A separate QMainWindow opened from the main toolbar.  It registers
data-source folders (persisted as JSON via ``persistence.data_sources``) and
forwards an activated file to ``AppViewModel.request_load``.

Thin adapter: all application state lives in AppViewModel; this widget only
wires the filesystem tree and the source list to it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFileSystemModel,
    QListWidget,
    QMainWindow,
    QMenu,
    QSplitter,
    QToolBar,
    QTreeView,
)

from valisync.gui.persistence import data_sources
from valisync.gui.viewmodels.app_viewmodel import AppViewModel


class DataExplorerView(QMainWindow):
    """Filesystem explorer that registers sources and triggers loads.

    Parameters
    ----------
    app_vm:
        Application ViewModel; receives ``request_load`` and source updates.
    sources_file:
        Optional JSON file backing the registered data-source list.  When
        given, sources are restored on construction and persisted on change.
        When *None* the source list lives only in memory (handy for tests
        that don't care about persistence).
    """

    def __init__(
        self,
        app_vm: AppViewModel,
        sources_file: Path | None = None,
        parent: QMainWindow | None = None,
        *,
        load_handler: Callable[[Path | str], None] | None = None,
        dir_chooser: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_vm = app_vm
        self._sources_file = Path(sources_file) if sources_file is not None else None
        # The integration injects an async loader; standalone use loads directly.
        self._load_handler: Callable[[Path | str], None] = (
            load_handler or self.load_path
        )
        # Injectable so the modal QFileDialog can be bypassed in tests.
        self._dir_chooser: Callable[[], str] = dir_chooser or self._default_dir_chooser
        self.setWindowTitle("Data Explorer")

        # ── Filesystem tree ──────────────────────────────────────────────────
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setRootPath("")
        self.tree = QTreeView(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.setModel(self.fs_model)
        self.tree.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.tree.activated.connect(self._on_activated)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        # SH-10: 登録データソースの可視リスト (tree の左に並置)。
        self.source_list = QListWidget(self)
        self.source_list.setObjectName("data_source_list")
        self.source_list.currentRowChanged.connect(self._on_source_row_changed)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.source_list)
        splitter.addWidget(self.tree)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)  # replaces setCentralWidget(self.tree)
        self.setAcceptDrops(True)  # OS file-manager drops (R12.1)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar: QToolBar = self.addToolBar("Sources")
        self.action_add_source = toolbar.addAction("Add Source")
        self.action_add_source.triggered.connect(self._on_add_source_clicked)
        self.action_remove_source = toolbar.addAction("Remove Source")
        self.action_remove_source.triggered.connect(self._on_remove_source_clicked)

        # data_sources 変更でリストを再投影 (restore の add もこれで反映)。
        self._app_unsub = self._app_vm.subscribe(self._on_app_change)
        self.destroyed.connect(lambda *_: self._app_unsub())

        # ── Restore persisted sources ────────────────────────────────────────
        if self._sources_file is not None:
            for path in data_sources.load(self._sources_file):
                self._app_vm.add_data_source(path)
            self._show_last_source()

    # ─── Toolbar actions (R3.4) ─────────────────────────────────────────────────

    def _default_dir_chooser(self) -> str:
        return QFileDialog.getExistingDirectory(self, "Select Data Source Folder")

    def _on_add_source_clicked(self, *_: object) -> None:
        folder = self._dir_chooser()
        if folder:
            self.add_source(folder)

    def _on_remove_source_clicked(self, *_: object) -> None:
        """Remove the source selected in the list (SH-15: not the invisible tree root)."""
        item = self.source_list.currentItem()
        if item is None:
            self.statusBar().showMessage(
                "削除するデータソースをリストから選択してください", 4000
            )
            return
        self.remove_source(Path(item.text()))

    # ─── Source management ─────────────────────────────────────────────────────

    def sources(self) -> list[str]:
        """Return the registered data-source folder paths."""
        return list(cast("list[str]", self._app_vm.inspect()["data_sources"]))

    def add_source(self, path: Path | str) -> None:
        """Register *path* as a data source, root the tree at it, and persist."""
        self._app_vm.add_data_source(str(path))
        self._root_at(Path(path))
        self._persist()

    def remove_source(self, path: Path | str) -> None:
        """Unregister *path* and persist the updated source list."""
        self._app_vm.remove_data_source(str(path))
        self._persist()

    def _persist(self) -> None:
        if self._sources_file is not None:
            data_sources.save(self.sources(), self._sources_file)

    def _show_last_source(self) -> None:
        sources = self.sources()
        if sources:
            self._root_at(Path(sources[-1]))

    def _root_at(self, folder: Path) -> None:
        self.tree.setRootIndex(self.fs_model.index(str(folder)))

    def _on_app_change(self, change: str) -> None:
        if change == "data_sources":
            self._refresh_source_list()

    def _refresh_source_list(self) -> None:
        current = self.source_list.currentItem()
        keep = current.text() if current is not None else None
        self.source_list.blockSignals(True)  # rebuild without spurious root switches
        self.source_list.clear()
        for path in self.sources():
            self.source_list.addItem(path)
        if keep is not None:
            matches = self.source_list.findItems(keep, Qt.MatchFlag.MatchExactly)
            if matches:
                self.source_list.setCurrentItem(matches[0])
        self.source_list.blockSignals(False)

    def _on_source_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self.source_list.item(row)
        if item is not None:
            self._root_at(Path(item.text()))

    # ─── Load ──────────────────────────────────────────────────────────────────

    def load_path(self, path: Path | str) -> None:
        """Forward *path* to the application ViewModel for loading."""
        self._app_vm.request_load(Path(path))

    def _on_activated(self, index: QModelIndex) -> None:
        """Load files on activation; directories are navigated, not loaded."""
        if not index.isValid() or self.fs_model.isDir(index):
            return
        self._load_handler(self.fs_model.filePath(index))

    # ─── OS file drop (R12.1) ───────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        for url in mime.urls():
            local = url.toLocalFile()
            if local:
                self._load_handler(local)
        event.acceptProposedAction()

    # ─── Context menu (R14.2) ───────────────────────────────────────────────────

    def build_context_menu(self, path: Path | str) -> QMenu:
        """Build the file context menu, greyed out per file/source state."""
        path = Path(path)
        menu = QMenu(self)
        load = menu.addAction("Load File")
        load.setEnabled(path.is_file())
        load.triggered.connect(lambda *_: self._load_handler(path))
        remove = menu.addAction("Remove from Data Sources")
        remove.setEnabled(str(path) in self.sources())
        remove.triggered.connect(lambda *_: self.remove_source(path))
        return menu

    def _show_context_menu(self, pos: QPoint) -> None:
        """Show the file menu on a real right-click (CustomContextMenu).

        Driven by ``QTreeView.customContextMenuRequested`` so the menu fires on
        the real OS path (mirrors FileBrowser PR#11); overriding contextMenuEvent
        on this container does not fire reliably from the child item view.
        """
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        global_pos = self.tree.viewport().mapToGlobal(pos)
        self.build_context_menu(self.fs_model.filePath(index)).exec(global_pos)
