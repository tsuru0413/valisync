# Multi-Column Y-Axis (R1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `valisync-gui-axes` R1 (Multi-Column Y-Axis Grid) — Y-axes arranged in a fixed, configurable number of columns (default 2) to the left of the plot, filled from the plot side outward, with empty column space acting as a drop target ("余白") and per-axis height resize handles.

**Architecture:** Pure-Python `GraphPanelVM`/`YAxisVM` own the column model and all placement/normalization logic (headless-testable). `GraphPanelView` renders one nested `GraphicsLayout` per column in the root grid (plot reserved as the last column), adds per-axis resize handles, and routes drag-and-drop. The agreed interaction design lives in `docs/multi-axis-multicolumn-followup.md` (brainstorm outcome) and revises R5.

**Tech Stack:** Python 3.12, PySide6/pyqtgraph, pytest + pytest-qt. GUI tests follow the mandatory layers in `docs/gui-testing-layers.md` (A = headless state, B = `sendEvent` real-event routing, C = `--realgui` real OS input).

**Column convention:** `YAxisVM.column` is the 0-based **visual** index left→right. The plot sits to the right of all columns, so the **inner column** (plot-adjacent) is `column_count - 1`. New axes default to the inner column; outer (lower-index) columns are populated only by user moves; empty columns/space = 余白.

**Out of scope (deferred — see `docs/multi-axis-multicolumn-followup.md` 保留):** left/right (width) handles, axis move/reorder drop-feedback visuals, column-count settings UI placement.

---

## File Structure

- `src/valisync/gui/viewmodels/graph_panel_vm.py` — add `column_count`, column-aware `_normalize_axes`, `create_new_axis` → inner column, `overwrite_axis`, `move_axis_to_column`; extend `inspect()`.
- `src/valisync/gui/viewmodels/y_axis_vm.py` — `column` already exists; no structural change (used by VM logic).
- `src/valisync/gui/views/graph_panel_view.py` — `_reconcile_axes` builds N axis-column sub-layouts + plot as last grid column; per-axis resize handles; `dropEvent` overwrite/Ctrl-add/new rules; axis-move drag.
- `tests/gui/test_graph_panel_vm.py` / `test_graph_panel_multi_axis.py` — VM column logic (Layer A).
- `tests/gui/test_graph_panel_view.py` (or existing view test) — layout + D&D routing (Layer A/B).
- `tests/realgui/test_multi_column_axis.py` — real OS drag of an axis to 余白 (Layer C, opt-in).
- `.kiro/specs/valisync-gui-axes/{requirements,design,tasks}.md` + `CLAUDE.md` Phase table — reconcile status (Wave 3).

---

## Wave 0: VM column model (pure-Python, headless TDD)

### Task 0.1: `column_count` on `GraphPanelVM`

**Files:** Modify `graph_panel_vm.py`; Test `tests/gui/test_graph_panel_multi_axis.py`

- [ ] **Step 1 — failing test:**
```python
def test_default_column_count_is_two():
    vm = GraphPanelVM(Session())
    assert vm.column_count == 2

def test_set_column_count_notifies_and_clamps():
    vm = GraphPanelVM(Session()); seen = []
    vm.subscribe(lambda tag: seen.append(tag))
    vm.set_column_count(3)
    assert vm.column_count == 3 and "axes" in seen
    vm.set_column_count(0)            # invalid
    assert vm.column_count == 1       # clamped to >=1
```
- [ ] **Step 2:** Run → FAIL (`column_count` undefined).
- [ ] **Step 3 — implement:** in `__init__` add `self._column_count = 2`; add property `column_count` and `set_column_count(self, n: int)` that clamps `max(1, n)`, calls `_normalize_axes()`, `self._notify("axes")`.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 0.2: Column-aware `_normalize_axes` (per-column equal split)

**Files:** Modify `graph_panel_vm.py:153 _normalize_axes`; Test `test_graph_panel_multi_axis.py`

