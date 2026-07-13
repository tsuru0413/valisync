# FU-22 (B) 増分① 階層ツリーモデル・コア 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChannelBrowser を遅延階層 QTreeView へ移行し、genuine ファイル選択の 5s フリーズを解消する(top-level 4,264 行 reset ~67ms + 484ms VM 構築消滅)。増分① = モデル + VM グルーピング + view 差し替え + 展開/折畳 + リーフ選択/D&D/追加パリティ + grab-point 親スレッド化。

**Architecture:** 新 `SignalTreeModel`(QAbstractItemModel・node グラフをモデル所有・遅延 materialize)。配列変数を親ノード・要素を子ノードに。フィルタ(増分②)/sort(③)/親D&D(④)は本プラン対象外。

**Tech Stack:** PySide6/pyqtgraph, MVVM(Observable), pytest-qt。設計 [spec](../specs/2026-07-13-fu22b-channel-tree-virtualization-design.md)。

## Global Constraints

- core(session.py/Signal/非 Qt VM 部) は Qt 非依存維持。`SignalTreeModel` は gui/adapters。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過。
- Python コメント/文字列に全角約物 `()：+=` 禁止(RUF001/002/003)。ASCII `()`, `:`, `+`, `=` を使う(矢印 `->`/`→`・`・` は可)。
- **本ブランチは増分②③④(フィルタ/sort/親D&D)でパリティ復旧するまで merge しない**。増分①は review チェックポイント(主症状解消の最小コア)。
- gui-test-plan 分類: 入力経路直結の view 変更 = クロスカット。honest observable = index/parent 往復・lazy materialize(Layer A)・リーフ選択/D&D の源キー解決(Layer B)・realgui パリティ・prod 実測(5,000ms->~500ms)。
- node は必ずモデル所有のキャッシュ済みを `createIndex` に渡す(transient は internalPointer ダングリングでクラッシュ)。

---

