# Implementation Tasks: valisync-gui-axes

These tasks define the implementation sequence for the advanced Multi-Y axis layout with vertical regions and auto-fit scaling.

## Wave 0: ViewModel Core Expansion
Refactor the state management to support multiple axes.

- [x] Task 0.1: Implement `YAxisVM` class (Observable) to hold range, top_ratio, height_ratio, column, and unit.
- [x] Task 0.2: Refactor `GraphPanelVM` to replace the single `y_range` with a `list[YAxisVM]`.
- [x] Task 0.3: Implement the "Auto-Fit" coordinate mapping logic in the ViewModel layer.
  - [x] **Red**: Add test in `tests/gui/test_graph_panel_vm.py` verifying raw-to-pixel mapping factors for various ratios.
  - [x] **Green**: Implement mapping calculations.

## Wave 1: Custom UI Components
Build the draggable dividers and specialized AxisItems.

- [x] Task 1.1: Create `RegionDividerItem` (a GraphicsObject) that provides a draggable horizontal line.
- [x] Task 1.2: Implement `AxisColumnLayout` (Nested `GraphicsLayout`) to manage a vertical stack of `AxisItem`s and dividers.
- [x] Task 1.3: Verify Real-time Ratio Updating.
  - [x] **Red**: Add test verifying that dragging a `RegionDividerItem` updates the `height_ratio` of adjacent `YAxisVM`s.
  - [x] **Green**: Wire mouse events to ViewModel updates.

## Wave 2: Multi-ViewBox Overlay & Transformation
Implement the core rendering logic.

- [x] Task 2.1: Modify `GraphPanelView` to instantiate and overlay multiple `ViewBox`es based on the `GraphPanelVM.axes` list.
- [x] Task 2.2: Apply the "Vertical Transform" (virtual range calculation) to each `ViewBox` to map it to its Home Region.
- [x] Task 2.3: Ensure X-axis synchronization (setXLink) across all overlaid ViewBoxes.
- [x] Task 2.4: Disable clipping (`setClipToView(False)`) to allow waveforms to draw across the entire panel.

## Wave 3: Drag & Drop Integration
Finalize the contextual signal addition logic.

- [x] Task 3.1: Implement Drop Zone logic in `AxisItem` (Join Axis).
- [x] Task 3.2: Implement Drop Zone logic in plot area (New Region).
- [ ] Task 3.3: Final E2E Verification.
  - [ ] **Verify**: Run `uv run valisync`, drag multiple signals with different units, adjust their heights, and verify auto-fit scaling and unclipped rendering.

---

### Task Dependency Graph
```json
{
  "tasks": [
    { "id": "0.1", "desc": "YAxisVM", "deps": [] },
    { "id": "0.2", "desc": "Refactor GraphPanelVM", "deps": ["0.1"] },
    { "id": "0.3", "desc": "Auto-Fit Logic", "deps": ["0.2"] },
    { "id": "1.1", "desc": "RegionDividerItem", "deps": [] },
    { "id": "1.2", "desc": "AxisColumnLayout", "deps": ["1.1"] },
    { "id": "1.3", "desc": "Ratio Interaction", "deps": ["1.2", "0.3"] },
    { "id": "2.1", "desc": "Multi-ViewBox Overlay", "deps": ["0.3"] },
    { "id": "2.2", "desc": "Vertical Transform Mapping", "deps": ["2.1"] },
    { "id": "2.3", "desc": "X-Link Sync", "deps": ["2.1"] },
    { "id": "2.4", "desc": "Non-Clipped Rendering", "deps": ["2.1"] },
    { "id": "3.1", "desc": "D&D to Axis", "deps": ["1.2"] },
    { "id": "3.2", "desc": "D&D to Plot", "deps": ["2.1"] },
    { "id": "3.3", "desc": "Final E2E", "deps": ["3.1", "3.2", "2.2", "2.3", "2.4", "1.3"] }
  ]
}
```