- [ ] **Step 1 — failing test:** two axes in different columns each fill their column full-height; two axes in the same column split it 50/50.
```python
def test_normalize_splits_height_per_column():
    vm = GraphPanelVM(Session()); _inject_two_signals(vm)  # helper: 2 signals -> 2 axes
    vm.axes[0].column, vm.axes[1].column = 1, 1            # same (inner) column
    vm._normalize_axes()
    assert [(a.top_ratio, a.height_ratio) for a in _col(vm, 1)] == [(0.0, 0.5), (0.5, 0.5)]
    vm.axes[1].column = 0                                  # move to outer column
    vm._normalize_axes()
    assert all(a.height_ratio == 1.0 for a in vm.axes)     # each alone in its column
```
- [ ] **Step 2:** Run → FAIL (current code splits across all axes ignoring column).
- [ ] **Step 3 — implement:** after the existing compaction/remap, replace the equal-split block so it **groups `self._axes` by `axis.column`** and, within each column group (ordered by current top_ratio to keep relative order), assigns `top_ratio = i*h, height_ratio = h` where `h = 1/len(group)`. Keep the "no signals → single full placeholder" branch (placeholder column = `column_count-1`).
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 0.3: `create_new_axis` targets the inner column (rule A)

**Files:** Modify `graph_panel_vm.py:141 create_new_axis`; Test `test_graph_panel_multi_axis.py`

- [ ] **Step 1 — failing test:**
```python
def test_new_axis_lands_in_inner_column():
    vm = GraphPanelVM(Session()); _inject_signal(vm, "csv_1::a")   # first signal
    assert vm.axes[0].column == vm.column_count - 1                # inner col
    vm.create_new_axis("csv_1::b")
    assert all(a.column == vm.column_count - 1 for a in vm.axes)   # both inner, stacked
    assert [a.height_ratio for a in vm.axes] == [0.5, 0.5]
```
- [ ] **Step 2:** Run → FAIL (new axis defaults column 0; not inner).
- [ ] **Step 3 — implement:** in `create_new_axis`, construct `YAxisVM(column=self._column_count - 1)` instead of `YAxisVM()`. (The first-ever axis also gets the inner column via the same path / placeholder default.)
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 0.4: `overwrite_axis` + Ctrl-add semantics (R5 revision)

**Files:** Modify `graph_panel_vm.py`; Test `test_graph_panel_multi_axis.py`

- [ ] **Step 1 — failing test:**
```python
def test_overwrite_axis_replaces_signals_on_that_axis():
    vm = GraphPanelVM(Session()); _inject_signal(vm, "csv_1::a")  # axis 0 has 'a'
    vm.overwrite_axis("csv_1::b", 0)
    assert _signals_on_axis(vm, 0) == ["csv_1::b"]                # 'a' replaced
def test_add_signal_to_axis_keeps_both():                         # Ctrl-add path unchanged
    vm = GraphPanelVM(Session()); _inject_signal(vm, "csv_1::a")
    vm.add_signal_to_axis("csv_1::b", 0)
    assert set(_signals_on_axis(vm, 0)) == {"csv_1::a", "csv_1::b"}
```
- [ ] **Step 2:** Run → FAIL (`overwrite_axis` undefined).
- [ ] **Step 3 — implement:** `overwrite_axis(self, signal_key, axis_index)`: drop existing `_plotted` entries with `e.axis_index == axis_index`, reset that axis's `name`/`unit`, then `add_signal_to_axis(signal_key, axis_index)`. `add_signal_to_axis` (Ctrl-add) stays as-is.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 0.5: `move_axis_to_column`

**Files:** Modify `graph_panel_vm.py`; Test `test_graph_panel_multi_axis.py`

- [ ] **Step 1 — failing test:**
```python
def test_move_axis_to_column_revacates_source():
    vm = GraphPanelVM(Session()); _inject_signal(vm, "csv_1::a"); vm.create_new_axis("csv_1::b")
    vm.move_axis_to_column(0, 0)               # move first inner axis to outer column 0
    assert vm.axes[0].column == 0 and vm.axes[0].height_ratio == 1.0   # alone in col 0
    assert _col(vm, vm.column_count-1)[0].height_ratio == 1.0          # remaining fills inner
```
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3 — implement:** `move_axis_to_column(self, axis_index, column)`: clamp `column` to `[0, column_count-1]`, set `self._axes[axis_index].column = column`, `_normalize_axes()`, `_notify("axes")`.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 0.6: Extend `inspect()` projection

**Files:** Modify `graph_panel_vm.py:427 inspect`; Test `test_graph_panel_multi_axis.py`

