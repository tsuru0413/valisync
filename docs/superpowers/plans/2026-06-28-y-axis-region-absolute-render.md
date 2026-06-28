# Y軸リージョン絶対レイアウト描画（空白ギャップ忠実描画）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** View が VM の絶対リージョンレイアウト（`top_ratio`/`height_ratio`、合計<1.0 の空白含む）を忠実に描画する — 削除/移動で抜けた帯を本当の空白として表示する。

**Architecture:** 列内の縦スタックを `QGraphicsGridLayout` の行ストレッチ（正規化＝空白を表現不可）から、**絶対ジオメトリ同期**へ統一。Y軸スパイン・波形 ViewBox・ディバイダを、マスター ViewBox の rect を基準に同じ絶対ストリップ `[top_ratio·H, height_ratio·H]` へ `setGeometry`。既存の `_sync_overlay_geometry`（refresh＋`sigResized` で発火）を拡張するだけでリサイズも自動追従。**View のみ変更・VM 不変。**

**Tech Stack:** Python 3.12/3.13, PySide6 + pyqtgraph（View 層）, pytest/pytest-qt, uv, ruff, mypy。

**設計の一次情報源:** [docs/superpowers/specs/2026-06-28-y-axis-region-absolute-render-design.md](../specs/2026-06-28-y-axis-region-absolute-render-design.md)

## Global Constraints

- **View のみ変更**: `src/valisync/gui/views/graph_panel_view.py` のみ。`graph_panel_vm.py` / `y_axis_vm.py`（VM）は変更しない。VM は PySide6/Qt を import しない純 Python を維持。
- **絶対配置の統一**: Y軸スパイン・波形 ViewBox・ディバイダは同一の絶対ストリップ基準（マスター ViewBox rect の Y、列コンテナ rect の X）で配置する。grid 行ストレッチによる縦スタックは廃止。
- **検証は描画ジオメトリで**: テストは VM 値ではなく実際の `sceneBoundingRect()`（描画結果）を assert する（前回 false-green の是正）。
- **公開セマンティクス維持**: `axis_columns()`（占有列）/ `plot_grid_column()`（プロット列＝`column_count`）の戻り値の意味は維持。
- **品質ゲート（コミット前に全通過）**: `uv run pytest`、`uv run ruff check`、`uv run ruff format --check`、`uv run mypy src/`。
- **GUI テストレイヤー**: docs/gui-testing-layers.md 準拠。Layer B（描画ジオメトリ・headless 可）必須・CI。Layer C（`--realgui`）はローカル Windows 実表示のみ。
- **commit 規約**: 末尾に `Co-Authored-By:` / `Claude-Session:` トレーラ。
- **事前準備**: worktree で最初に一度 `uv sync --extra dev`。

---

## Testing Strategy（realgui を含む — 重点検討）

前回の不具合は「realgui テストが**実OSドラッグで起動はするが、その後 VM の値を assert**していた」ため、**描画されていない**バグを検知できず false-green になった。今回は層の役割を明確化する：

| 層 | 何を検証するか | 実行 | 役割 |
|---|---|---|---|
| **Layer B（描画ジオメトリ）** | View をマウントし、実際の `_view_boxes[i]`/`_y_axes[i]` の `sceneBoundingRect()` が絶対ストリップに一致し、**空白帯にどの要素の rect も無い**こと | **CI（headless/offscreen 可）** | **回帰の主防御**。offscreen でもレイアウトジオメトリは計算される（既存 `test_dragging_divider_is_column_scoped` が headless で `view._view_boxes[0].geometry()` を検証している前例あり）。空白描画の退行を決定論的に CI で捕捉。 |
| **Layer A（VM）** | 高さ計算（移動/削除/並べ替え） | CI | 不変。既存テスト維持。VM 値のみで描画は保証しない（今回の教訓）。 |
| **Layer C（realgui・実OS入力）** | 実マウス操作（移動ドラッグ／Remove File 右クリック）後に、**実際の描画ジオメトリ**で空白・整列を確認＋**スクショ保存** | ローカル Windows 実表示のみ（CI 非対象・skip） | 実表示＋実入力経路＋DPI/WM の確証と、人間が目視できる**スクショ成果物**。 |

