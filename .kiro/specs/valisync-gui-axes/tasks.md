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
- [x] Task 1.2: Implement per-column sub-layouts (`_axis_layouts: dict[int, GraphicsLayout]`) to manage a vertical stack of `AxisItem`s and dividers for each occupied column. (Originally specified as `AxisColumnLayout`; the actual implementation uses a dictionary of `GraphicsLayout` objects keyed by column index — see Revision R1 below.)
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
- [x] Task 3.3: Final E2E Verification.
  - [x] **Verify**: Run `uv run valisync`, drag multiple signals with different units, adjust their heights, and verify auto-fit scaling and unclipped rendering. — auto-fit / unclipped / multi-unit は自動テスト + 実 `tests/fixtures/sample.mf4` 駆動で検証。divider ドラッグによる高さ調整は `test_dragging_divider_resizes_adjacent_regions` で回帰テスト化。D&D は `TestContextualDrop` でカバー。

---

## Revision R1: Multi-Column (re-review)

> **背景**: PR #4 merged 時点では R1（Multi-Column Y-Axis Grid）は tasks 全 `[x]`・完了扱いだったが、実コードは**単一列の縦積み**にとどまり、複数列グリッドは未実装だった。`feature/valisync-gui-axes-multicolumn` ブランチで 2026-06-27 に実装完了。実装計画: `docs/superpowers/plans/2026-06-27-multi-column-y-axis.md`。

- [x] **Rev-0.5**: VM column model — `GraphPanelVM.column_count` (default 2, `set_column_count(n)` clamps ≥1); `create_new_axis` appends to inner column bottom (Rule A); `move_axis_to_column(index, column, position)` vacates source + equal-re-splits destination.
- [x] **Rev-1.4**: View N-column layout — `_reconcile_axes` builds `_axis_layouts: dict[col → GraphicsLayout]`; plot at root col = `column_count`; empty columns hold fixed-width slots ("余白" drop-target gutters); per-axis `RegionDividerItem` handles drive `resize_axis(boundary_index, delta, column=…)` (column-scoped vertical-order).
- [x] **Rev-1.5**: Signal drop rules (R5 revision) — plain drop on axis = `overwrite_axis`; Ctrl+drop = `add_signal_to_axis`; drop on background = `create_new_axis` (Rule A).
- [x] **Rev-1.6**: Axis-move D&D + drop feedback — `AXIS_INDEX_MIME` drag source; `_axis_drop_target` computes `(column, position)`; **insertion line** feedback for occupied columns; **whole-column highlight** for empty columns; source axis dimmed during drag.
- [x] **Rev-3.3**: Verification — VM column logic covered by Layer A tests; view drop/move logic covered by Layer A/B via direct handler calls; real D&D delivery path (QDrag startup + hit-test + child→parent bubbling) is Layer C / manual only (see `docs/gui-testing-layers.md`).

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
