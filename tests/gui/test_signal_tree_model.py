"""Tests for SignalTreeModel (FU-22 B): hierarchical lazy tree over base channels."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from valisync.core.models import Signal
from valisync.gui.adapters.qt_signal_models import decode_signal_keys
from valisync.gui.adapters.signal_tree_model import SignalTreeModel
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM


def _sig(name: str) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={"unit": "V"},
    )


def _model(qtbot: QtBot) -> SignalTreeModel:
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    app_vm.session.group_signals = lambda key: [
        _sig("g::Arr[0]"),
        _sig("g::Arr[1]"),
        _sig("g::Arr[2]"),
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
    app_vm.session.group_signals = lambda k: [
        _sig("g::Zeta"),
        _sig("g::alpha"),
        _sig("g::Mid"),
        _sig("g::Arr[2]"),
        _sig("g::Arr[0]"),
        _sig("g::Arr[1]"),
    ]
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
