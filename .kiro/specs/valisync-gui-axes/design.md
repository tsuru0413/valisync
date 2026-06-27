# Design Document: valisync-gui-axes

## Architecture

This sub-spec introduces a "Region-based Overlay" architecture using multiple `pyqtgraph.ViewBox` and `pyqtgraph.AxisItem` objects within nested `GraphicsLayout` structures.

### Component Interaction

```mermaid
graph TD
    subgraph View (PyQtGraph)
        G_Widget[GraphicsLayoutWidget]
        Root_Layout[Root Grid Layout]
        Col_Layouts["_axis_layouts: dict[col → GraphicsLayout]"]
        Main_VB[Overlaid ViewBoxes]
        Axis_Item[AxisItems]
        
        G_Widget --> Root_Layout
        Root_Layout --> Col_Layouts
        Col_Layouts --> Axis_Item
        Root_Layout --> Main_VB
    end
    subgraph ViewModel
        GP_VM[GraphPanelVM]
        Y_VM[YAxisVM]
        
        GP_VM --> Y_VM
    end
```

## ViewModels

### YAxisVM (New)
**Role:** Manages the state of a single Y-axis and its assigned vertical region.
- **Properties:**
  - `range: tuple[float, float]`: The current value range displayed (e.g., 0.0 to 120.0).
  - `top_ratio: float`: The vertical start position as a percentage (0.0 = top of panel).
  - `height_ratio: float`: The vertical height as a percentage (1.0 = full height).
  - `column: int`: The grid column index.
  - `unit: str`: The physical unit of associated signals.
  - `signal_keys: list[str]`: List of namespaced signal keys mapped to this axis.

### GraphPanelVM (Refactor)
- **State Change:** Replaces `y_range` with `axes: list[YAxisVM]`.
- **Logic:**
  - Performs "Auto-Fit" calculations: converts a signal's raw value to a vertically shifted/scaled value based on its `YAxisVM` ratios.
  - Coordinates X-axis synchronization across all ViewBoxes.

## Views

### Layout Structure
- **Root Layout**: A single row, N+1 columns grid where N = `column_count` (default **2**, per-panel, set via `GraphPanelVM.set_column_count(n)`; clamps ≥ 1). The wave plot area is placed at root col = `column_count` (always the rightmost slot).
- **Per-Column Sub-Layouts** (`_axis_layouts: dict[int, GraphicsLayout]`): One `pyqtgraph.GraphicsLayout` per *occupied* column, keyed by column index, placed at root grid col = column index. Columns that have no axes are not added to `_axis_layouts` but still hold a fixed-width slot in the root grid — they serve as empty **drop-target gutters** ("余白").
- **Fill-Inner-First (Rule A)**: New axes are always appended at the bottom of the **inner column** (`column_count−1`). An axis can subsequently be moved to any column via D&D.
- **Per-Axis Resize Handles**: `RegionDividerItem` objects are placed between vertically-adjacent axes within each column. Dragging a handle calls `resize_axis(boundary_index, delta, column=…)` — resize is **column-scoped** (only axes within the same column are affected), ordered by their vertical position (`top_ratio`).

### Coordinate Mapping (The "Secret")
To achieve "Auto-Fit" without clipping, we apply a custom **Vertical Transform** to each `ViewBox`:
1. Each `ViewBox` occupies the **full** pixel height of the plot area.
2. We calculate a `mapping_factor` and `offset`:
   - `mapping_factor = 1.0 / Y_VM.height_ratio`
   - `offset = -Y_VM.top_ratio * mapping_factor`
3. We set the `ViewBox` Y-Range to a "virtual range" that positions the signal's actual 0-100% exactly within the target pixel region.
4. `setClipToView(False)` is used to ensure drawing remains visible outside the target region.

## Interactions

### Draggable Dividers
- Draggable objects are placed at the boundaries of `AxisItem` rows in the `Column Layouts`.
- On drag, the `height_ratio` and `top_ratio` of adjacent `YAxisVM` objects are updated.
- The `ViewBox` transforms are updated in real-time, causing the waveforms to stretch/compress.

### Drag and Drop Routing

#### Signal Drop
1. **Drop on `AxisItem`**: Calls `overwrite_axis` — **replaces** the axis's signal assignment with the dropped signal.
2. **Ctrl+Drop on `AxisItem`**: Calls `add_signal_to_axis` — **adds/joins** the signal to the existing `YAxisVM` without replacing.
3. **Drop on plot area (background)**: Calls `create_new_axis` — creates a new `YAxisVM` in the inner column (Rule A: `column_count−1`, appended at column bottom).

#### Axis Move (D&D)
- An axis carries its source index as drag data (`AXIS_INDEX_MIME`).
- On drop, `_axis_drop_target(pos)` computes `(column, position)` and calls `move_axis_to_column(index, column, position)`. The source slot is vacated; the destination column is equal-re-split among its new set of axes.
- **Drop feedback during drag**:
  - **Occupied column**: An **insertion line** snaps to the nearest of N+1 boundary candidates (top of first axis / between adjacent axes / bottom of last axis).
  - **Empty column (余白)**: The **whole column is highlighted** (no insertion line, as there are no boundaries).
  - **Source axis**: Dimmed as a placeholder during the drag and vacated on successful drop.
