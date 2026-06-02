"""Qt item-model adapters bridging pure ViewModels to Qt views (Task 7.1).

``ChannelTreeModel`` is a thin :class:`QAbstractItemModel` over
:class:`ChannelBrowserVM`.  It owns no signal state of its own — it reads the
VM's ``tree()`` snapshot and exposes it as a two-level tree (group → signal)
with metadata columns.  ``refresh()`` re-reads the snapshot and resets the
model so a bound ``QTreeView`` re-renders.

This is the only Channel_Browser code path that touches Qt's model API; the
VM stays Qt-free for headless testing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import (
    QAbstractItemModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM

# Qt's overridable model methods accept either index flavour; match the
# supertype signature so mypy's Liskov check passes.
_Index = QModelIndex | QPersistentModelIndex

# Custom MIME type for dragging signal keys from the Channel_Browser to a
# Graph_Panel.  The payload is the namespaced signal names, one per line.
# Defined here (the adapter layer) so both the drag source and the drop sink
# agree on the wire format without coupling two view modules to each other.
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


# Column layout.  Column 0 is the tree/name column; the rest expose the
# signal metadata the VM already computes from each Signal.
_HEADERS = ("Name", "Type", "Samples", "Time Range")


class _Node:
    """Internal tree node kept alive for ``QModelIndex.internalPointer``.

    Qt indexes reference a stable Python object via ``createIndex``; building
    explicit nodes (rather than indexing into nested dicts on the fly) keeps
    parent/child navigation O(1) and the pointers valid for the model's life.
    """

    __slots__ = ("children", "kind", "label", "leaf", "parent", "row")

    def __init__(
        self,
        kind: str,
        row: int,
        parent: _Node | None,
        label: str,
        leaf: dict[str, Any] | None = None,
    ) -> None:
        self.kind = kind  # "group" | "signal"
        self.row = row
        self.parent = parent
        self.children: list[_Node] = []
        self.label = label
        self.leaf = leaf  # populated for signal nodes only


def _format_time_range(time_range: tuple[float, float] | None) -> str:
    if time_range is None:
        return ""
    lo, hi = time_range
    return f"{lo:g} - {hi:g}"


class ChannelTreeModel(QAbstractItemModel):
    """QAbstractItemModel mirroring :meth:`ChannelBrowserVM.tree`."""

    def __init__(self, vm: ChannelBrowserVM, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._roots: list[_Node] = []
        self._build()

    # ─── Tree construction ─────────────────────────────────────────────────────

    def _build(self) -> None:
        """Rebuild the internal node tree from the VM's current snapshot."""
        self._roots = []
        for grow, group in enumerate(self._vm.tree()):
            gnode = _Node("group", grow, None, str(group["key"]))
            for srow, leaf in enumerate(group["signals"]):
                gnode.children.append(
                    _Node("signal", srow, gnode, str(leaf["display_name"]), leaf)
                )
            self._roots.append(gnode)

    def refresh(self) -> None:
        """Re-read the VM snapshot and reset the model (full re-render)."""
        self.beginResetModel()
        self._build()
        self.endResetModel()

    # ─── Index helpers ─────────────────────────────────────────────────────────

    def _node(self, index: _Index) -> _Node | None:
        if not index.isValid():
            return None
        ptr = index.internalPointer()
        return ptr if isinstance(ptr, _Node) else None

    def signal_key_at(self, index: _Index) -> str | None:
        """Return the namespaced signal name for a leaf row, else ``None``.

        Used by the view for selection state and drag-and-drop payloads.
        """
        node = self._node(index)
        if node is not None and node.kind == "signal" and node.leaf is not None:
            return str(node.leaf["name"])
        return None

    # ─── QAbstractItemModel interface ──────────────────────────────────────────

    def index(
        self, row: int, column: int, parent: _Index = QModelIndex()
    ) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = self._node(parent)
        siblings = self._roots if parent_node is None else parent_node.children
        if row < 0 or row >= len(siblings):
            return QModelIndex()
        return self.createIndex(row, column, siblings[row])

    def parent(self, index: _Index) -> QModelIndex:  # type: ignore[override]
        node = self._node(index)
        if node is None or node.parent is None:
            return QModelIndex()
        parent = node.parent
        return self.createIndex(parent.row, 0, parent)

    def rowCount(self, parent: _Index = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        parent_node = self._node(parent)
        if parent_node is None:
            return len(self._roots)
        return len(parent_node.children)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:
        return len(_HEADERS)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        node = self._node(index)
        if node is None:
            return None
        col = index.column()
        if node.kind == "group":
            # Group rows carry a label in column 0 and no metadata elsewhere.
            return node.label if col == 0 else ""
        leaf = node.leaf
        assert leaf is not None  # signal nodes always carry a leaf
        if col == 0:
            return node.label
        if col == 1:
            return str(leaf["dtype"])
        if col == 2:
            return str(leaf["count"])
        if col == 3:
            return _format_time_range(leaf["time_range"])
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
            and 0 <= section < len(_HEADERS)
        ):
            return _HEADERS[section]
        return None

    # ─── Drag source (signal leaves → Graph_Panel) ─────────────────────────────

    def flags(self, index: _Index) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        # Only signal leaves are draggable; group headers are not.
        if self.signal_key_at(index) is not None:
            base |= Qt.ItemFlag.ItemIsDragEnabled
        return base

    def mimeTypes(self) -> list[str]:
        return [SIGNAL_KEYS_MIME]

    def mimeData(self, indexes: Sequence[_Index]) -> QMimeData:
        """Pack the selected signal-leaf keys into a drag payload (deduped).

        Qt passes one index per column of each selected row; collapse them to
        unique signal keys (group rows contribute nothing).
        """
        keys: list[str] = []
        seen: set[str] = set()
        for index in indexes:
            key = self.signal_key_at(index)
            if key is not None and key not in seen:
                seen.add(key)
                keys.append(key)
        return encode_signal_keys(keys)
