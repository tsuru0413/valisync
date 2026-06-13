import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from valisync.gui.views.region_divider_item import RegionDividerItem
from unittest.mock import MagicMock

class MockVM:
    def __init__(self):
        self.resize_axis = MagicMock()

class MockEvent:
    def __init__(self, pos, last_pos, is_start=False, is_finish=False):
        self._pos = pos
        self._last_pos = last_pos
        self._is_start = is_start
        self._is_finish = is_finish
        self.accepted = False

    def pos(self): return self._pos
    def lastPos(self): return self._last_pos
    def isStart(self): return self._is_start
    def isFinish(self): return self._is_finish
    def button(self): return Qt.MouseButton.LeftButton
    def accept(self): self.accepted = True
    def ignore(self): self.accepted = False

def test_region_divider_item_instantiation():
    vm = MockVM()
    divider = RegionDividerItem(vm=vm, axis_index=0)
    assert divider.axis_index == 0
    assert divider.vm == vm

def test_region_divider_item_drag(qtbot):
    vm = MockVM()
    divider = RegionDividerItem(vm=vm, axis_index=0)
    
    # Mock getViewWidget to return a mock widget with height
    mock_view = MagicMock()
    mock_view.height.return_value = 1000
    divider.getViewWidget = MagicMock(return_value=mock_view)
    
    # Start drag
    ev_start = MockEvent(QPointF(0, 100), QPointF(0, 100), is_start=True)
    divider.mouseDragEvent(ev_start)
    assert ev_start.accepted
    vm.resize_axis.assert_not_called()
    
    # Drag move
    ev_move = MockEvent(QPointF(0, 110), QPointF(0, 100))
    divider.mouseDragEvent(ev_move)
    assert ev_move.accepted
    # delta_y is 10, height is 1000, so delta_ratio is 0.01
    vm.resize_axis.assert_called_once_with(0, pytest.approx(0.01))
    
    # Finish drag
    ev_finish = MockEvent(QPointF(0, 110), QPointF(0, 110), is_finish=True)
    divider.mouseDragEvent(ev_finish)
    assert ev_finish.accepted
