"""SignalTreeModel (FU-22 B / E-2): a lazy hierarchical QAbstractItemModel over
the active file's signals, one top-level row per **physical channel**. A channel
the loader exploded into several columns (LD-14 Name[i]/.field) is a collapsible
parent node; a channel presenting a single column is a leaf. Only the top-level
nodes are built eagerly; a parent's children are *synthesized* from
ChannelBrowserVM.column_names_for() on the first rowCount/index for that parent
-- never during _rebuild, which at prod scale (4,324 rows / 264,004 columns)
would be O(n^2) and undo the increment. Fixes the 264k flat-reset freeze
(QTreeView builds one internal viewItem per row on reset -- collapsed the top
level is ~4,324 rows, not 264k)."""

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

from valisync.gui import strings as S
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

    __slots__ = ("base_key", "children", "key", "orig", "parent", "row", "unit")

    def __init__(
        self,
        orig: str,
        unit: str,
        key: str | None,
        base_key: str | None,
        parent: _Node | None,
        row: int,
    ) -> None:
        self.orig = orig  # display name (Name column)
        self.unit = unit  # unit (Unit column); "" for a parent (aggregated in incr 5)
        self.key = key  # leaf signal_key; None for a parent node
        # Synthetic grouping handle passed back to column_names_for() when this
        # node is expanded. NOT a signal_key (a physical channel that was
        # exploded has no Signal of its own) -- never let it reach .key.
        self.base_key = base_key
        self.children: list[_Node] | None = None  # None = not materialized
        self.parent = parent
        self.row = row


class SignalTreeModel(QAbstractItemModel):
    HEADERS = (S.SIGNAL_TREE_COL_NAME, S.SIGNAL_TREE_COL_UNIT)

    def __init__(self, vm: ChannelBrowserVM, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._top: list[_Node] = []
        self._sort_col: int = -1
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder
        self._rebuild()
        self._vm.subscribe(self._on_vm_change)

    # --- build ----------------------------------------------------------------
    def _on_vm_change(self, change: str) -> None:
        if change in ("signals", "filter"):
            self.beginResetModel()
            self._rebuild()
            self.endResetModel()

    def _rebuild(self) -> None:
        """Eager top-level only; children stay lazy (None).

        column_names_for() is deliberately NOT called here: at prod scale that
        is one span walk per row on every reset (O(n^2)) and would rebuild the
        very per-column objects this increment removed.
        """
        top: list[_Node] = []
        for row, (name, unit, base_key, _count, single) in enumerate(
            self._vm.tree_groups()
        ):
            if single is not None:
                # This row currently presents exactly one column (either the
                # channel really has one, or the filter narrowed it to one).
                # Both the key and the display name come from that column's
                # **real identity** -- the synthetic base_key may not exist as a
                # Signal at all (parent "Mono" of Mono[0], "P" of P.x, "Q" of
                # Q.x), and using it as a leaf key would produce a row that is
                # visible but can never be plotted.
                orig, key = single
                top.append(_Node(orig, unit, key, base_key, None, row))
            else:
                # Parent rows keep a blank Unit cell (UX-29: the unit lives on
                # the children; aggregation is deferred to increment 5).
                top.append(_Node(name, "", None, base_key, None, row))
        self._top = top
        self._sort_top()  # preserve the active sort across filter/signal rebuilds

    def _materialize(self, node: _Node) -> None:
        """Synthesize *node*'s children on first demand (expansion), never before."""
        if node.children is None:
            # A node reaching here is a parent (hasChildren()==True implies
            # key is None, and rowCount()/hasIndex() keep leaves from ever
            # reaching _materialize -- see hasChildren()/rowCount() above), so
            # it must carry a grouping handle. Fail loudly instead of
            # silently building a childless expandable row (a leaf wrongly
            # treated as a parent would previously vanish into `else []`).
            assert node.base_key is not None
            columns = self._vm.column_names_for(node.base_key)
            # Children are always leaves: base_key None (nothing to expand).
            node.children = [
                _Node(orig, unit, key, None, node, r)
                for r, (orig, unit, key) in enumerate(columns)
            ]
            self._sort_children(node)  # apply the active sort to freshly-built children

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
        # tree_groups() never returns a row with 0 matching columns, and a row
        # down to 1 matching column is emitted as a leaf (key not None), so
        # key is None <=> presented columns >= 2. Do NOT decide this from the
        # column count (that is filter-independent, so a row the filter narrowed
        # to a single column would stay a non-draggable parent). Answering
        # without materializing is the whole point of this shape (rowCount does
        # materialize).
        return node.key is None

    def columnCount(self, parent: _Index = QModelIndex()) -> int:
        return len(self.HEADERS)

    # --- sort (VM-side; proxy was dropped -- it materialized all children) -------
    def sort(
        self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder
    ) -> None:
        """Sort top-level bases now; children are sorted lazily on materialize so
        an unexpanded array is never built just to sort (preserves the lazy tree)."""
        self._sort_col = column
        self._sort_order = order
        self.beginResetModel()
        self._sort_top()
        for node in self._top:
            if node.children is not None:  # already-materialized parents only
                self._sort_children(node)
        self.endResetModel()

    def _sort_key(self, node: _Node, column: int) -> str:
        return (node.orig if column == 0 else node.unit).lower()

    def _sort_top(self) -> None:
        if self._sort_col < 0:
            return  # passthrough: keep session order (as built by _rebuild)
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder
        self._top.sort(key=lambda n: self._sort_key(n, self._sort_col), reverse=reverse)
        for i, n in enumerate(self._top):
            n.row = i

    def _sort_children(self, node: _Node) -> None:
        if self._sort_col < 0 or not node.children:
            return
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder
        node.children.sort(
            key=lambda n: self._sort_key(n, self._sort_col), reverse=reverse
        )
        for i, n in enumerate(node.children):
            n.row = i

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

    def has_materialized_children(self, index: _Index) -> bool:
        """True if *index* is the invalid root, a leaf (no children ever), or a
        group whose children are already built. Never triggers materialization
        itself (unlike rowCount()/index()) -- callers use this to decide
        whether descending into a subtree is free (e.g. UX-29's bounded Unit
        column sampling, which must not force-build array children on every
        reset; that would defeat the lazy tree this model exists for, see
        module docstring / FU-22 B)."""
        if not index.isValid():
            return True  # root: self._top is always built eagerly
        node: _Node = index.internalPointer()
        return node.key is not None or node.children is not None

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
