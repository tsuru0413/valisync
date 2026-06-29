# Task 5 Report: R14 オフセットドラッグジェスチャ

## Status

DONE — 5/5 Layer B tests pass. Full suite 602 passed / 11 skipped. All quality gates clean.

## Commit

`355ee43` — feat(gui): R14 オフセットドラッグジェスチャ（プレビュー/ツールチップ/Escape/適用ダイアログ）

## TDD Evidence

**RED** (before implementation):
```
uv run pytest tests/gui/test_graph_panel_offset_drag.py -v
5 FAILED — TypeError: GraphPanelView.__init__() got an unexpected keyword argument 'apply_dialog_fn'
```

**GREEN** (after implementation):
```
uv run pytest tests/gui/test_graph_panel_offset_drag.py -v
5 passed in 2.28s
```

**Full suite**: 602 passed, 11 skipped, 2 warnings in 54.31s — zero regressions.

## Quality Gate

- `uv run ruff check` — All checks passed
- `uv run ruff format --check` — 120 files already formatted (ruff format applied first)
- `uv run mypy src/` — Success: no issues found in 52 source files
- `uv run pytest` — 602 passed, 11 skipped

## Files Changed

- `src/valisync/gui/views/graph_panel_view.py` — Modified (Signal, __init__, mouse handlers, helpers, refresh guard)
- `tests/gui/test_graph_panel_offset_drag.py` — Created (5 Layer B tests)

## Implementation Summary

### Imports added
- `from collections.abc import Callable`
- `QKeyEvent` in PySide6.QtGui imports
- `QToolTip` in PySide6.QtWidgets imports

### Signal added
```python
offset_apply_requested = Signal(str, float, str)  # signal_key, delta_t, scope
```

### __init__ changes
- Signature extended: `apply_dialog_fn: Callable[[str, float], str | None] | None = None`
- `self._apply_dialog_fn = apply_dialog_fn` stored
- 5 offset-drag state fields: `_offset_drag_key`, `_offset_drag_start_x`, `_offset_orig_xy`, `_offset_orig_pen`, `_offset_last_delta`
- `self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)` at end

### Mouse / key handlers
- `mousePressEvent`: X-zone branch preserved; ZONE_PLOT branch added (calls `_begin_offset_drag` when `_curve_at` returns a key)
- `mouseMoveEvent`: offset drag branch intercepts when `_offset_drag_key` is set; existing X-zone cursor update preserved
- `mouseReleaseEvent`: offset drag branch intercepts first; existing X-zone logic fully preserved
- `keyPressEvent`: Escape during offset drag calls `_cancel_offset_drag()`

### Helpers added (after `_curve_at`)
- `_begin_offset_drag` — captures origin xy/pen, highlights with width=3 pen, sets SizeHorCursor
- `_update_offset_preview` — shifts curve xs by Δt, shows QToolTip with `f"Δt = {delta_t:+.3g} s"`
- `_end_offset_drag` — defers dialog via `QTimer.singleShot(0, lambda: self._finish_offset(...))`
- `_finish_offset` — calls dialog fn, emits if confirmed, cancels if not
- `_cancel_offset_drag` — calls `_reset_offset_state(restore_data=True)`
- `_reset_offset_state` — restores data+pen, hides tooltip, clears all state fields
- `_default_apply_dialog` — real QDialog with 2 radio buttons (signal/group), Ok/Cancel buttons

### refresh() guard
Added after curve update loop, before geometry sync:
- If `_offset_drag_key` disappeared from `_items` → cancel drag
- Otherwise re-apply preview offset (in case of mid-drag rebuild)

## Self-Review

### X-zone drag behavior preserved?
YES — `mousePressEvent` checks `zone in (ZONE_X_INNER, ZONE_X_OUTER)` first (unchanged), then adds `elif zone == ZONE_PLOT`. `mouseMoveEvent` early-returns only if `_offset_drag_key is not None`, otherwise falls through to the existing cursor update. `mouseReleaseEvent` early-returns only during offset drag; X-zone commit logic unchanged.

### Backward-compatible construction?
YES — `apply_dialog_fn` defaults to `None`. `make_single_signal_panel()` in `_panel_factory.py` calls `GraphPanelView(vm)` (no new param); `make_two_axis_panel()` likewise. Both factories work unchanged. No construction errors in the full 602-test suite.

### Deferred dialog?
YES — `_end_offset_drag` schedules `_finish_offset` via `QTimer.singleShot(0, ...)`, matching the axis-move `_apply_deferred_axis_move` pattern. No `exec()` runs inside the mouse-release handler.

### cursor-line scene-detach lifetime code in `_reconcile_axes`?
NOT TOUCHED — only `refresh()`, the three mouse handlers, the constructor, and a block after `_curve_at` were modified.

### `_curve_at` modified?
NO — only the block of helper methods added after it, and the mouse handler calls.

## Concerns

None blocking. Layer C (Task 7 realgui) will exercise:
1. Real OS mouse press/move/release on the actual display
2. The real `_default_apply_dialog` modal (QDialog.exec()) with Enter/Cancel keyboard
3. Escape key via real OS keypress

The Layer B tests here prove the wiring (event → state, dialog fn → emit/restore) but cannot prove the real modal OS path (documented in test docstring).

---

## Review Follow-up (commit faea07c)

### Findings addressed

**Finding 1 (Important — plan-mandated test)**: Added `test_refresh_cancels_drag_when_curve_removed`.
- VM removal API used: `GraphPanelVM.remove_signal(key)` — triggers `_notify("signals")` → subscriber `_on_vm_change("signals")` → `refresh()` synchronously. The §9 guard fires inside that refresh, calling `_cancel_offset_drag()`.
- Assert: `_offset_drag_key is None` + `captured == []` (no emit).

**Finding 2 (Minor — cursor restore)**: Added `self.unsetCursor()` at the end of `_reset_offset_state` (after field clears). Covers confirm, cancel, and Escape paths — the SizeHorCursor set by `_begin_offset_drag` no longer lingers through the apply dialog or into the next mouse move.

**Finding 3 (Minor — negative-path test)**: Added `test_press_zone_plot_no_nearby_curve_no_drag`.
- Press at `(rect.left()+3, rect.top()+3)` — the linear signal (v=t) is far from this corner so `_curve_at` returns None. Assert `_offset_drag_key is None`.

### Gate results

- `uv run ruff check` — All checks passed
- `uv run ruff format --check` — 120 files already formatted
- `uv run mypy src/` — Success: no issues found in 52 source files
- `uv run pytest tests/gui/test_graph_panel_offset_drag.py -v` — 7/7 passed (existing 5 + new 2)
- `uv run pytest` — 604 passed, 11 skipped, 2 warnings — zero regressions

### Files changed

- `src/valisync/gui/views/graph_panel_view.py` — `_reset_offset_state`: added `self.unsetCursor()`
- `tests/gui/test_graph_panel_offset_drag.py` — added `test_refresh_cancels_drag_when_curve_removed` + `test_press_zone_plot_no_nearby_curve_no_drag`
