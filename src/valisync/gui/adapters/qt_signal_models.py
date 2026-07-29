"""Qt item-model adapters bridging pure ViewModels to Qt views (Task 2.2).

This module provides models that adapt pure Python ViewModels (Observable)
to Qt's Model/View architecture.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtGui import QColor

from valisync.gui.theme import tokens
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

    ReleasingRole = Qt.ItemDataRole.UserRole + 1

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
        if role == FileListModel.ReleasingRole:
            return self._vm.is_releasing(index.row())
        if role == Qt.ItemDataRole.ForegroundRole and self._vm.is_releasing(
            index.row()
        ):
            return QColor(
                *tokens.active().colors.text_releasing.rgba
            )  # 解放中の行はグレーアウト
        if role == Qt.ItemDataRole.DecorationRole:
            # ファイル=色相ファミリーのチップ (E-2c・spec §4.3) — 比較モード時のみ
            # (chip_color が同一述語で None を返す)。QListView は QColor を渡すと
            # 自動で色見本を描く。
            color_hex = self._vm.chip_color(index.row())
            if color_hex is not None:
                return QColor(color_hex)
        return None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.isValid() and self._vm.is_releasing(index.row()):
            # 解放中の行は選択も操作も不可(スピナーのプレースホルダ)。
            return base & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled
        return base