### Task 1: ChannelBrowserVM.tree_groups() ベースグルーピング

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`
- Test: `tests/gui/test_channel_browser_vm.py`

**Interfaces:**
- Consumes: 既存 `self._ensure_prep()` が `self._prep = list[(orig, lower, unit, key)]` を構築(active file ごと 1 回・152ms)。
- Produces: `tree_groups() -> list[tuple[str, list[tuple[str, str, str]]]]` = `[(base, [(orig, unit, key), ...]), ...]`。ベース first-seen 順保持。base = orig の最初の `[` or `.` 以前。フィルタ非適用(増分② で対応)。

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_channel_browser_vm.py` に追加:

```python
def test_tree_groups_buckets_arrays_under_base(tmp_path: Path) -> None:
    """FU-22 B: LD-14 名を base(最初の [ or . 以前)でグルーピング。配列は複数リーフ・スカラーは単一。"""
    import numpy as np

    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    def _sig(name: str) -> Signal:
        return Signal(
            name=name, timestamps=np.array([0.0]), values=np.array([1.0]),
            file_format="MDF4", bus_type="", source_file="",
            metadata={"unit": "V"},
        )

    app_vm.session.group_signals = lambda key: [
        _sig("g::Arr[0]"), _sig("g::Arr[1]"), _sig("g::Arr[2]"),
        _sig("g::Scalar"),
        _sig("g::Struct.field"),
    ]
    app_vm.set_active_file("g")

    groups = vm.tree_groups()
    as_dict = {base: leaves for base, leaves in groups}
    assert [b for b, _ in groups] == ["Arr", "Scalar", "Struct"]  # first-seen order
    assert len(as_dict["Arr"]) == 3
    assert as_dict["Arr"][0] == ("Arr[0]", "V", "g::Arr[0]")  # (orig, unit, key)
    assert len(as_dict["Scalar"]) == 1
    assert as_dict["Struct"][0] == ("Struct.field", "V", "g::Struct.field")
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py::test_tree_groups_buckets_arrays_under_base -v`
Expected: FAIL(`tree_groups` 未定義)。

- [ ] **Step 3: 実装**

`channel_browser_vm.py` の import に `import re` を追加し、`ChannelBrowserVM` にモジュール定数とメソッドを追加(既存 `_ensure_prep` の後):

```python
_BASE_RE = re.compile(r"[\[.]")


def _base_of(orig: str) -> str:
    """Base channel name = orig up to the first LD-14 suffix marker ('[' or '.')."""
    m = _BASE_RE.search(orig)
    return orig[: m.start()] if m else orig
```

(モジュールレベルに置く。`_SEP` の近く。)

`ChannelBrowserVM` メソッド:

```python
    def tree_groups(self) -> list[tuple[str, list[tuple[str, str, str]]]]:
        """Group the active file's signals by base channel for the tree browser.

        Returns [(base, [(orig, unit, key), ...]), ...] in base first-seen order.
        Arrays (LD-14 Name[i]/.field) bucket under their base; scalars are a
        single-leaf group. Filter is NOT applied here (increment 2)."""
        self._ensure_prep()
        groups: dict[str, list[tuple[str, str, str]]] = {}
        order: list[str] = []
        for orig, _lower, unit, key in self._prep:
            base = _base_of(orig)
            bucket = groups.get(base)
            if bucket is None:
                bucket = groups[base] = []
                order.append(base)
            bucket.append((orig, unit, key))
        return [(b, groups[b]) for b in order]
```

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py -v`
Expected: 新規含め全 PASS。

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/viewmodels/channel_browser_vm.py tests/gui/test_channel_browser_vm.py
git commit -m "feat(fu22b): ChannelBrowserVM.tree_groups で信号を base チャンネルにグルーピング"
```

---

### Task 2: SignalTreeModel ナビゲーション(node グラフ・遅延・index/parent)

**Files:**
- Create: `src/valisync/gui/adapters/signal_tree_model.py`
- Test: `tests/gui/test_signal_tree_model.py`

**Interfaces:**
- Consumes: `ChannelBrowserVM.tree_groups()`(Task 1)・`vm.subscribe`。
- Produces: `SignalTreeModel(vm)` = QAbstractItemModel。top-level=base ノード(単一リーフの base は leaf ノード・複数は parent)。`index`/`parent`/`rowCount`/`hasChildren`/`columnCount`。子は初回 `rowCount`/`index` で materialize。

- [ ] **Step 1: 失敗テスト(往復・遅延・構造)**

`tests/gui/test_signal_tree_model.py` を作成:

```python
"""Tests for SignalTreeModel (FU-22 B): hierarchical lazy tree over base channels."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QModelIndex
from pytestqt.qtbot import QtBot

from valisync.core.models import Signal
from valisync.gui.adapters.signal_tree_model import SignalTreeModel
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM


def _sig(name: str) -> Signal:
    return Signal(
        name=name, timestamps=np.array([0.0]), values=np.array([1.0]),
        file_format="MDF4", bus_type="", source_file="", metadata={"unit": "V"},
    )


def _model(qtbot: QtBot) -> SignalTreeModel:
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    app_vm.session.group_signals = lambda key: [
        _sig("g::Arr[0]"), _sig("g::Arr[1]"), _sig("g::Arr[2]"),
        _sig("g::Scalar"),
    ]
    app_vm.set_active_file("g")
    return SignalTreeModel(vm)


def test_top_level_row_count(qtbot: QtBot) -> None:
    m = _model(qtbot)
    assert m.rowCount(QModelIndex()) == 2  # Arr (parent) + Scalar (leaf)


def test_array_parent_has_children_scalar_leaf_does_not(qtbot: QtBot) -> None:
    m = _model(qtbot)
    arr = m.index(0, 0, QModelIndex())
    scalar = m.index(1, 0, QModelIndex())
    assert m.hasChildren(arr) is True
    assert m.rowCount(arr) == 3
    assert m.hasChildren(scalar) is False
    assert m.rowCount(scalar) == 0


def test_index_parent_round_trip(qtbot: QtBot) -> None:
    m = _model(qtbot)
    arr = m.index(0, 0, QModelIndex())
    child = m.index(1, 0, arr)
    assert child.isValid()
    assert m.parent(child) == arr
    assert m.parent(arr) == QModelIndex()  # top-level has no parent


def test_children_lazy_until_requested(qtbot: QtBot) -> None:
    m = _model(qtbot)
    arr_node = m.index(0, 0, QModelIndex()).internalPointer()
    assert arr_node.children is None  # not materialized before rowCount/index
    m.rowCount(m.index(0, 0, QModelIndex()))
    assert arr_node.children is not None and len(arr_node.children) == 3
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_signal_tree_model.py -v`
Expected: FAIL(モジュール未作成)。

- [ ] **Step 3: 実装(ナビゲーション部)**

`src/valisync/gui/adapters/signal_tree_model.py` を作成:

```python
"""SignalTreeModel (FU-22 B): a lazy hierarchical QAbstractItemModel over the
active file's signals, grouped by base channel. Array variables (LD-14
Name[i]/.field) are collapsible parent nodes; scalars are leaves. Only the
top-level (base) nodes are built eagerly; each array's children are materialized
on the first rowCount/index for that parent. Fixes the 264k flat-reset freeze
(QTreeView builds one internal viewItem per row on reset -- collapsed the top
level is ~4,264 rows, not 264k)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QObject

if TYPE_CHECKING:
    from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM

_Index = QModelIndex


class _Node:
    """A tree node OWNED by the model (never pass a transient node to
    createIndex -- internalPointer would dangle and crash)."""

    __slots__ = ("orig", "unit", "key", "leaves", "children", "parent", "row")

    def __init__(
        self,
        orig: str,
        unit: str,
        key: str | None,
        leaves: list[tuple[str, str, str]] | None,
        parent: "_Node | None",
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

    def __init__(self, vm: "ChannelBrowserVM", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._top: list[_Node] = []
        self._rebuild()
        self._vm.subscribe(self._on_vm_change)

    # ─── build ────────────────────────────────────────────────────────────────
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

    # ─── navigation ─────────────────────────────────────────────────────────────
    def index(self, row: int, column: int, parent: _Index = _Index()) -> _Index:
        if not self.hasIndex(row, column, parent):
            return _Index()
        if not parent.isValid():
            return self.createIndex(row, column, self._top[row])
        pnode: _Node = parent.internalPointer()
        self._materialize(pnode)
        return self.createIndex(row, column, pnode.children[row])  # type: ignore[index]

    def parent(self, index: _Index = _Index()) -> _Index:  # type: ignore[override]
        if not index.isValid():
            return _Index()
        node: _Node = index.internalPointer()
        p = node.parent
        if p is None:
            return _Index()
        return self.createIndex(p.row, 0, p)

    def rowCount(self, parent: _Index = _Index()) -> int:
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            return len(self._top)
        node: _Node = parent.internalPointer()
        if node.key is not None:  # leaf
            return 0
        self._materialize(node)
        return len(node.children or [])

    def hasChildren(self, parent: _Index = _Index()) -> bool:
        if not parent.isValid():
            return len(self._top) > 0
        node: _Node = parent.internalPointer()
        return node.key is None and bool(node.leaves)

    def columnCount(self, parent: _Index = _Index()) -> int:
        return len(self.HEADERS)
```

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_signal_tree_model.py -v`
Expected: 4 件 PASS(往復・遅延・hasChildren・rowCount)。

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/adapters/signal_tree_model.py tests/gui/test_signal_tree_model.py
git commit -m "feat(fu22b): SignalTreeModel ナビゲーション(遅延 node グラフ・index/parent 往復)"
```

---

### Task 3: SignalTreeModel データ提示 + D&D(data/flags/mimeData/signal_key_at)

**Files:**
- Modify: `src/valisync/gui/adapters/signal_tree_model.py`
- Test: `tests/gui/test_signal_tree_model.py`

**Interfaces:**
- Consumes: Task 2 の node/ナビゲーション、`SIGNAL_KEYS_MIME`/`encode_signal_keys`。
- Produces: `data`(Name/Unit)・`headerData`・`signal_key_at`(リーフ key・親 None)・`flags`(リーフのみ Drag・親 D&D は増分④)・`mimeTypes`・`mimeData`(リーフ key のみ・増分④で親対応)。

- [ ] **Step 1: 失敗テスト**

`tests/gui/test_signal_tree_model.py` に追加:

```python
from PySide6.QtCore import Qt
from valisync.gui.adapters.qt_signal_models import SIGNAL_KEYS_MIME, decode_signal_keys


def test_data_name_and_unit(qtbot: QtBot) -> None:
    m = _model(qtbot)
    arr = m.index(0, 0, QModelIndex())
    child0 = m.index(0, 0, arr)
    assert m.data(child0, Qt.ItemDataRole.DisplayRole) == "Arr[0]"
    assert m.data(m.index(0, 1, arr), Qt.ItemDataRole.DisplayRole) == "V"
    # parent Name = base, unit blank (aggregated in incr 5)
    assert m.data(arr, Qt.ItemDataRole.DisplayRole) == "Arr"
    assert m.data(m.index(0, 1, QModelIndex()), Qt.ItemDataRole.DisplayRole) == ""


def test_signal_key_at_leaf_vs_parent(qtbot: QtBot) -> None:
    m = _model(qtbot)
    arr = m.index(0, 0, QModelIndex())
    scalar = m.index(1, 0, QModelIndex())
    assert m.signal_key_at(m.index(0, 0, arr)) == "g::Arr[0]"
    assert m.signal_key_at(scalar) == "g::Scalar"
    assert m.signal_key_at(arr) is None  # parent has no single key


def test_flags_leaf_draggable_parent_not(qtbot: QtBot) -> None:
    m = _model(qtbot)
    arr = m.index(0, 0, QModelIndex())
    leaf = m.index(0, 0, arr)
    assert m.flags(leaf) & Qt.ItemFlag.ItemIsDragEnabled
    assert not (m.flags(arr) & Qt.ItemFlag.ItemIsDragEnabled)  # parent drag = incr 4


def test_mimedata_encodes_leaf_keys(qtbot: QtBot) -> None:
    m = _model(qtbot)
    arr = m.index(0, 0, QModelIndex())
    mime = m.mimeData([m.index(0, 0, arr), m.index(1, 0, arr)])
    assert decode_signal_keys(mime) == ["g::Arr[0]", "g::Arr[1]"]
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_signal_tree_model.py -k "data or signal_key or flags or mimedata" -v`
Expected: FAIL(未実装)。

- [ ] **Step 3: 実装(提示 + D&D 部を SignalTreeModel に追加)**

まず import を拡張(Task 2 の最小 import に追記):
- `from typing import TYPE_CHECKING` -> `from typing import TYPE_CHECKING, Any, Sequence`
- `from PySide6.QtCore import QAbstractItemModel, QModelIndex, QObject` -> `..., QModelIndex, QObject, QMimeData, Qt`
- `from valisync.gui.adapters.qt_signal_models import SIGNAL_KEYS_MIME, encode_signal_keys` を追加

`signal_tree_model.py` の `columnCount` の後にメソッドを追加:

```python
    # ─── presentation ────────────────────────────────────────────────────────────
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
        self, section: int, orientation: Qt.Orientation,
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

    # ─── drag (leaf only in increment 1; parent aggregate = increment 4) ──────────
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
```

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_signal_tree_model.py -v`
Expected: 全 PASS。

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/adapters/signal_tree_model.py tests/gui/test_signal_tree_model.py
git commit -m "feat(fu22b): SignalTreeModel の data/flags/mimeData(リーフ D&D パリティ)"
```

---

### Task 4: ChannelBrowserView を階層モデルへ差し替え + パリティ + grab-point

**Files:**
- Modify: `src/valisync/gui/views/channel_browser_view.py`
- Test: `tests/gui/test_channel_browser_view.py`

**Interfaces:**
- Consumes: `SignalTreeModel`(Task 2/3)。既存 `proxy`(QSortFilterProxyModel・accept-all)・`self.tree`(QTreeView)。
- Produces: view が `SignalTreeModel` を表示(展開/折畳)。`selected_signal_keys()` が**リーフのみ**を源解決(親/未展開は無視)。grab-point は親スレッド化(`proxy.index(childRow, 0, proxy.mapFromSource(親src))`)。

- [ ] **Step 1: 失敗テスト(パリティ)**

`tests/gui/test_channel_browser_view.py` に追加(既存 import の `SignalTableModel` は残す・新規に tree を検証):

```python
def test_view_uses_signal_tree_model(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-22 B: ChannelBrowserView は SignalTreeModel(階層)を表示する。"""
    from valisync.gui.adapters.signal_tree_model import SignalTreeModel

    app_vm, view, key = _make_view_with_arrays(qtbot, tmp_path)
    assert isinstance(view.model, SignalTreeModel)
    # top-level に配列親が居り、展開で子が見える
    proxy = view.proxy
    top0 = proxy.index(0, 0)
    assert view.model.rowCount(proxy.mapToSource(top0)) >= 1


def test_selected_leaf_resolves_source_key(qtbot: QtBot, tmp_path: Path) -> None:
    """親を展開しリーフを選択すると selected_signal_keys が源 key を返す(親スレッド grab)。"""
    app_vm, view, key = _make_view_with_arrays(qtbot, tmp_path)
    proxy, model = view.proxy, view.model
    parent_src = model.index(0, 0, QModelIndex())  # array parent
    parent_proxy = proxy.mapFromSource(parent_src)
    child_proxy = proxy.index(0, 0, parent_proxy)  # thread the parent
    view.tree.selectionModel().select(
        child_proxy, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    )
    keys = view.selected_signal_keys()
    assert len(keys) == 1 and keys[0].endswith("[0]")


def test_selecting_parent_yields_no_leaf_keys_in_incr1(qtbot: QtBot, tmp_path: Path) -> None:
    """増分①: 親選択は源 key を持たない(親追加は増分④)。"""
    app_vm, view, key = _make_view_with_arrays(qtbot, tmp_path)
    proxy, model = view.proxy, view.model
    parent_proxy = proxy.mapFromSource(model.index(0, 0, QModelIndex()))
    view.tree.selectionModel().select(
        parent_proxy, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    )
    assert view.selected_signal_keys() == []
```

`_make_view_with_arrays` ヘルパをテスト冒頭付近に追加(既存 `_loaded_vm`/`_cb_view_with_signals` と同じく `ChannelBrowserVM(app_vm)` を直接構築。VM は MainWindow 所有で `app_vm.channel_browser_vm` アクセサは存在しない):

```python
def _make_view_with_arrays(qtbot, tmp_path):
    import numpy as np
    from valisync.core.models import Signal
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
    from valisync.gui.views.channel_browser_view import ChannelBrowserView

    app_vm = AppViewModel()

    def _sig(name):
        return Signal(name=name, timestamps=np.array([0.0]), values=np.array([1.0]),
                      file_format="MDF4", bus_type="", source_file="", metadata={"unit": "V"})

    # set_active_file はキー存在を検証しない(FU-22 A)。group_signals を monkeypatch
    # すれば "g" は実ロード不要。active file を先に立ててから VM/view を作る
    # (SignalTreeModel は __init__ で tree_groups を読むため)。
    app_vm.session.group_signals = lambda k: [
        _sig("g::Arr[0]"), _sig("g::Arr[1]"), _sig("g::Scalar"),
    ]
    app_vm.set_active_file("g")
    vm = ChannelBrowserVM(app_vm)
    view = ChannelBrowserView(vm)
    qtbot.addWidget(view)
    return app_vm, view, "g"
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_channel_browser_view.py -k "tree_model or leaf_resolves or parent_yields" -v`
Expected: FAIL(view はまだ `SignalTableModel`)。

- [ ] **Step 3: 実装(view 差し替え・最小)**

`channel_browser_view.py`(既存の `selected_signal_keys`/`mime_data_for_selection` は既に `proxy.mapToSource` + `signal_key_at` + `if key is not None` = 親スキップ済みのため**無変更**):
1. import 行(`from valisync.gui.adapters.qt_signal_models import ...` 付近)の `SignalTableModel` を `from valisync.gui.adapters.signal_tree_model import SignalTreeModel` へ差し替え。`SignalTableModel` が他で未使用になるなら import から除去(ruff F401 回避)。`encode_signal_keys` 等の他 import は残す。
2. `:56` `self.model = SignalTableModel(vm)` -> `self.model = SignalTreeModel(vm)`。
3. `:90-91` のフラット装飾 2 行(`setRootIsDecorated(False)`/`setItemsExpandable(False)`)と直前コメント `# Refactor for flat list appearance` を**削除**(QTreeView 既定 = decoration/expandable True = 階層の展開矢印)。
4. クラス docstring(`:47` 付近 `flat tree view` 表現)を階層向けに更新(WHY: 配列を親ノードに畳む)。

- [ ] **Step 4: 既存 flat 前提テストの是正(限定)**

スカラー信号はツリーでは top-level リーフ = 既存スカラーのみテスト(PC-20 sort 群含む)は無回帰。是正が要るのは以下のみ:
- `test_flat_appearance`(`:134-140`): `assert not view.tree.rootIsDecorated()` を階層前提へ反転。テスト名/コメントも更新:

```python
class TestLayout:
    def test_hierarchical_appearance(self, qtbot: QtBot, tmp_path: Path) -> None:
        app_vm, _ = _setup_app(tmp_path)
        vm = ChannelBrowserVM(app_vm)
        view = _make_view(qtbot, vm)

        # FU-22 B: array bases are collapsible -> expand/collapse decoration on
        assert view.tree.rootIsDecorated()
```

- `test_search_box_filters_list`(`TestSearchFilter`, `:109-118`): フィルタは増分②で配線。①では検索がツリーを絞らないため skip:

```python
    @pytest.mark.skip(reason="FU-22 B: filter wiring lands in increment 2")
    def test_search_box_filters_list(self, qtbot: QtBot, tmp_path: Path) -> None:
```

(`import pytest` が無ければ追加。)
- `:311-312` 付近の header コメント内 `SignalTableModel (source)` を `SignalTreeModel (source)` へ(cosmetic)。

Run: `uv run pytest tests/gui/test_channel_browser_view.py -v`
Expected: 新規3件 PASS・PC-20 sort 群無回帰・上記2件(反転/ skip)反映。

- [ ] **Step 5: 品質ゲート**

Run: `uv run pytest`; `uv run ruff check`; `uv run ruff format --check`; `uv run mypy src/`
Expected: 全通過。flat 前提の他テスト(test_dnd_workflow 等)が壊れたら Task 4 の範囲で是正(源キー解決を `signal_key_at` + `mapToSource` へ統一)。

- [ ] **Step 6: コミット**

```bash
git add src/valisync/gui/views/channel_browser_view.py tests/gui/test_channel_browser_view.py
git commit -m "feat(fu22b): ChannelBrowserView を SignalTreeModel(階層)へ差し替え + リーフパリティ"
```

---

### Task 5: proxy 撤去(model 直結・遅延保持)

> **改訂根拠(spec「実装後の実測知見」)**: QSortFilterProxyModel は reset マッピングで全 array 親の rowCount/hasChildren を source へ転送し `_materialize` を呼ぶ = 260k 子ノードを eager 構築(遅延/省メモリ破壊 + ~456ms)。proxy を撤去し model を tree 直結。sort(PC-20)は増分③で VM-side 化するため本増分では一時停止(sort テストは filter 同様 skip)。

**Files:**
- Modify: `src/valisync/gui/views/channel_browser_view.py`
- Modify test: `tests/gui/test_channel_browser_view.py`

**Interfaces:**
- Produces: `self.tree.model()` が `SignalTreeModel` 直結(proxy 無)。`selected_signal_keys()` は `self.tree.selectionModel().selectedRows(0)` の index を `self.model.signal_key_at(index)` で直接解決(mapToSource 不要)。`self.proxy` 属性は削除。

- [ ] **Step 1: 失敗テスト(proxy 非依存の掴み点)**

Task 4 で追加した3テストは `view.proxy` を使う。proxy 撤去後の掴み点(model index 直接)へ書き換え。まず現行(proxy 版)が撤去後に壊れることを RED で確認するため、以下へ更新:

```python
def test_view_uses_signal_tree_model(qtbot: QtBot, tmp_path: Path) -> None:
    from valisync.gui.adapters.signal_tree_model import SignalTreeModel

    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    assert isinstance(view.model, SignalTreeModel)
    assert not hasattr(view, "proxy")  # proxy 撤去(FU-22 B: 遅延保持)
    assert view.tree.model() is view.model  # model 直結
    top0 = view.model.index(0, 0, QModelIndex())
    assert view.model.rowCount(top0) >= 1  # array 親に子


def test_selected_leaf_resolves_source_key(qtbot: QtBot, tmp_path: Path) -> None:
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    model = view.model
    parent = model.index(0, 0, QModelIndex())  # array parent
    child = model.index(0, 0, parent)  # first leaf child (no proxy threading)
    view.tree.selectionModel().select(
        child,
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    keys = view.selected_signal_keys()
    assert len(keys) == 1 and keys[0].endswith("[0]")


def test_selecting_parent_yields_no_leaf_keys_in_incr1(qtbot: QtBot, tmp_path: Path) -> None:
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    parent = view.model.index(0, 0, QModelIndex())
    view.tree.selectionModel().select(
        parent,
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    assert view.selected_signal_keys() == []
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_channel_browser_view.py -k "tree_model or leaf_resolves or parent_yields" -v`
Expected: FAIL(`view.proxy` 依存の旧 view はまだ proxy を持つ / `hasattr(view,'proxy')` True)。

- [ ] **Step 3: 実装(proxy 撤去)**

`channel_browser_view.py`:
1. proxy 生成ブロックを削除(現行の `self.proxy = QSortFilterProxyModel(self)` + `setSourceModel` + `setSortCaseSensitivity` の3行と直前 PC-20 コメント)。
2. `self.tree.setModel(self.proxy)` -> `self.tree.setModel(self.model)`。
3. `self.tree.setSortingEnabled(True)` と `self.tree.sortByColumn(-1, ...)` の2行 + 直前コメントを削除(sort は増分③で VM-side)。
4. `selected_signal_keys()` を proxy 非依存へ:

```python
    def selected_signal_keys(self) -> list[str]:
        """Return the namespaced keys of the selected leaf rows.

        The tree is bound directly to SignalTreeModel (no proxy -- a proxy would
        eagerly materialize all array children on reset, defeating the lazy tree,
        see FU-22 B). So selection indexes are model indexes; resolve each key
        directly. Parent (array) nodes return None and are skipped (parent-as-signal
        lands in increment 4)."""
        keys: list[str] = []
        for index in self.tree.selectionModel().selectedRows(0):
            key = self.model.signal_key_at(index)
            if key is not None:
                keys.append(key)
        return keys
```

5. `from PySide6.QtCore import QSortFilterProxyModel` を削除(未使用化・ruff F401)。`Qt` は他で使うなら残す。

- [ ] **Step 4: PC-20 sort テストを skip(増分③まで)**

`tests/gui/test_channel_browser_view.py` の sort テスト5本(`test_default_order_is_source_order`・`test_header_click_sorts_by_name`・`test_selected_keys_correct_after_sort`・`test_dnd_mime_keys_correct_after_sort`・`test_sort_is_case_insensitive`)は `view.proxy` に依存。各関数の直前に:

```python
@pytest.mark.skip(reason="FU-22 B: sort moves VM-side in increment 3 (proxy dropped)")
```

`:311-317` 付近の proxy 説明コメントブロックも「増分③で VM-side sort に移行(proxy 撤去)」へ更新。

- [ ] **Step 5: GREEN + 品質ゲート**

Run: `uv run pytest tests/gui/test_channel_browser_view.py -v`(新規3 GREEN・sort 5本 skip)
Run: `uv run pytest`; `uv run ruff check`; `uv run ruff format --check`; `uv run mypy src/`
Expected: 全通過。他に `view.proxy` を参照する gui テストがあれば同様に model 直結へ是正(grep `\.proxy\b` in tests/gui)。

- [ ] **Step 6: コミット**

```bash
git add src/valisync/gui/views/channel_browser_view.py tests/gui/test_channel_browser_view.py
git commit -m "perf(fu22b): ChannelBrowser の proxy を撤去し model 直結(遅延保持・260k 子の eager 構築を根絶)"
```

---

### Task 6: header/empty を count-only 化(264k SignalItem build 撤去)

> **改訂根拠(spec「実装後の実測知見」)**: view `_refresh_state`->`header_text()`(`len(self.signals)`)/`empty_state()`(`if not self.signals`)が genuine switch ごとに 264k SignalItem を構築(~263ms)。カウントのみ必要なので `_prep` 長ベースの `shown_count()` に置換。

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`
- Test: `tests/gui/test_channel_browser_vm.py`

**Interfaces:**
- Produces: `ChannelBrowserVM.shown_count() -> int` = フィルタ後の表示件数を SignalItem 非構築で算出(`_prep` を走査)。`header_text()`/`empty_state()` が `self.signals` の代わりに `shown_count()` を使う(挙動不変・264k build 撤去)。

- [ ] **Step 1: 失敗テスト**

`tests/gui/test_channel_browser_vm.py` に追加:

```python
def test_shown_count_matches_signals_without_building_items(tmp_path: Path) -> None:
    """FU-22 B: shown_count は len(signals) と一致するが SignalItem を構築しない。"""
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    import numpy as np

    def _sig(name: str) -> Signal:
        return Signal(
            name=name, timestamps=np.array([0.0]), values=np.array([1.0]),
            file_format="MDF4", bus_type="", source_file="", metadata={"unit": "V"},
        )

    app_vm.session.group_signals = lambda k: [_sig("g::a"), _sig("g::b"), _sig("g::ab")]
    app_vm.set_active_file("g")

    assert vm.shown_count() == 3  # no filter -> total
    assert vm.shown_count() == len(vm.signals)
    vm.set_filter("a")
    assert vm.shown_count() == 2  # "a", "ab"
    assert vm.shown_count() == len(vm.signals)
    vm.set_filter("zzz")
    assert vm.shown_count() == 0
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py::test_shown_count_matches_signals_without_building_items -v`
Expected: FAIL(`shown_count` 未定義)。

- [ ] **Step 3: 実装**

`channel_browser_vm.py` に `shown_count()` を追加(`_filtered` の近く):

```python
    def shown_count(self) -> int:
        """Number of signals shown after the current filter, WITHOUT building
        SignalItems. header_text/empty_state need only the count; materializing
        264k SignalItems here was the residual ~263ms of the FU-22 B freeze."""
        self._ensure_prep()
        fl = self._filter_text.lower()
        if not fl:
            return len(self._prep)
        return sum(1 for _n, lo, _u, _k in self._prep if fl in lo)
```

`header_text()` の `len(self.signals)` を `self.shown_count()` へ:

```python
        return f"{name} — {total} ch 中 {self.shown_count()} 件表示"
```

`empty_state()` の `if not self.signals:` を `if self.shown_count() == 0:` へ:

```python
        if self.shown_count() == 0:
            return "no_match"
        return "has_rows"
```

(他は不変。`—` は既存の em-dash を踏襲。)

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py -v`(shown_count + 既存 header/empty テスト無回帰)
Expected: 全 PASS(header_text/empty_state の値は挙動不変)。

- [ ] **Step 5: 品質ゲート + コミット**

Run: `uv run pytest`; `uv run ruff check`; `uv run ruff format --check`; `uv run mypy src/`

```bash
git add src/valisync/gui/viewmodels/channel_browser_vm.py tests/gui/test_channel_browser_vm.py
git commit -m "perf(fu22b): header/empty を shown_count で count-only 化(264k SignalItem build を撤去)"
```

---

### Task 7: realgui パリティ + prod 実測(5s->~400ms)= メインセッション駆動

> realgui は実ディスプレイ + スクショ AI 判定 + prod_demo.mf4 が必須でサブエージェント不可。gui-verify ①ゲートと同扱い。

**Files:**
- Modify(必要時): `tests/realgui/test_channel_browser_realclick.py`・`tests/realgui/test_signal_dnd_realclick.py`(stale コメント/掴み点)
- Scratch(非コミット): prod repro

**Interfaces:**
- Consumes: proxy 撤去済 view。realgui 掴み点は `browser.tree.model().index(row, 0)`(top-level スカラー)/`model.index(childRow, 0, parentIndex)`(配列子・親展開後)。`browser.proxy` は存在しない。

- [ ] **Step 1: realgui 掴み点を proxy 非依存へ**

`test_signal_dnd_realclick.py`/`test_channel_browser_realclick.py` は CSV スカラー(`a`/`b`)を使い `browser.proxy.index(0,0)`/`browser.model.index(r,0)` で top-level を掴む。proxy 撤去後は `browser.proxy` が無いので `browser.tree.model().index(row,0)` か `browser.model.index(row,0)` へ。スカラーは top-level リーフのため親スレッド不要。stale コメント `browser.model is SignalTableModel` を `SignalTreeModel` へ。

- [ ] **Step 2: realgui クラスタ実行(実ディスプレイ)**

Run: `uv run pytest --realgui tests/realgui/test_signal_dnd_realclick.py tests/realgui/test_channel_browser_realclick.py tests/realgui/test_journey_smoke.py tests/realgui/test_active_panel_flow.py tests/realgui/test_panel_source_flow.py -v`
Expected: 全 PASS(選択/D&D/追加が proxy 非依存の階層 view で無回帰)。スクショ目視添付。

- [ ] **Step 3: prod 実測(主症状解消の記録)**

scratchpad の `repro_fu22b_incr1.py` 等を proxy 撤去 + shown_count 後の実コードで再走。
Expected: genuine file 選択 5,027ms -> **~400ms 以下**・materialized=0(遅延保持)。数値を spec/catalog に記録(コミットしない)。

- [ ] **Step 4: realgui コミット(あれば)**

```bash
git add tests/realgui/test_signal_dnd_realclick.py tests/realgui/test_channel_browser_realclick.py
git commit -m "test(fu22b): realgui 掴み点を proxy 非依存へ + 階層 view パリティ無回帰"
```

増分①はここで review チェックポイント。**merge はしない**(②③④ でパリティ復旧後)。

---

## Self-Review

- **Spec coverage**: 増分①(モデル + VM グルーピング + view 差し替え + 展開/折畳 + リーフパリティ + grab-point + **proxy 撤去(遅延保持)** + **header/empty count-only**) = Task 1-7。フィルタ②/sort③(VM-side)/親D&D④/磨き⑤は本プラン対象外(後続プラン)。
- **Placeholder scan**: 全 step に実コード/実コマンド。
- **Type consistency**: `SignalTreeModel(vm)`・`signal_key_at(index) -> str | None`・`tree_groups() -> list[tuple[str, list[tuple[str,str,str]]]]`・`shown_count() -> int`・`_base_of(orig)` は Task 間で一致。`_Node.key is None` が親/リーフ判定の単一規約。proxy 撤去後は `self.tree.model()` が SignalTreeModel 直結で selection index = model index。