- [ ] **Step 1 — failing test:** `inspect()["column_count"] == 2` and each `inspect()["axes"][i]` carries `column`, `top_ratio`, `height_ratio`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** add `"column_count": self._column_count` and confirm per-axis `column` is present (already at line 449). **Step 4:** PASS. **Step 5:** Commit.

---

## Wave 1: View — multi-column layout, handles, D&D

> View tasks follow `docs/gui-testing-layers.md`: **Layer A** asserts `inspect()`-style projected state; **Layer B** drives real events via `QApplication.sendEvent`; **Layer C** (Wave 4) does a real OS drag. Read the existing method before modifying.

### Task 1.1: Render N axis columns + plot as last grid column

**Files:** Modify `graph_panel_view.py:298 _reconcile_axes` (+ `_sync_overlay_geometry`); Test `test_graph_panel_view.py`

- [ ] **Step 1 — failing test (Layer A):** with two axes in columns 0 and 1 (column_count 2), the view exposes one axis sub-layout per occupied column and places each `AxisItem` in the matching root grid column; the plot ViewBox is in root column `column_count`.
```python
def test_view_builds_one_sublayout_per_column(qtbot):
    view, vm = _mounted_panel(qtbot, columns=2)
    _inject_signal(vm, "csv_1::a"); vm.move_axis_to_column(0, 0)   # axis in OUTER col 0
    vm.create_new_axis("csv_1::b")                                  # axis in INNER col 1
    view.refresh()
    assert sorted(view.axis_columns()) == [0, 1]                    # new introspection helper
    assert view.plot_grid_column() == 2
```
- [ ] **Step 2:** Run → FAIL. 
- [ ] **Step 3 — implement:** generalize `_reconcile_axes`: instead of a single `_axis_layout` at `(row=0,col=0)`, create a dict `{column_index: GraphicsLayout}` added at `root (row=0, col=column_index)` for each column that has axes; reserve `root col = column_count` for the plot ViewBox container (update the `setColumnFixedWidth`/`setColumnStretchFactor` loop accordingly). Within each column sub-layout, stack that column's axes by row using their per-column `top_ratio` order and `height_ratio` stretch (same formula as today, but per column). Keep the multi-ViewBox overlay + `setXLink` + `_sync_overlay_geometry` (ViewBoxes still overlay the single plot rect). Add introspection helpers `axis_columns()` and `plot_grid_column()` for tests.
- [ ] **Step 4:** Run → PASS; run full `uv run pytest` (no regression in existing axis tests). **Step 5:** Commit.

### Task 1.2: Per-axis top/bottom resize handles

**Files:** Modify `graph_panel_view.py` (reuse/extend the existing `RegionDividerItem`); Test `test_graph_panel_view.py`

- [ ] **Step 1 — failing test (Layer B):** dragging the handle at the boundary between two stacked axes in the same column updates their `height_ratio` (assert via `vm.axes` after a synthesized drag), mirroring the existing `test_dragging_divider_resizes_adjacent_regions`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3 — implement:** place a draggable handle at each axis's shared boundary within a column (top edge of all-but-first, bottom edge of all-but-last); wire its drag delta to `vm.resize_axis(...)` scoped to the column (extend `resize_axis` to take a column or a pair of axis indices). Left/right handles are **deferred** (out of scope).
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 1.3: Drop rules — overwrite / Ctrl-add / new (inner column)

**Files:** Modify `graph_panel_view.py:587 dropEvent` (+ `_axis_index_at`); Test `test_graph_panel_view.py`

- [ ] **Step 1 — failing test (Layer B):** build three `QDropEvent`s via `sendEvent` (hold the `QMimeData` in a local — see `docs/development.md` GUI pitfalls): (a) drop over an axis → `overwrite_axis` called for that axis; (b) drop over an axis with `Qt.ControlModifier` → `add_signal_to_axis`; (c) drop over the plot background → `create_new_axis` (lands in inner column per Wave 0).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3 — implement:** in `dropEvent`, resolve `_axis_index_at(pos)`; if valid and `event.modifiers() & Qt.ControlModifier` → `add_signal_to_axis`; if valid and no modifier → `overwrite_axis`; else → `create_new_axis`. (Removes the old "join on plain drop" behavior — R5 revision.)
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

### Task 1.4: Drag an existing axis to another column / 余白

**Files:** Modify `graph_panel_view.py` (axis-item drag source + column drop target); Test `test_graph_panel_view.py`

