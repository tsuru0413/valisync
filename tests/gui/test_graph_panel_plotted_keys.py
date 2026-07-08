from __future__ import annotations

from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


def test_plotted_signal_keys_order_preserving_dedup() -> None:
    vm = GraphPanelVM(Session())
    vm.add_signal("csv_1::a")
    vm.add_signal("csv_1::b")
    vm.add_signal_to_axis("csv_1::a", 0)  # duplicate key in different operation
    assert vm.plotted_signal_keys() == ["csv_1::a", "csv_1::b"]


def test_plotted_signal_keys_empty() -> None:
    assert GraphPanelVM(Session()).plotted_signal_keys() == []
