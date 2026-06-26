# Design Document: valisync-gui-axes

## Architecture

This sub-spec introduces a "Region-based Overlay" architecture using multiple `pyqtgraph.ViewBox` and `pyqtgraph.AxisItem` objects within nested `GraphicsLayout` structures.

### Component Interaction

```mermaid
graph TD
    subgraph View (PyQtGraph)
        G_Widget[GraphicsLayoutWidget]
        Root_Layout[Root Grid Layout]
        Col_Layout[Column Nested Layout]
        Main_VB[Overlaid ViewBoxes]
        Axis_Item[AxisItems]
        
        G_Widget --> Root_Layout
        Root_Layout --> Col_Layout
        Col_Layout --> Axis_Item
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
- **Root Layout**: A single row, multiple columns grid. The last column is always reserved for the wave plot area.
- **Column Layouts**: Each axis column is a `pyqtgraph.GraphicsLayout` added to a cell of the Root Layout. This allows independent row heights per column.

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
1. Drop on `AxisItem`: Signal joins the existing `YAxisVM`.
2. Drop on Plot Area: Creates a new `YAxisVM` with a default `height_ratio` (e.g., 0.3) in the first available slot.
