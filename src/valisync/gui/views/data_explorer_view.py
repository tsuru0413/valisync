"""Data_Explorer view — standalone filesystem browser (Task 7.3).

A separate QMainWindow opened from the main toolbar.  It registers
data-source folders (persisted as JSON via ``persistence.data_sources``) and
forwards an activated file to ``AppViewModel.request_load``.

Thin adapter: all application state lives in AppViewModel; this widget only
wires the filesystem tree and the source list to it.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import QModelIndex
from PySide6.QtGui import (
    QContextMenuEvent,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
)
from PySide6.QtWidgets import (
    QFileSystemModel,
    QMainWindow,
    QMenu,
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
    ) -> None:
        super().__init__(parent)
        self._app_vm = app_vm
        self._sources_file = Path(sources_file) if sources_file is not None else None
        self.setWindowTitle("Data Explorer")

        # ── Filesystem tree ──────────────────────────────────────────────────
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setRootPath("")
        self.tree = QTreeView(self)
        self.tree.setModel(self.fs_model)
        self.tree.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.tree.activated.connect(self._on_activated)
        self.setCentralWidget(self.tree)
        self.setAcceptDrops(True)  # OS file-manager drops (R12.1)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar: QToolBar = self.addToolBar("Sources")
        self.action_add_source = toolbar.addAction("Add Source")
        self.action_remove_source = toolbar.addAction("Remove Source")

        # ── Restore persisted sources ────────────────────────────────────────
        if self._sources_file is not None:
            for path in data_sources.load(self._sources_file):
                self._app_vm.add_data_source(path)
            self._show_last_source()

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

    # ─── Load ──────────────────────────────────────────────────────────────────

    def load_path(self, path: Path | str) -> None:
        """Forward *path* to the application ViewModel for loading."""
        self._app_vm.request_load(Path(path))

    def _on_activated(self, index: QModelIndex) -> None:
        """Load files on activation; directories are navigated, not loaded."""
        if not index.isValid() or self.fs_model.isDir(index):
            return
        self.load_path(self.fs_model.filePath(index))

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
                self.load_path(local)
        event.acceptProposedAction()

    # ─── Context menu (R14.2) ───────────────────────────────────────────────────

    def build_context_menu(self, path: Path | str) -> QMenu:
        """Build the file context menu, greyed out per file/source state."""
        path = Path(path)
        menu = QMenu(self)
        load = menu.addAction("Load File")
        load.setEnabled(path.is_file())
        load.triggered.connect(lambda *_: self.load_path(path))
        remove = menu.addAction("Remove from Data Sources")
        remove.setEnabled(str(path) in self.sources())
        remove.triggered.connect(lambda *_: self.remove_source(path))
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        index = self.tree.indexAt(self.tree.viewport().mapFromGlobal(event.globalPos()))
        if index.isValid():
            self.build_context_menu(self.fs_model.filePath(index)).exec(
                event.globalPos()
            )
