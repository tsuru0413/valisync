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

from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM

_Index = QModelIndex | QPersistentModelIndex

SIGNAL_KEYS_MIME = "application/x-valisync-signal-keys"


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
        if (
            index.isValid()
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= index.row() < len(self._vm.files)
        ):
            return self._vm.files[index.row()]
        return None


class SignalTableModel(QAbstractTableModel):
    """QAbstractTableModel mirroring :meth:`ChannelBrowserVM.signals`."""

    HEADERS = ("Name", "Unit")

    def __init__(self, vm: ChannelBrowserVM, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._vm.subscribe(self._on_vm_change)

    def _on_vm_change(self, change: str) -> None:
        if change in ("signals", "filter"):
            self.beginResetModel()
            self.endResetModel()

    def rowCount(self, parent: _Index = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._vm.signals)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        signals = self._vm.signals
        if not (0 <= index.row() < len(signals)):
            return None

        item = signals[index.row()]
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
        signals = self._vm.signals
        if 0 <= index.row() < len(signals):
            return signals[index.row()].key
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