**realgui 設計判断（明示）:**
1. **realgui の assert は VM 値ではなく描画ジオメトリにする**（`_view_boxes[]`/`_y_axes[]` の rect）。これが前回欠けていた本質。
2. **既存 realgui 2本を書き換える**: `test_multi_column_axis.py`（移動）と `test_remove_file_preserves_proportions.py`（削除）。両者とも実入力ハーネス（実OSドラッグ／実右クリック＋watchdog＋最前面化）は流用し、**末尾の assert を描画ジオメトリへ置換**＋失敗時/通常時にスクショ保存。
3. **回帰の主防御は Layer B**（CI・決定論）。realgui は実機確証＋目視用で、CI に依存しない（実機が無い環境では skip）。
4. **ピクセルサンプリングは不採用（YAGNI）**: スクショの画素色で「空白帯が背景色」と判定する案は、テーマ色・アンチエイリアスで脆く保守困難。**「空白帯にどの要素の rect も無い」ジオメトリ assert＋スクショの人間目視**で十分とする。
5. **実機実行は controller が最後に1回行い結果（PASS＋スクショ）を確認**（実装 subagent は headless のため）。

---

## File Structure

| ファイル | 役割 | 変更 |
|---|---|---|
| `src/valisync/gui/views/graph_panel_view.py` | グラフパネル View（リージョン描画） | 列コンテナ導入・AxisItem をシーン配置・`_sync_overlay_geometry` 拡張・ディバイダ絶対配置（Task 1） |
| `tests/gui/test_graph_panel_render_geometry.py` | **新規** Layer B 描画ジオメトリ | 空白描画・整列・リサイズ追従（Task 1） |
| `tests/gui/test_graph_panel_multi_axis.py` 他 | 既存 GUI テスト | grid 内部前提の assert を新機構へ更新（Task 1） |
| `tests/realgui/test_multi_column_axis.py` / `test_remove_file_preserves_proportions.py` | Layer C | assert を描画ジオメトリへ置換＋スクショ（Task 2） |
| `docs/multi-axis-empty-region-followup.md` / `CLAUDE.md` | 追跡 | View 描画修正を反映（Task 2） |

---

## Pre-flight（最初に一度）

- [ ] **依存同期**: `uv sync --extra dev` → 完了。
- [ ] **ベースライン**: `uv run pytest tests/gui/ -q` → 全 PASS を確認（変更前の緑）。
- [ ] **現状の可視化（任意・実機）**: 後述の Layer B 新規テストはまず **RED**（現状は空白が描画されないため失敗）になることが、本修正が必要であることの証左。

---

### Task 1: View をリージョン絶対ジオメトリ描画へ統一（＋Layer B 描画テスト）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`_reconcile_axes` build 経路 `:401-517`、`_sync_overlay_geometry` `:339-351`、ディバイダ生成 `:495-505`）
- Create: `tests/gui/test_graph_panel_render_geometry.py`
- Modify: 既存 GUI テストのうち grid 内部前提のもの（下記 Step で特定）

**Interfaces:**
- Consumes: `GraphPanelVM.axes[i].top_ratio/height_ratio/column`（不変）、`YAxisVM.calculate_virtual_range()`（不変）。
- Produces: `_column_containers: dict[int, QGraphicsWidget]`（占有列→幅確保コンテナ）。`_sync_overlay_geometry()` が ViewBox に加え `_y_axes[i]` とディバイダを絶対ストリップへ配置する（戻り値なし）。`_y_axes[i]`/`_view_boxes[i]` と `vm.axes[i]` のペアリングは維持。

**設計メモ（ジオメトリの正確な定義）:** マスター ViewBox（`_view_boxes[0]`）の `sceneBoundingRect()` を `R` とする。リージョン i（列 c, top t, height h）の絶対ストリップは：
- **Y は常に `R` 基準**（軸と波形が同じ Y を共有して整列するため）: `strip_y = R.y() + t*R.height()`, `strip_h = h*R.height()`。
- **X は列コンテナ基準**: `band = _column_containers[c].sceneBoundingRect()` → `strip_x = band.x()`, `strip_w = band.width()`。
- 軸: `_y_axes[i].setGeometry(QRectF(strip_x, strip_y, strip_w, strip_h))`。
- 波形 ViewBox: 従来どおり `R` 全面（virtual-range が Y を絶対化）。**変更不要**。
- ディバイダ（隣接連続のみ）: 列内を top 昇順に並べ、`t_{k+1} ≈ t_k + h_k`（`abs(...) < 1e-6`）のときのみ、境界 `y = R.y() + (t_k+h_k)*R.height()` に水平ジオメトリ（`x=band.x(), w=band.width(), 高さ数px`）で配置。

> **GUI 実装の反復について（プレースホルダではない）**: pyqtgraph の AxisItem/ディバイダをシーンアイテム化して `setGeometry` で描画する細部（ティック描画・クリッピング・幅）は、下記 Layer B テストを**実行しながら**詰める。各実装 Step は「テストを RED→GREEN にする」TDD で進め、テストが描画ジオメトリの**完全な受け入れ条件**を成す。

