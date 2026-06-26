# Multi-Axis Layout Bug Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the X-axis disappearing bug and restore missing Y-axis unit labels in the multi-axis layout.

**Architecture:** 
1. **Layout**: Restructure `GraphPanelView` to use a hierarchical `GraphicsLayout`. The root layout will be a 2x2 grid where the X-axis is isolated in a row independent of the Y-axis row stacking.
2. **Units**: Update `GraphPanelVM` to extract unit metadata from signals and assign it to the corresponding `YAxisVM`.

**Tech Stack:** Python, PySide6, PyQtGraph

---

### Task 5: Layout Restructuring and Unit Restoration

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- Modify: `src/valisync/gui/views/graph_panel_view.py`
- Modify: `tests/gui/test_graph_panel_multi_axis.py`

- [ ] **Step 1: Write the failing tests**
Update `test_graph_panel_multi_axis.py` to verify that the X-axis is not crushed and Y-axis units are correctly displayed.

```python
# In tests/gui/test_graph_panel_multi_axis.py

def test_x_axis_is_not_crushed_with_many_y_axes(qtbot, tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    view = _make_view(qtbot, vm)
    
    # Add many axes
    for i in range(5):
        vm.create_new_axis(_keys(session)[0])
        
    view.resize(800, 600)
    # X-axis should have a non-zero height in widget coordinates
    assert view._x_axis.boundingRect().height() > 10

def test_y_axis_displays_unit_from_metadata(qtbot, tmp_path):
    session, _ = _loaded_session(tmp_path)
    # Mock unit in metadata
    sig = session.signals()[0]
    sig.metadata["unit"] = "V"
    
    vm = GraphPanelVM(session)
    view = _make_view(qtbot, vm)
    vm.add_signal(sig.name)
    
    # Axis label should contain the unit
    assert "V" in view._y_axes[0].label.toPlainText()
```

- [ ] **Step 2: Implement Unit Propagation in VM**
Modify `GraphPanelVM.add_signal_to_axis` to extract the `unit` from signal metadata.

```python
# In src/valisync/gui/viewmodels/graph_panel_vm.py

def add_signal_to_axis(self, signal_key: str, axis_index: int) -> None:
    # ... existing plotted append ...
    if 0 <= axis_index < len(self._axes):
        axis = self._axes[axis_index]
        sig = self._signal_map().get(signal_key)
        if sig and sig.metadata and (unit := sig.metadata.get("unit")):
            axis.unit = str(unit)
    # ... notify ...
```

- [ ] **Step 3: Implement Nested Layout in View**
Refactor `_reconcile_axes` to create a dedicated `axis_layout` for Y-axes and place the X-axis in a separate root row.

```python
# In src/valisync/gui/views/graph_panel_view.py

def _reconcile_axes(self):
    self.plot_widget.ci.clear()
    # Root: Col 0 = Y-Axes, Col 1 = Plot/X-Axis
    # Row 0 = Top, Row 1 = Bottom (X-axis)
    
    # Create nested layout for Y-axes in Col 0
    self._axis_layout = self.plot_widget.addLayout(row=0, col=0)
    self._axis_layout.setColumnFixedWidth(0, 60)
    
    # ... create ViewBoxes and AxisItems ...
    # Add AxisItem to self._axis_layout instead of plot_widget
    
    # Add X-axis to the root layout Row 1, Col 1
    self.plot_widget.addItem(self._x_axis, row=1, col=1)
```

- [ ] **Step 4: Verify and Commit**
Run all tests and verify visually.
