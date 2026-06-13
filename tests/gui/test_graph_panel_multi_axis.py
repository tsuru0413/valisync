"""Tests for Task 4: Drag & Drop Integration.

Verify that dropping signals on different zones of the GraphPanelView results
in different outcomes:
- Dropping on the plot area creates a NEW axis for each signal.
- Dropping on a Y-axis adds the signal to THAT specific axis.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDropEvent
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.adapters.qt_signal_models import encode_signal_keys
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from tests.gui.test_graph_panel_view import _loaded_session, _keys, _make_view

class TestContextualDrop:
    def test_drop_on_plot_creates_new_axis(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        
        # Force ZONE_PLOT
        view._zone_at = lambda pos: "plot" # type: ignore
        
        mime = encode_signal_keys([key])
        event = QDropEvent(
            QPointF(100.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dropEvent(event)
        
        # Initial 1 axis + 1 new axis = 2
        assert len(vm.axes) == 2
        plotted = vm.inspect()["plotted_signals"]
        assert plotted[0]["signal_key"] == key
        assert plotted[0]["axis_index"] == 1
        
        # Verify ratios (equally split 1.0 / 2 = 0.5)
        assert vm.axes[0].height_ratio == 0.5
        assert vm.axes[1].height_ratio == 0.5
        assert vm.axes[1].top_ratio == 0.5

    def test_drop_on_y_axis_joins_that_axis(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        
        # Force ZONE_Y_INNER and axis index 0
        view._zone_at = lambda pos: "y_inner" # type: ignore
        view._axis_index_at = lambda pos: 0 # type: ignore
        
        mime = encode_signal_keys([key])
        event = QDropEvent(
            QPointF(10.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dropEvent(event)
        
        # Still 1 axis
        assert len(vm.axes) == 1
        plotted = vm.inspect()["plotted_signals"]
        assert plotted[0]["signal_key"] == key
        assert plotted[0]["axis_index"] == 0

    def test_drop_multiple_signals_on_plot_creates_multiple_axes(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=2)
        k0, k1 = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        
        # Force ZONE_PLOT
        view._zone_at = lambda pos: "plot" # type: ignore
        
        mime = encode_signal_keys([k0, k1])
        event = QDropEvent(
            QPointF(100.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dropEvent(event)
        
        # Initial 1 axis + 2 new axes = 3
        assert len(vm.axes) == 3
        plotted = vm.inspect()["plotted_signals"]
        assert plotted[0]["axis_index"] == 1
        assert plotted[1]["axis_index"] == 2
        
        # Verify ratios (1/3 = 0.333...)
        for ax in vm.axes:
            assert abs(ax.height_ratio - 1.0/3.0) < 1e-6

class TestAxisResizing:
    def test_resize_axis_updates_ratios(self, tmp_path: Path) -> None:
        from valisync.core.session import Session
        session = Session()
        vm = GraphPanelVM(session)
        # Create 2 axes (0.5 each)
        vm.create_new_axis("sig1")
        assert len(vm.axes) == 2
        
        # Move divider 0 down by 0.1
        vm.resize_axis(0, 0.1)
        
        assert vm.axes[0].height_ratio == pytest.approx(0.6)
        assert vm.axes[1].top_ratio == pytest.approx(0.6)
        assert vm.axes[1].height_ratio == pytest.approx(0.4)

    def test_resize_axis_respects_minimum_height(self, tmp_path: Path) -> None:
        from valisync.core.session import Session
        session = Session()
        vm = GraphPanelVM(session)
        vm.create_new_axis("sig1")
        
        # Try to move divider 0 down so much that below axis disappears
        vm.resize_axis(0, 0.6) # 0.5 + 0.6 = 1.1 (invalid, should cap)
        
        # Min height is 0.05
        assert vm.axes[1].height_ratio == pytest.approx(0.05)
        assert vm.axes[0].height_ratio == pytest.approx(0.95)