- [ ] **Step 1: Layer B 描画テストを新規作成（RED）**

`tests/gui/test_graph_panel_render_geometry.py` を作成。ヘルパ `_make_view`/`_loaded_session`/`_keys` は `tests/gui/test_graph_panel_view.py`（`:52,61,65`）で定義され `test_graph_panel_multi_axis.py:19` が同じ形で再 import している。mount → resize → show → waitExposed → waitUntil(geometry settled) のパターン（`test_dragging_divider_is_column_scoped:937-940`）に倣う。

```python
"""Layer B: rendered-geometry tests — the View must paint the VM's absolute
region layout (blank gaps included), not normalize/fill. Asserts actual
sceneBoundingRect() geometry, NOT VM values (the gap the prior tests missed)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from typing import cast

from tests.gui.test_graph_panel_view import _keys, _loaded_session, _make_view
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView

# NOTE: _keys/_loaded_session/_make_view are the project's existing GUI-test
# helpers in tests/gui/test_graph_panel_view.py (re-imported the same way by
# tests/gui/test_graph_panel_multi_axis.py:19). _make_view returns `object`,
# hence the cast.


def _mounted(qtbot: QtBot, vm: GraphPanelVM) -> GraphPanelView:
    """Mount the view over a VM whose axes are already configured, show it, and
    wait until layout geometry has settled (mirrors the mount pattern in
    test_dragging_divider_is_column_scoped)."""
    view = cast(GraphPanelView, _make_view(qtbot, vm))
    view.resize(1000, 700)
    view.show()
    qtbot.waitExposed(view)
    view.refresh()
    qtbot.waitUntil(
        lambda: bool(view._view_boxes)
        and view._view_boxes[0].sceneBoundingRect().height() > 100,
        timeout=3000,
    )
    return view


def _plot_rect(view: GraphPanelView):
    return view._view_boxes[0].sceneBoundingRect()


def _strip_of_axis(view: GraphPanelView, i: int):
    """Return (top_frac, height_frac) of axis i's spine within the plot Y-band."""
    R = _plot_rect(view)
    rect = view._y_axes[i].sceneBoundingRect()
    return ((rect.y() - R.y()) / R.height(), rect.height() / R.height())


def test_axis_spines_render_at_absolute_strips_with_blank_gap(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """3 regions 0.5/0.3/0.2 in one column, delete the middle -> survivors render
    at absolute strips (A=[0,0.5], C=[0.8,1.0]) with a blank band [0.5,0.8].

    A fresh GraphPanelVM(session) has zero axes; three create_new_axis calls
    stack three regions in the inner column (column_count-1)."""
    session, _ = _loaded_session(tmp_path, n_signals=3)
    keys = sorted(_keys(session))
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])
    vm.create_new_axis(keys[1])
    vm.create_new_axis(keys[2])
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.5
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.5, 0.3
    vm.axes[2].top_ratio, vm.axes[2].height_ratio = 0.8, 0.2

    view = _mounted(qtbot, vm)
    # Prune the middle signal -> VM leaves A(0,0.5)/C(0.8,0.2) with a blank gap.
    remaining = [s for s in session.signals() if s.name != keys[1]]
    session.signals = lambda: remaining  # type: ignore[method-assign]
    vm.prune_missing_signals()
    view.refresh()
    qtbot.waitUntil(lambda: len(view._y_axes) == 2, timeout=2000)

    # Survivors sorted by rendered top.
    strips = sorted((_strip_of_axis(view, i) for i in range(len(view._y_axes))))
    (a_top, a_h), (c_top, c_h) = strips
    assert a_top == pytest.approx(0.0, abs=0.03)
    assert a_h == pytest.approx(0.5, abs=0.03)
    assert c_top == pytest.approx(0.8, abs=0.03)
    assert c_h == pytest.approx(0.2, abs=0.03)
    # The middle band [0.5,0.8] must contain NO axis spine rect.
    R = _plot_rect(view)
    gap_lo, gap_hi = R.y() + 0.55 * R.height(), R.y() + 0.75 * R.height()
    for i in range(len(view._y_axes)):
        r = view._y_axes[i].sceneBoundingRect()
        assert not (r.y() < gap_hi and r.y() + r.height() > gap_lo), (
            "an axis spine overlaps the blank band — gap not rendered (filled)"
        )


def test_axis_spine_aligned_with_its_waveform_viewbox(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Each region's axis spine strip matches its waveform ViewBox data strip."""
    session, _ = _loaded_session(tmp_path, n_signals=2)
    keys = sorted(_keys(session))
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])
    vm.create_new_axis(keys[1])
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.7
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.7, 0.3

    view = _mounted(qtbot, vm)
    R = _plot_rect(view)
    for i, expected_top in ((0, 0.0), (1, 0.7)):
        top_frac, _h = _strip_of_axis(view, i)
        assert top_frac == pytest.approx(expected_top, abs=0.03), (
            f"axis {i} spine not at its absolute strip (got {top_frac})"
        )
```

