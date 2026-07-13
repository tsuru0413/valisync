"""SignalTreeModel (FU-22 B): a lazy hierarchical QAbstractItemModel over the
active file's signals, grouped by base channel. Array variables (LD-14
Name[i]/.field) are collapsible parent nodes; scalars are leaves. Only the
top-level (base) nodes are built eagerly; each array's children are materialized
on the first rowCount/index for that parent. Fixes the 264k flat-reset freeze
(QTreeView builds one internal viewItem per row on reset -- collapsed the top
level is ~4,264 rows, not 264k)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import (
    QAbstractItemModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from valisync.gui.adapters.qt_signal_models import SIGNAL_KEYS_MIME, encode_signal_keys

if TYPE_CHECKING:
    from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM

# Qt's C++ signatures accept either index kind as the *parent* argument; the
# navigation methods below always *return* a plain QModelIndex (matches the
# QAbstractItemModel supertype exactly, see PySide6 stubs).
_Index = QModelIndex | QPersistentModelIndex


class _Node:
    """A tree node OWNED by the model (never pass a transient node to
    createIndex -- internalPointer would dangle and crash)."""

    __slots__ = ("children", "key", "leaves", "orig", "parent", "row", "unit")

    def __init__(
        self,
        orig: str,
        unit: str,
        key: str | None,
        leaves: list[tuple[str, str, str]] | None,
        parent: _Node | None,
        row: int,
    ) -> None:
        self.orig = orig  # display name (Name column)
        self.unit = unit  # unit (Unit column); "" for a parent (aggregated in incr 5)
        self.key = key  # leaf signal_key; None for a parent node
        self.leaves = leaves  # parent: [(orig, unit, key)]; leaf: None
        self.children: list[_Node] | None = None  # None = not materialized
        self.parent = parent
        self.row = row


class SignalTreeModel(QAbstractItemModel):
    HEADERS = ("Name", "Unit")

    def __init__(self, vm: ChannelBrowserVM, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._top: list[_Node] = []
        self._rebuild()
        self._vm.subscribe(self._on_vm_change)

    # --- build ----------------------------------------------------------------
    def _on_vm_change(self, change: str) -> None:
        if change in ("signals", "filter"):
            self.beginResetModel()
            self._rebuild()
            self.endResetModel()

    def _rebuild(self) -> None:
        """Eager top-level only; children stay lazy (None)."""
        top: list[_Node] = []
        for row, (base, leaves) in enumerate(self._vm.tree_groups()):
            if len(leaves) == 1:
                orig, unit, key = leaves[0]
                top.append(_Node(orig, unit, key, None, None, row))
            else:
                top.append(_Node(base, "", None, leaves, None, row))
        self._top = top

    def _materialize(self, node: _Node) -> None:
        if node.children is None:
            node.children = [
                _Node(orig, unit, key, None, node, r)
                for r, (orig, unit, key) in enumerate(node.leaves or [])
            ]

    # --- navigation -------------------------------------------------------------
    def index(
        self, row: int, column: int, parent: _Index = QModelIndex()
    ) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, self._top[row])
        pnode: _Node = parent.internalPointer()
        self._materialize(pnode)
        return self.createIndex(row, column, pnode.children[row])  # type: ignore[index]

    def parent(self, index: _Index = QModelIndex()) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        node: _Node = index.internalPointer()
        p = node.parent
        if p is None:
            return QModelIndex()
        return self.createIndex(p.row, 0, p)

    def rowCount(self, parent: _Index = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            return len(self._top)
        node: _Node = parent.internalPointer()
        if node.key is not None:  # leaf
            return 0
        self._materialize(node)
        return len(node.children or [])

    def hasChildren(self, parent: _Index = QModelIndex()) -> bool:
        if not parent.isValid():
            return len(self._top) > 0
        node: _Node = parent.internalPointer()
        return node.key is None and bool(node.leaves)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:
        return len(self.HEADERS)

    # --- presentation -----------------------------------------------------------
    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        node: _Node = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return node.orig
            if index.column() == 1:
                return node.unit
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
        """Leaf signal_key, or None for a parent (array) node."""
        if not index.isValid():
            return None
        return index.internalPointer().key

    # --- drag (leaf only in increment 1; parent aggregate = increment 4) --------
    def flags(self, index: _Index) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        node: _Node = index.internalPointer()
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if node.key is not None:
            base |= Qt.ItemFlag.ItemIsDragEnabled
        return base

    def mimeTypes(self) -> list[str]:
        return [SIGNAL_KEYS_MIME]

    def mimeData(self, indexes: Sequence[_Index]) -> QMimeData:
        keys: list[str] = []
        seen: set[int] = set()
        for index in indexes:
            if not index.isValid():
                continue
            node: _Node = index.internalPointer()
            if id(node) in seen:
                continue
            seen.add(id(node))
            if node.key is not None:  # leaf only in increment 1
                keys.append(node.key)
        return encode_signal_keys(keys)
