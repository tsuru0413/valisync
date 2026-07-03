"""Qt item-model adapters bridging pure ViewModels to Qt views (Task 2.2).

This module provides models that adapt pure Python ViewModels (Observable)
to Qt's Model/View architecture.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QAbstractTableModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM, SignalItem
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM

_Index = QModelIndex | QPersistentModelIndex

SIGNAL_KEYS_MIME = "application/x-valisync-signal-keys"

# Distinct mime type for an axis-move drag (relocate an existing axis to another
# column/position), so the GraphPanelView drop sink can tell it apart from a
# signal-key drop (add/overwrite a signal) carried under SIGNAL_KEYS_MIME.
AXIS_INDEX_MIME = "application/x-valisync-axis-index"


def encode_signal_keys(keys: list[str]) -> QMimeData:
    """Pack *keys* into a QMimeData payload under :data:`SIGNAL_KEYS_MIME`."""
    md = QMimeData()
    md.setData(SIGNAL_KEYS_MIME, "\n".join(keys).encode("utf-8"))
    return md


def decode_signal_keys(md: QMimeData) -> list[str]:
    """Extract signal keys from *md*; empty list if it carries no such payload."""
    if not md.hasFormat(SIGNAL_KEYS_MIME):
        return []
    raw = bytes(md.data(SIGNAL_KEYS_MIME).data()).decode("utf-8")
    return raw.split("\n") if raw else []


def encode_axis_move(source_panel_index: int, axis_index: int) -> QMimeData:
    """Pack a {source_panel_index, axis_index} axis-move payload under AXIS_INDEX_MIME."""
    md = QMimeData()
    md.setData(AXIS_INDEX_MIME, f"{source_panel_index},{axis_index}".encode())
    return md


def decode_axis_move(md: QMimeData) -> tuple[int, int] | None:
    """Extract (source_panel_index, axis_index) from *md*; None if absent/invalid."""
    if not md.hasFormat(AXIS_INDEX_MIME):
        return None
    try:
        src, axis = bytes(md.data(AXIS_INDEX_MIME).data()).decode("utf-8").split(",")
        return int(src), int(axis)
    except (ValueError, TypeError):
        return None


class FileListModel(QAbstractListModel):
    """QAbstractListModel mirroring :meth:`FileBrowserVM.files`."""

    def __init__(self, vm: FileBrowserVM, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._vm.subscribe(self._on_vm_change)

    def _on_vm_change(self, change: str) -> None:
        if change == "files":
            self.beginResetModel()
            self.endResetModel()

    def rowCount(self, parent: _Index = QModelIndex()) -> int:
        return len(self._vm.files)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._vm.files)):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._vm.files[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._vm.tooltip_text(index.row())
        return None


class SignalTableModel(QAbstractTableModel):
    """QAbstractTableModel mirroring :meth:`ChannelBrowserVM.signals`."""

    HEADERS = ("Name", "Unit")

    def __init__(self, vm: ChannelBrowserVM, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        # Snapshot the VM's signal list so per-cell lookups (rowCount/data) are
        # O(1) instead of recomputing the whole list on every cell.
        self._rows: list[SignalItem] = list(vm.signals)
        self._vm.subscribe(self._on_vm_change)

    def _on_vm_change(self, change: str) -> None:
        if change in ("signals", "filter"):
            self.beginResetModel()
            self._rows = list(self._vm.signals)
            self.endResetModel()

    def rowCount(self, parent: _Index = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        if not (0 <= index.row() < len(self._rows)):
            return None

        item = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return item.name
            if col == 1:
                return item.unit

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(self.HEADERS)
        ):
            return self.HEADERS[section]
        return None

    def signal_key_at(self, index: _Index) -> str | None:
        """Return the namespaced signal key for a row."""
        if not index.isValid():
            return None
        if 0 <= index.row() < len(self._rows):
            return self._rows[index.row()].key
        return None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
        )

    def mimeTypes(self) -> list[str]:
        return [SIGNAL_KEYS_MIME]

    def mimeData(self, indexes: Sequence[_Index]) -> QMimeData:
        keys: list[str] = []
        seen: set[int] = set()
        for index in indexes:
            row = index.row()
            if row not in seen:
                key = self.signal_key_at(index)
                if key:
                    keys.append(key)
                seen.add(row)
        return encode_signal_keys(keys)