- [ ] **Step 1 — failing test (Layer B):** simulate an axis-move gesture (start drag on an `AxisItem`, drop over an empty column region) → `vm.move_axis_to_column(axis_index, target_column)` invoked with the target column; assert via `vm.axes[i].column`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3 — implement:** make each axis draggable (carry its axis index in the drag payload); compute the target column from the drop x-position relative to the column sub-layouts (empty column region = 余白); call `vm.move_axis_to_column`. Drop-feedback visuals are **deferred**.
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

## Wave 2: Column-count plumbing

### Task 2.1: Expose column count from panel → settings hook

**Files:** Modify `graph_panel_vm.py` (already has `set_column_count`) + the panel's owner; Test existing VM test

- [ ] **Step 1 — failing test:** changing `column_count` from 2→3 re-normalizes and the view (`view.refresh()`) renders 3 reserved columns. (Layer A.)
- [ ] **Step 2–4:** wire a public path to `set_column_count` (a method on the panel/area VM); **UI placement of the setting is deferred** — a programmatic setter + test is sufficient for this scope. **Step 5:** Commit.

---

## Wave 3: Spec & status reconciliation (docs)

### Task 3.1: Revise the axes spec to match reality + this design

**Files:** Modify `.kiro/specs/valisync-gui-axes/{requirements,design,tasks}.md`, `CLAUDE.md` Phase table, `docs/multi-axis-multicolumn-followup.md`

- [ ] **R5 revision** in `requirements.md`: change R5.1 from "join that axis" to "**replace (overwrite)** the dropped signal onto that axis; **Ctrl+drop adds**"; keep R5.2 (background → new axis) and note the inner-column rule (A).
- [ ] **design.md**: replace the unimplemented `AxisColumnLayout`/single-`GraphicsLayout` description with the actual per-column sub-layout design and the fill-inner-first + 余白 + per-axis-handle model.
- [ ] **tasks.md**: add a "Revision R1: Multi-Column (re-review)" section listing the waves above; correct the overstated all-`[x]` status note for R1.
- [ ] **CLAUDE.md** Phase table: change axes row to reference this follow-up + that R1 multi-column was completed here.
- [ ] **Step:** Commit (docs-only).

---

## Wave 4: Verification

### Task 4.1: Layer C real-OS axis move

**Files:** Create `tests/realgui/test_multi_column_axis.py` (`@pytest.mark.realgui`); follow `tests/realgui/test_file_browser_realclick.py` pattern

- [ ] Real OS drag (Win32) of an axis from the inner column into an empty outer column; assert `vm.axes[i].column` changed and a screenshot artifact saved. Skipped by default/CI; run `uv run pytest --realgui tests/realgui/`.

### Task 4.2: Full gate + manual E2E

- [ ] `uv run pytest` (Layer A/B green, realgui skipped) + `ruff check` + `ruff format --check` + `mypy src/`.
- [ ] `uv run valisync`: load 3+ signals → confirm new axes land inner-column, resize via handles, drag an axis to the outer column (余白), overwrite vs Ctrl-add on an existing axis.

---

### Task Dependency Graph
```json
{
  "tasks": [
    {"id":"0.1","desc":"column_count","deps":[]},
    {"id":"0.2","desc":"per-column normalize","deps":["0.1"]},
    {"id":"0.3","desc":"new axis -> inner col","deps":["0.2"]},
    {"id":"0.4","desc":"overwrite/Ctrl-add","deps":["0.2"]},
    {"id":"0.5","desc":"move_axis_to_column","deps":["0.2"]},
    {"id":"0.6","desc":"inspect projection","deps":["0.1"]},
    {"id":"1.1","desc":"N column layout","deps":["0.2","0.3","0.6"]},
    {"id":"1.2","desc":"per-axis handles","deps":["1.1"]},
    {"id":"1.3","desc":"drop rules","deps":["1.1","0.4"]},
    {"id":"1.4","desc":"axis move D&D","deps":["1.1","0.5"]},
    {"id":"2.1","desc":"column-count plumbing","deps":["1.1"]},
    {"id":"3.1","desc":"spec reconciliation","deps":["1.1","1.3"]},
    {"id":"4.1","desc":"Layer C realgui","deps":["1.4"]},
    {"id":"4.2","desc":"full gate + E2E","deps":["1.2","1.3","1.4","2.1"]}
  ]
}
```
