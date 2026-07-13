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