- [ ] **Step 2: Run the new tests to verify they FAIL**

Run: `uv run pytest tests/gui/test_graph_panel_render_geometry.py -q`
Expected: FAIL — the current grid row-stretch fills the column, so survivor spines render at normalized positions (≈0.714/0.286) and overlap the blank band. (This RED proves the bug.)

- [ ] **Step 3: Build path — replace grid sub-layouts with column containers + scene AxisItems**

In `_reconcile_axes` rebuild path (`graph_panel_view.py:401-517`): replace the per-column `addLayout`/`setRowStretchFactor` stacking with column containers and scene-item AxisItems. Rename the instance attribute: in `__init__` replace `self._axis_layouts: dict[int, pg.GraphicsLayout] = {}` (`:222`) with `self._column_containers: dict[int, QGraphicsWidget] = {}`, and the reset `self._axis_layouts = {}` (`:427`) with `self._column_containers = {}`. Concrete changes:

```python
# (a) Reserve each occupied gutter column with an empty container widget so the
#     fixed-width columns don't collapse; it also provides the per-column X band.
from PySide6.QtWidgets import QGraphicsWidget  # add to imports

self._column_containers = {}
for col in sorted({c for _, c, _ in placement}):
    container = QGraphicsWidget()
    container.setMaximumWidth(_Y_AXIS_FIXED_WIDTH)
    self.plot_widget.addItem(container, row=0, col=col)
    self._column_containers[col] = container

# (b) Create AxisItems as SCENE items (like secondary ViewBoxes), positioned by
#     _sync_overlay_geometry — NOT added to a grid, NOT row-stretched.
#     (Replaces the prior `sub.addItem(axis,...)` + setRowStretchFactor.)
self.plot_widget.scene().addItem(axis)
```

Keep ViewBox creation unchanged (master in plot col, secondaries in scene). Remove all `self._axis_layouts[...]` usage. Update `axis_columns()` to `return sorted(self._column_containers)` (same semantics: occupied columns).

> Iterate against Step 1 tests + a real-display smoke check. If an AxisItem added to the scene doesn't paint ticks/labels until `setGeometry`, that's expected — geometry is set in Step 4's sync.

**Fast path (`:385-399`)** — also de-grid it: this branch handles a pure height change (e.g. divider drag) without rebuilding, to keep the dragged divider object alive. Change the guard `if self._axis_layouts` → `if self._column_containers`, and **delete the `setRowStretchFactor` retune** (the three lines `self._axis_layouts[col].layout.setRowStretchFactor(row, int(axis_vm.height_ratio * 1000))`). Keep the label retune (`self._y_axes[i].setLabel(...)`) and the `return`. The height change is then applied by `_sync_overlay_geometry()`, which `refresh()` calls (`:322`) after `_reconcile_axes()` returns — it reads each `axis_vm.top_ratio/height_ratio` live and repositions spines/dividers/ViewBoxes to the new strips.

- [ ] **Step 4: Extend `_sync_overlay_geometry` to position axis spines (and keep ViewBox sync)**

Replace `_sync_overlay_geometry` (`:339-351`) with absolute positioning of axes too (Y from master rect, X from column container). Dividers are added in Step 5.

```python
def _sync_overlay_geometry(self) -> None:
    """Align secondary ViewBoxes AND axis spines to absolute region strips.

    Region i (column c, top t, height h) occupies the strip
    [R.y()+t*R.height(), h*R.height()] of the master plot rect R (so a region
    sum < 1.0 leaves a genuine blank band — no normalization). X comes from the
    column container so spines sit in their gutter. Called on refresh and on the
    master's sigResized, so geometry follows window resizes.
    """
    if not self._view_boxes:
        return
    R = self._view_boxes[0].sceneBoundingRect()
    for vb in self._view_boxes[1:]:
        vb.setGeometry(R)
    for i, axis_vm in enumerate(self.vm.axes):
        container = self._column_containers.get(axis_vm.column)
        if container is None:
            continue
        band = container.sceneBoundingRect()
        strip = QRectF(
            band.x(),
            R.y() + axis_vm.top_ratio * R.height(),
            band.width(),
            axis_vm.height_ratio * R.height(),
        )
        self._y_axes[i].setGeometry(strip)
    self._position_dividers(R)
```

Add a `_position_dividers(self, R: QRectF) -> None` stub that does nothing yet (filled in Step 5) so this step runs:
```python
def _position_dividers(self, R: QRectF) -> None:
    return
```

