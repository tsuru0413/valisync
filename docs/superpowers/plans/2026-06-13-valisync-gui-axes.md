# Multi-Axis Layout - Task 2: Custom UI Components (Dividers and Layouts)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement visual components for multi-axis support, including draggable dividers and a layout that handles multiple stacked axes per column.

**Architecture:**
- `RegionDividerItem`: A `pg.GraphicsObject` representing a draggable horizontal divider.
- `GraphPanelVM`: Enhanced to handle axis resizing and curve-to-axis mapping.
- `GraphPanelView`: Refactored to use `pg.GraphicsLayoutWidget` and manage multiple `ViewBox`es and `AxisItem`s.

**Tech Stack:** PySide6, pyqtgraph, NumPy.

---

### Task 1: Update ViewModel for Multi-Axis Resizing

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- Test: `tests/gui/test_graph_panel_vm.py`

- [ ] **Step 1: Update RenderCurve to include axis_index**
Modify `RenderCurve` dataclass to include `axis_index: int`. Update `render_data` to populate it from `_PlottedEntry`.

```python
# In src/valisync/gui/viewmodels/graph_panel_vm.py

@dataclass
class RenderCurve:
    name: str
    color: str
    timestamps: np.ndarray
    values: np.ndarray
    axis_index: int  # Added

# In render_data loop:
curves.append(
    RenderCurve(
        name=entry.signal_key,
        color=entry.color,
        timestamps=out_ts,
        values=out_vs,
        axis_index=entry.axis_index,  # Added
    )
)
```

- [ ] **Step 2: Add resize_axis method to GraphPanelVM**
Implement `resize_axis(divider_index, delta_ratio)` which updates the `height_ratio` and `top_ratio` of adjacent axes.

```python
# In src/valisync/gui/viewmodels/graph_panel_vm.py

    def resize_axis(self, divider_index: int, delta_ratio: float) -> None:
        """Resize two adjacent axes by moving the divider between them.
        
        divider_index 0 is between axis 0 and 1.
        delta_ratio is positive for moving the divider down.
        """
        if divider_index < 0 or divider_index >= len(self._axes) - 1:
            return
            
        above = self._axes[divider_index]
        below = self._axes[divider_index + 1]
        
        # Ensure minimum height (e.g., 5%)
        min_h = 0.05
        if above.height_ratio + delta_ratio < min_h:
            delta_ratio = min_h - above.height_ratio
        if below.height_ratio - delta_ratio < min_h:
            delta_ratio = below.height_ratio - min_h
            
        above.height_ratio += delta_ratio
        below.top_ratio += delta_ratio
        below.height_ratio -= delta_ratio
        
        self._notify("axes")
```

- [ ] **Step 3: Write tests for resizing**
In `tests/gui/test_graph_panel_vm.py`, add a test that verifies `resize_axis` correctly updates ratios.

```python
def test_resize_axis(session):
    vm = GraphPanelVM(session)
    # Add a second axis
    from valisync.gui.viewmodels.y_axis_vm import YAxisVM
    vm.axes.append(YAxisVM(top_ratio=0.5, height_ratio=0.5))
    vm.axes[0].height_ratio = 0.5
    
    vm.resize_axis(0, 0.1)
    
    assert vm.axes[0].height_ratio == 0.6
    assert vm.axes[1].top_ratio == 0.6
    assert vm.axes[1].height_ratio == 0.4
```

- [ ] **Step 4: Run tests and commit**

### Task 2: Implement RegionDividerItem

**Files:**
- Create: `src/valisync/gui/views/region_divider_item.py`
- Test: `tests/gui/test_region_divider_item.py`

- [ ] **Step 1: Implement RegionDividerItem**
Inherit from `pg.GraphicsObject`. Implement drawing a horizontal line and handling mouse drag events.

```python
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPen, QColor

class RegionDividerItem(pg.GraphicsObject):
    sigDragged = Signal(float)  # Emits delta_y in pixels or normalized? 
    # Let's emit delta in pixels and let the view convert to ratio.

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pen = QPen(QColor(150, 150, 150), 1)
        self.hover_pen = QPen(QColor(255, 255, 0), 2)
        self._hovering = False
        self.setAcceptHoverEvents(True)

    def boundingRect(self):
        return QRectF(-10000, -5, 20000, 10)

    def paint(self, p, *args):
        p.setPen(self.hover_pen if self._hovering else self.pen)
        p.drawLine(-10000, 0, 10000, 0)

    def hoverEnterEvent(self, ev):
        self._hovering = True
        self.update()
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def hoverLeaveEvent(self, ev):
        self._hovering = False
        self.update()
        self.unsetCursor()

    def mouseDragEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        
        if ev.isStart():
            ev.accept()
        elif ev.isFinish():
            pass
        else:
            delta = ev.pos() - ev.lastPos()
            self.sigDragged.emit(delta.y())
            ev.accept()
```

- [ ] **Step 2: Write a smoke test for RegionDividerItem**
Since it's a GUI component, we'll mostly test its existence and signal.

- [ ] **Step 3: Commit**

### Task 3: Refactor GraphPanelView for Multi-Axis Layout

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`

- [ ] **Step 1: Switch to GraphicsLayoutWidget**
Change `self.plot_widget = pg.PlotWidget()` to `self.plot_widget = pg.GraphicsLayoutWidget()`.

- [ ] **Step 2: Implement Multi-Axis Layout Logic**
Update `refresh` to create/reconcile multiple `ViewBox`es based on `vm.axes`. Link their X axes.
Use a `pg.GraphicsLayout` to stack them.

```python
# In GraphPanelView.refresh:
# 1. Clear current layout
# 2. For each YAxisVM in vm.axes:
#    - Create/Reuse a ViewBox (and AxisItem)
#    - Add to layout at (row, 0)
#    - Link X axis to first ViewBox
#    - Set row stretch factor based on YAxisVM.height_ratio
# 3. For each RenderCurve:
#    - Add to the corresponding ViewBox
```

Wait, `pyqtgraph.GraphicsLayout` doesn't support floating-point row stretches natively in a simple way if we want to change them dynamically with dividers. 
Actually, we can use `layout.layout.setRowStretch(row, int(ratio * 1000))`.

- [ ] **Step 3: Wire Dividers to VM**
Add `RegionDividerItem`s between `ViewBox`es in the layout.
Connect `divider.sigDragged` to a handler that calls `vm.resize_axis`.

- [ ] **Step 4: Update Interaction Logic**
The current `classify_zone` logic assumes one plot area. It needs to be updated or replaced to handle multiple `ViewBox`es.
Actually, if each `ViewBox` handles its own events (or we delegate), it might be simpler.
But the "zone" model (inner/outer) is nice. We might need to map the global `pos` to the specific `ViewBox` it's over.

- [ ] **Step 5: Verify and Commit**

---
