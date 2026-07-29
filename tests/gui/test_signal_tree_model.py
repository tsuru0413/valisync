"""Tests for SignalTreeModel (FU-22 B): hierarchical lazy tree over base channels."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from tests.gui._physical_fixtures import inject_physical_channels
from valisync.gui.adapters.qt_signal_models import decode_signal_keys
from valisync.gui.adapters.signal_tree_model import SignalTreeModel
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM


def _model(qtbot: QtBot) -> SignalTreeModel:
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    inject_physical_channels(
        app_vm,
        "g",
        [("Arr", "V", ("Arr[0]", "Arr[1]", "Arr[2]")), ("Scalar", "V", ("Scalar",))],
    )
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


def _sort_model(qtbot: QtBot) -> SignalTreeModel:
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    # 列順は未ソートのまま (Arr[2], Arr[0], Arr[1]) = 子ソートの母数
    inject_physical_channels(
        app_vm,
        "g",
        [
            ("Zeta", "V", ("Zeta",)),
            ("alpha", "V", ("alpha",)),
            ("Mid", "V", ("Mid",)),
            ("Arr", "V", ("Arr[2]", "Arr[0]", "Arr[1]")),
        ],
    )
    app_vm.set_active_file("g")
    return SignalTreeModel(vm)


def _top_names(m: SignalTreeModel) -> list[str]:
    return [
        m.data(m.index(r, 0, QModelIndex()), Qt.ItemDataRole.DisplayRole)
        for r in range(m.rowCount(QModelIndex()))
    ]


def test_sort_top_level_case_insensitive_ascending(qtbot: QtBot) -> None:
    m = _sort_model(qtbot)
    # session order: Zeta, alpha, Mid, Arr (Arr is a parent grouping the 3 leaves)
    m.sort(0, Qt.SortOrder.AscendingOrder)
    # case-insensitive A-Z: alpha, Arr, Mid, Zeta
    assert _top_names(m) == ["alpha", "Arr", "Mid", "Zeta"]


def test_sort_top_level_descending(qtbot: QtBot) -> None:
    m = _sort_model(qtbot)
    m.sort(0, Qt.SortOrder.DescendingOrder)
    assert _top_names(m) == ["Zeta", "Mid", "Arr", "alpha"]


def test_sort_does_not_materialize_children(qtbot: QtBot) -> None:
    """FU-22 B lazy invariant: sort must not build children of an unexpanded
    parent (that is the exact laziness the dropped proxy defeated)."""
    m = _sort_model(qtbot)
    m.sort(0, Qt.SortOrder.AscendingOrder)
    parents = [n for n in m._top if n.key is None]
    assert parents and all(n.children is None for n in parents)  # materialized 0


def test_sort_row_reassigned_parent_round_trip(qtbot: QtBot) -> None:
    """node.row is reassigned after sort so parent()/index() round-trip holds."""
    m = _sort_model(qtbot)
    m.sort(0, Qt.SortOrder.AscendingOrder)
    for r in range(m.rowCount(QModelIndex())):
        idx = m.index(r, 0, QModelIndex())
        assert idx.row() == r
        assert m.parent(idx) == QModelIndex()
    # child round-trip after materialize (Arr is at sorted row 1)
    arr = m.index(1, 0, QModelIndex())
    assert m.data(arr, Qt.ItemDataRole.DisplayRole) == "Arr"
    child = m.index(0, 0, arr)
    assert m.parent(child) == arr


def test_children_sorted_on_materialize(qtbot: QtBot) -> None:
    """Materializing after a sort orders children too (Arr[2],Arr[0],Arr[1] ->
    Arr[0],Arr[1],Arr[2])."""
    m = _sort_model(qtbot)
    m.sort(0, Qt.SortOrder.AscendingOrder)
    arr = m.index(1, 0, QModelIndex())  # Arr after sort
    names = [
        m.data(m.index(r, 0, arr), Qt.ItemDataRole.DisplayRole)
        for r in range(m.rowCount(arr))
    ]
    assert names == ["Arr[0]", "Arr[1]", "Arr[2]"]


def test_sort_preserved_across_filter(qtbot: QtBot) -> None:
    """Sort state survives a filter-triggered rebuild."""
    m = _sort_model(qtbot)
    m.sort(0, Qt.SortOrder.DescendingOrder)
    m._vm.set_filter("a")  # notify 'filter' -> _rebuild
    # 'a' matches alpha and Arr[*] (Arr base is prefix). Desc order among survivors.
    names = _top_names(m)
    assert names == sorted(names, key=str.lower, reverse=True)


def test_filter_narrows_row_to_single_column_stays_draggable_leaf(
    qtbot: QtBot,
) -> None:
    """C1 model half: a row the filter narrows down to exactly one matching
    column must stay a leaf carrying that column's real identity, not collapse
    to a non-draggable parent.

    Without a filter, ``single is not None`` and ``_count == 1`` coincide (every
    unfiltered test is blind to the difference). Filtering "arr[1]" against the
    Arr[0]/Arr[1]/Arr[2] fixture keeps the real column count at 3 while exactly
    one column (Arr[1]) survives -- the only way to tell the two conditions
    apart. Sabotage: branch _rebuild()'s leaf/parent decision on ``_count == 1``
    instead of ``single is not None`` and this goes RED (see
    .superpowers/sdd/e2-task-3-report.md for the recorded RED/GREEN pair).
    """
    m = _model(qtbot)
    m._vm.set_filter("arr[1]")  # only Arr[1] matches; Arr[0]/Arr[2]/Scalar don't
    assert m.rowCount(QModelIndex()) == 1
    row = m.index(0, 0, QModelIndex())
    assert m.hasChildren(row) is False
    assert m.signal_key_at(row) == "g::Arr[1]"
    assert m.data(row, Qt.ItemDataRole.DisplayRole) == "Arr[1]"
    assert m.flags(row) & Qt.ItemFlag.ItemIsDragEnabled


# ─── E-2: 1 行 = 1 物理チャンネル / 子は要求時合成 ─────────────────────────────
# 実 mf4 経由 (合成 Signal では physical_channel の実 fallback を踏めない)。


def _vm_from_mf4(path: Path) -> ChannelBrowserVM:
    app_vm = AppViewModel()
    key = app_vm.request_load(path)  # MDF4 は format_def 不要
    app_vm.set_active_file(key)
    return ChannelBrowserVM(app_vm)


def _vm_with_array_channel(tmp_path: Path) -> ChannelBrowserVM:
    from tests.mdf4_helpers import write_mdf4_2d

    return _vm_from_mf4(write_mdf4_2d(tmp_path))  # Mat 3 列 + Clean 1 列


def test_top_level_rows_are_physical_channels(qtbot: QtBot, tmp_path: Path) -> None:
    # 1 行 = 1 物理チャンネル。配列チャンネルは 1 行で、展開して初めて列が出る。
    vm = _vm_with_array_channel(tmp_path)
    model = SignalTreeModel(vm)
    tops = [model.index(r, 0).data() for r in range(model.rowCount())]
    assert tops == ["Mat", "Clean"]
    assert not any(str(t).startswith("Mat[") for t in tops)


def test_children_are_synthesized_on_demand(qtbot: QtBot, tmp_path: Path) -> None:
    vm = _vm_with_array_channel(tmp_path)
    model = SignalTreeModel(vm)
    row = next(r for r in range(model.rowCount()) if model.index(r, 0).data() == "Mat")
    parent = model.index(row, 0)
    node = parent.internalPointer()
    assert node.children is None  # 要求されるまで作らない
    assert model.hasChildren(parent) is True  # 合成せずに親と判る
    assert model.rowCount(parent) == 3  # ここで初めて合成される
    assert model.index(0, 0, parent).data() == "Mat[0]"


def test_scalar_channel_has_no_children(qtbot: QtBot, tmp_path: Path) -> None:
    vm = _vm_with_array_channel(tmp_path)
    model = SignalTreeModel(vm)
    row = next(
        r for r in range(model.rowCount()) if model.index(r, 0).data() == "Clean"
    )
    assert model.hasChildren(model.index(row, 0)) is False


def test_parent_row_unit_cell_is_blank(qtbot: QtBot, tmp_path: Path) -> None:
    """m2: 親行の Unit は "" のまま (UX-29 — 親は空・実体は子)。"""
    vm = _vm_with_array_channel(tmp_path)
    model = SignalTreeModel(vm)
    row = next(r for r in range(model.rowCount()) if model.index(r, 0).data() == "Mat")
    assert model.index(row, 1).data() == ""


def test_single_column_channels_are_draggable_leaves(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """C1: (N,1) 2D / 単一フィールド構造化 / 混在構造化 は列 1 本の **葉**。

    表示名も key も実列のもの (Mono[0] / P.x / Q.x)。sabotage: key を base_key に
    戻す・表示名を physical_name に戻すと 3 本とも RED になる。
    """
    from tests.mdf4_helpers import write_mdf4_single_column_shapes

    vm = _vm_from_mf4(write_mdf4_single_column_shapes(tmp_path))
    model = SignalTreeModel(vm)
    tops = [model.index(r, 0).data() for r in range(model.rowCount())]
    assert tops == ["Mono[0]", "P.x", "Q.x", "Clean"]
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        assert model.hasChildren(idx) is False
        assert model.signal_key_at(idx) == f"mf4_1::{tops[r]}"
        assert model.flags(idx) & Qt.ItemFlag.ItemIsDragEnabled


def test_every_signal_key_in_the_tree_resolves(qtbot: QtBot, tmp_path: Path) -> None:
    """恒久ガード (E-3 の鋳造書き換えでも生き残る): モデルが出す全キーが解決する。

    トップレベル全行と展開済み全子を歩き、signal_key_at が None でない全キーが
    session.signal_map() で解決することを assert する。
    """
    from tests.mdf4_helpers import write_mdf4_single_column_shapes

    app_vm = AppViewModel()
    key = app_vm.request_load(write_mdf4_single_column_shapes(tmp_path))
    app_vm.set_active_file(key)
    model = SignalTreeModel(ChannelBrowserVM(app_vm))
    sig_map = app_vm.session.signal_map()

    def walk(parent: QModelIndex) -> None:
        for r in range(model.rowCount(parent)):
            idx = model.index(r, 0, parent)
            k = model.signal_key_at(idx)
            if k is not None:
                assert sig_map.get(k) is not None, f"dead key in tree: {k!r}"
            else:
                walk(idx)  # 親は必ず展開して子まで検査する

    walk(QModelIndex())