- [ ] **Step 5: Run axis tests GREEN; iterate item-wiring as needed**

Run: `uv run pytest tests/gui/test_graph_panel_render_geometry.py -q`
Expected: PASS for `test_axis_spines_render_at_absolute_strips_with_blank_gap` and `test_axis_spine_aligned_with_its_waveform_viewbox`. If a spine's `sceneBoundingRect()` is empty/zero, ensure the AxisItem is in the scene and `setGeometry` runs after layout settles (the sync is called from `refresh()` and `sigResized`).

- [ ] **Step 6: Dividers — absolute placement between contiguous regions only**

Replace the grid-based divider creation (`:495-505`) with scene-item dividers, and implement `_position_dividers`. Create one `RegionDividerItem` per **contiguous** vertical pair within a column (no divider across a blank gap). The `RegionDividerItem(vm, rank, column)` API is unchanged (rank = upper region's vertical rank in its column).

Build path (replace `:495-505`):
```python
self._dividers = []
by_col: dict[int, list[int]] = {}
for i, ax in enumerate(self.vm.axes):
    by_col.setdefault(ax.column, []).append(i)
for col, idxs in by_col.items():
    ordered = sorted(idxs, key=lambda i: self.vm.axes[i].top_ratio)
    for rank in range(len(ordered) - 1):
        upper, lower = self.vm.axes[ordered[rank]], self.vm.axes[ordered[rank + 1]]
        if abs((upper.top_ratio + upper.height_ratio) - lower.top_ratio) < 1e-6:
            divider = RegionDividerItem(self.vm, rank, column=col)
            self.plot_widget.scene().addItem(divider)
            self._dividers.append(divider)
```
`_position_dividers`:
```python
def _position_dividers(self, R: QRectF) -> None:
    for divider in self._dividers:
        col = divider.column
        ordered = sorted(
            (a for a in self.vm.axes if a.column == col), key=lambda a: a.top_ratio
        )
        upper = ordered[divider.axis_index]  # rank == upper region's vertical index
        band = self._column_containers[col].sceneBoundingRect()
        y = R.y() + (upper.top_ratio + upper.height_ratio) * R.height()
        divider.setGeometry(QRectF(band.x(), y - 2.0, band.width(), 4.0))
```
> Confirm `RegionDividerItem` exposes `.column` and `.axis_index` (it is constructed with `(vm, rank, column=col)`); if the attribute names differ, read the class and adapt. If `RegionDividerItem` is not a `QGraphicsWidget` (no `setGeometry`), position via `setPos` + a width/line update — iterate against Step 7.

- [ ] **Step 7: Add divider Layer B test; run GREEN**

Append to `tests/gui/test_graph_panel_render_geometry.py`:
```python
def test_no_divider_across_blank_gap(qtbot: QtBot, tmp_path: Path) -> None:
    """After deleting the middle of 3 regions, no divider sits in the blank band."""
    session, _ = _loaded_session(tmp_path, n_signals=3)
    keys = sorted(_keys(session))
    vm = GraphPanelVM(session)
    for k in keys:
        vm.create_new_axis(k)
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.5
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.5, 0.3
    vm.axes[2].top_ratio, vm.axes[2].height_ratio = 0.8, 0.2
    view = _mounted(qtbot, vm)
    remaining = [s for s in session.signals() if s.name != keys[1]]
    session.signals = lambda: remaining  # type: ignore[method-assign]
    vm.prune_missing_signals()
    view.refresh()
    qtbot.waitUntil(lambda: len(view._y_axes) == 2, timeout=2000)
    # A(0,0.5) and C(0.8,0.2) are NOT contiguous -> zero dividers between them.
    assert len(view._dividers) == 0
```
Run: `uv run pytest tests/gui/test_graph_panel_render_geometry.py -q` → all PASS.

- [ ] **Step 8: Update existing GUI tests that assumed the grid internals; full GUI suite GREEN**

Run `uv run pytest tests/gui/ -q`. Expect breakages ONLY in tests that asserted the old grid mechanism. Known candidates to inspect (do not weaken intent):
- `test_graph_panel_multi_axis.py::test_view_builds_one_sublayout_per_column` — **likely still PASSES as-is**: it only asserts `axis_columns() == [0, 1]` and `plot_grid_column() == 2`, whose semantics are preserved (`axis_columns()` now returns `sorted(self._column_containers)`). The test *name* is now stale (no sub-layouts exist) — optionally rename to `test_view_reserves_one_container_per_column`. Do NOT change the assertions.
- `test_dragging_divider_is_column_scoped` / `test_resize_axis_is_scoped_to_one_column` — dividers/resize still exist (`_dividers`, VM `resize_axis` unchanged). These drive `RegionDividerItem.mouseDragEvent` and read `view._dividers[0]` / `view._view_boxes[0].geometry()`, none of which reference `_axis_layouts` — expected to PASS. Confirm `view._dividers` is still populated (Step 6 keeps it).
- Any test reading `view._axis_layouts` — none found by grep at plan time; if one appears, switch it to `_column_containers` or rendered geometry.
For each failure: read the test, determine whether it asserts (a) old mechanism internals (update to new equivalent) or (b) a real behavior (must still hold). Do NOT edit a test to pass if it reveals a real regression — report BLOCKED.
Expected after updates: full `tests/gui/` PASS.

- [ ] **Step 9: Gates + commit**

Run: `uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: clean.
```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_render_geometry.py tests/gui/test_graph_panel_multi_axis.py
git commit -m "fix(gui): render Y-axis regions at absolute strips (blank gaps shown); scene-item axes/dividers"
```

---

### Task 2: Layer C realgui を描画ジオメトリ検証へ書き換え＋追跡ドキュメント更新

**Files:**
- Modify: `tests/realgui/test_multi_column_axis.py`、`tests/realgui/test_remove_file_preserves_proportions.py`
- Modify: `docs/multi-axis-empty-region-followup.md`、`CLAUDE.md`

**Interfaces:** Consumes Task 1 の `view._view_boxes[]` / `view._y_axes[]` 描画ジオメトリ。

- [ ] **Step 1: 移動 realgui を描画ジオメトリ assert へ置換**

`tests/realgui/test_multi_column_axis.py` の `# ─── Assertions ───` ブロック（**現状 L257–285**）の **VM 比率 assert**（`vm.axes[0].column == 0` / `vm.axes[0].height_ratio == approx(0.5)` / `inner_axes[0].top_ratio == approx(0.5)` …）を、**実ドラッグ後の描画ジオメトリ**検証へ置換する。`view` は `_CapturingView`（`drop_seen` 付き、L146-160）、`view._column_containers` は Task 1 で追加。**実入力ハーネス（背景スレッド実OSドラッグ＋watchdog＋最前面化）・`drop_seen` による完了確認・既存スクショ保存（`mid_drag.png`/`after_drag.png`）は維持**。pairing は `_y_axes[i] ↔ vm.axes[i]`（移動後 axis0=移動軸＝col0／axis1=inner 残存）。置換後（`# ─── Assertions ───` 直後の本文を丸ごと差し替え）:
```python
    # Real-input completion proof (KEEP): the drag actually reached dropEvent.
    assert view.drop_seen, (
        "no dropEvent fired — the real-OS drag never completed (watchdog "
        f"cancelled it). Screenshots saved to {tmp_path}"
    )
    assert len(vm.axes) == 2, f"expected 2 axes after drag, got {len(vm.axes)}"
    # Let the post-drop rebuild settle, then assert RENDERED geometry — NOT VM
    # ratios. The prior column/height_ratio/top_ratio asserts were the
    # false-green: the VM moved the axis but the View never painted the gap.
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: len(view._y_axes) == 2  # type: ignore[attr-defined]
        and view._view_boxes[0].sceneBoundingRect().height() > 100,  # type: ignore[attr-defined]
        timeout=3000,
    )
    R = view._view_boxes[0].sceneBoundingRect()  # type: ignore[attr-defined]

    def _strip(i: int) -> tuple[float, float]:
        r = view._y_axes[i].sceneBoundingRect()  # type: ignore[attr-defined]
        return ((r.y() - R.y()) / R.height(), r.height() / R.height())

    def _center_x(i: int) -> float:
        return view._y_axes[i].sceneBoundingRect().center().x()  # type: ignore[attr-defined]

    # axis 0 = the moved axis; its spine must paint in the OUTER column 0 band,
    # ~0.5 tall at top 0.0 (NOT grown to full height).
    band0 = view._column_containers[0].sceneBoundingRect()  # type: ignore[attr-defined]
    moved_top, moved_h = _strip(0)
    assert band0.x() <= _center_x(0) <= band0.x() + band0.width(), (
        f"moved spine not rendered in outer column 0 band. Screenshots: {tmp_path}"
    )
    assert moved_top == pytest.approx(0.0, abs=0.06), (
        f"moved spine not at top of col0 (got {moved_top}). Screenshots: {tmp_path}"
    )
    assert moved_h == pytest.approx(0.5, abs=0.06), (
        f"moved spine not ~0.5 tall — gap not rendered (got {moved_h}). "
        f"Screenshots: {tmp_path}"
    )
    # axis 1 = inner remainder; its spine must paint in column 1 at top ~0.5
    # (the vacated top half [0.0,0.5] is a genuine blank band).
    band1 = view._column_containers[1].sceneBoundingRect()  # type: ignore[attr-defined]
    rem_top, _rem_h = _strip(1)
    assert band1.x() <= _center_x(1) <= band1.x() + band1.width(), (
        f"inner remainder spine not in column 1 band. Screenshots: {tmp_path}"
    )
    assert rem_top == pytest.approx(0.5, abs=0.06), (
        f"inner remainder spine not at top 0.5 (blank above) — got {rem_top}. "
        f"Screenshots: {tmp_path}"
    )
```
モジュール/関数 docstring の検証箇条書き（L62-73 等）を「rendered geometry（spine strips + column band）, not VM values」に更新。`pytest` は import 済み（L46）。

- [ ] **Step 2: 削除 realgui を描画ジオメトリ assert へ置換**

`tests/realgui/test_remove_file_preserves_proportions.py` の `# ─── Assert: middle region pruned ...` ブロック（**現状 L267–287**）の **VM 比率 assert**（`cols[0].height_ratio == approx(heights_before[0])` / `cols[1].height_ratio == approx(heights_before[2])` / `sum(...) == approx(...)`）を **描画ジオメトリ**へ置換。`gpv` は `GraphPanelView(panel)`、`heights_before` は分割ドラッグ後の3リージョン高さ（top_ratio 昇順、L192-194 で取得済み；中央 `heights_before[1]` を削除）。**実右クリックハーネス（QTimer 内 capture）・`captured["triggered"]` 確認・スクショ（`drag.png`/`menu.png`/`after.png`）・`finally` 後始末は維持**。構造 assert（`len(panel.axes) == 2`, `len(gpv._view_boxes) == 2`）は残す。置換後（その2行の構造 assert の間〜後を差し替え）:
```python
        assert len(panel.axes) == 2, (
            f"expected 2 regions after Remove File, got {len(panel.axes)}. "
            f"Screenshots: {tmp_path}"
        )
        # RENDERED geometry (NOT VM height_ratio): survivors keep their absolute
        # strips and the removed middle band is genuinely blank. The prior
        # height_ratio/sum asserts were the false-green — the VM computed the gap
        # but the View never painted it.
        for _ in range(3):
            QApplication.processEvents()
        qtbot.waitUntil(
            lambda: len(gpv._y_axes) == 2  # type: ignore[attr-defined]
            and gpv._view_boxes[0].sceneBoundingRect().height() > 100,  # type: ignore[attr-defined]
            timeout=3000,
        )
        R = gpv._view_boxes[0].sceneBoundingRect()  # type: ignore[attr-defined]

        def _strip(i: int) -> tuple[float, float]:
            r = gpv._y_axes[i].sceneBoundingRect()  # type: ignore[attr-defined]
            return ((r.y() - R.y()) / R.height(), r.height() / R.height())

        rendered = sorted(_strip(i) for i in range(len(gpv._y_axes)))  # type: ignore[attr-defined]
        (top_top, top_h), (bot_top, bot_h) = rendered
        # Survivors keep their absolute heights as RENDERED strip fractions
        # (top == heights_before[0]; bottom == heights_before[2]).
        assert top_h == pytest.approx(heights_before[0], abs=0.04), (
            f"top survivor not rendered at its absolute height: {top_h} != "
            f"{heights_before[0]}. Screenshots: {tmp_path}"
        )
        assert bot_h == pytest.approx(heights_before[2], abs=0.04), (
            f"bottom survivor not rendered at its absolute height: {bot_h} != "
            f"{heights_before[2]}. Screenshots: {tmp_path}"
        )
        # Removed middle band is blank: a real gap is rendered between survivors
        # and no spine paints inside it.
        gap_lo = R.y() + (top_top + top_h) * R.height()
        gap_hi = R.y() + bot_top * R.height()
        assert gap_hi - gap_lo > 0.05 * R.height(), (
            f"no blank band rendered between survivors (gap collapsed). "
            f"Screenshots: {tmp_path}"
        )
        mid = gap_lo + 0.5 * (gap_hi - gap_lo)
        for i in range(len(gpv._y_axes)):  # type: ignore[attr-defined]
            r = gpv._y_axes[i].sceneBoundingRect()  # type: ignore[attr-defined]
            assert not (r.y() < mid < r.y() + r.height()), (
                f"a spine paints inside the blank band. Screenshots: {tmp_path}"
            )
        assert len(gpv._view_boxes) == 2  # type: ignore[attr-defined]
```
モジュール docstring（L7-12）の検証説明を「rendered geometry（strip fractions + blank-band absence）, not VM height_ratio」に更新。

- [ ] **Step 3: realgui collect 確認＋（実機は controller 実行）**

Run: `uv run pytest --realgui tests/realgui/ --collect-only -q`
Expected: 両ファイルが import/収集エラー無く収集される（headless では実行 skip）。実機実行は controller が最後に行う。

- [ ] **Step 4: 追跡ドキュメント更新**

`docs/multi-axis-empty-region-followup.md` の「## 対応状況」末尾に追記：
```markdown
- **空白ギャップの忠実描画（2026-06-28）**: 高さ保持（PR #14/#16）は VM では空白を計算していたが、View が列内を grid 行ストレッチ（正規化）で積むため**描画されていなかった**。View をリージョン絶対ジオメトリ描画（Y軸スパイン・波形・ディバイダを絶対ストリップへ統一同期）へ修正し、空白が実際に描画されるようにした。検証は VM 値ではなく描画ジオメトリ（Layer B 必須・CI／Layer C realgui を geometry assert へ）。設計: [docs/superpowers/specs/2026-06-28-y-axis-region-absolute-render-design.md](superpowers/specs/2026-06-28-y-axis-region-absolute-render-design.md)。
```
`CLAUDE.md` の Phase 状況 `valisync-gui-axes` 行末に追記：
```markdown
。リージョンの空白ギャップは View 側で未描画だった不具合を絶対ジオメトリ描画へ統一して修正（PR pending）— 設計 [docs/superpowers/specs/2026-06-28-y-axis-region-absolute-render-design.md](docs/superpowers/specs/2026-06-28-y-axis-region-absolute-render-design.md)
```

- [ ] **Step 5: 全ゲート＋commit**

Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: pytest 全 PASS（realgui skip）、lint/format/型クリーン。
```bash
git add tests/realgui/test_multi_column_axis.py tests/realgui/test_remove_file_preserves_proportions.py docs/multi-axis-empty-region-followup.md CLAUDE.md
git commit -m "test(realgui)+docs: assert rendered region geometry (blank gap) instead of VM values"
```

---

## Self-Review

**1. Spec coverage:**
- 絶対ストリップ描画（軸/波形/ディバイダ統一）→ Task 1 Step 3-6（`_sync_overlay_geometry` 拡張・列コンテナ・シーン軸・ディバイダ）。
- 空白ギャップ描画 → Task 1 Step 1/7 の Layer B（gap 帯に rect 無し）。
- 軸と波形の整列 → Task 1 Step 1（`test_axis_spine_aligned_with_its_waveform_viewbox`）。
- リサイズ追従 → 既存 `sigResized`→`_sync_overlay_geometry` 配線（Task 1 Step 4 のメソッドが両経路で発火）。**追加 Layer B のリサイズテストを Task 1 Step 1 に含めるべき** → 下記で補強。
- VM 不変・View のみ → Global Constraints + Task 1 ファイル範囲。
- realgui を描画ジオメトリへ → Task 2 + Testing Strategy 節。

**2. Placeholder scan:** 「GUI 実装の反復」注記は手順を省く意味ではなく、TDD でテストを受け入れ条件にする旨の明示。各コード Step は具体コードを含む。テストコードは完全。

**3. Type consistency:** `_column_containers: dict[int, QGraphicsWidget]`、`_sync_overlay_geometry()`/`_position_dividers(R: QRectF)`、`axis_columns()→sorted(self._column_containers)` を全 Step で一貫使用。`RegionDividerItem(vm, rank, column=col)` は既存 API。

**補強（self-review で追加）:** Task 1 Step 1 に下記リサイズテストも含める：
```python
def test_region_geometry_follows_resize(qtbot: QtBot, tmp_path: Path) -> None:
    from tests.gui.test_graph_panel_multi_axis import _loaded_session, _keys
    session, _ = _loaded_session(tmp_path, n_signals=2)
    keys = sorted(_keys(session))
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0]); vm.create_new_axis(keys[1])
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.7
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.7, 0.3
    view = _mounted(qtbot, vm)
    view.resize(1200, 900)
    qtbot.waitUntil(lambda: _plot_rect(view).height() > 100, timeout=2000)
    top0, h0 = _strip_of_axis(view, 0)
    assert top0 == pytest.approx(0.0, abs=0.03) and h0 == pytest.approx(0.7, abs=0.03)
```

---

## Execution Handoff

> **GUI 描画修正のため**: 実装 subagent は headless で動く。回帰の主防御は **Layer B（headless 描画ジオメトリ・CI）** が担うので subagent-driven でも検知可能だが、**最終の実機 realgui＋スクショ目視は controller が実行**して確認する。
