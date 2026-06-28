# 軸ごとリサイズ ＋ アクティブ軸統一操作モデル 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 各 Y 軸を独立にリサイズでき、パン/ズーム/リサイズ/移動を「アクティブ軸」に集約した統一操作モデルへ刷新する（連動ディバイダーを廃止）。

**Architecture:** ドメインロジックは VM（`GraphPanelVM`/`YAxisVM`、per-axis `y_range` は既存を流用）。アクティブ軸の操作面は `_AlignedAxisItem`（pyqtgraph の AxisItem）に集約し、アイテムローカル座標のゾーン判定でグリップ=リサイズ／枠線=移動(QDrag)／内側=ズーム／外側=パンへ分岐。壊れた widget レベルのゾーン方式と `RegionDividerItem` は撤去（根本修正）。

**Tech Stack:** Python 3 / PySide6 / pyqtgraph / pytest / pytest-qt。realgui は Win32 `mouse_event`（Layer C）。

**設計一次情報**: [docs/superpowers/specs/2026-06-28-y-axis-per-axis-resize-active-model-design.md](../specs/2026-06-28-y-axis-per-axis-resize-active-model-design.md)

## Global Constraints

- 最小高さ `MIN_H = 0.05`（リサイズ下限、verbatim）。
- リサイズ制約3つ: **最小5%／隣接軸を押さない／自身の逆端も押さない**。
- ズームは**範囲選択（ズームインのみ）**。**ホイール・ダブルクリックは X/Y とも不採用**。ズームアウト/リセットは本スコープ外（後日コンテキストメニュー）。
- 全操作（パン/ズーム/リサイズ/移動）は**アクティブ軸のみ受付**。X 軸（時間・共有）は常時。
- アクティブ状態は**非永続**（.vsproj に保存しない）。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。worktree では先に `uv sync --extra dev`。
- GUI テストレイヤー（`docs/gui-testing-layers.md`）必須。input-path 変更のため Layer B 必須、Layer C（realgui）を merge 前に証拠付きで実行（`/gui-verify`）。

---

## ファイル構成

| ファイル | 役割 | 操作 |
|---|---|---|
| `src/valisync/gui/viewmodels/graph_panel_vm.py` | `resize_axis_edge`（モデルB）、`set_axis_range`（アクティブ軸ズーム/パン）追加。連動 `resize_axis` 削除。 | Modify |
| `src/valisync/gui/views/graph_panel_view.py` | `classify_axis_zone`（純関数）追加。`_AlignedAxisItem` に hover/cursor・ゾーン分岐ドラッグ・フレーム/グリップ paint。アクティブ軸状態。divider 生成・`_position_dividers`・widget レベル Y ゾーン・`wheelEvent`・`mouseDoubleClickEvent` 撤去。 | Modify |
| `src/valisync/gui/views/region_divider_item.py` | 連動ディバイダー | **Delete** |
| `tests/gui/test_graph_panel_resize_edge.py` | Layer A: `resize_axis_edge` / `set_axis_range` | Create |
| `tests/gui/test_axis_zone_classify.py` | Layer A: `classify_axis_zone` | Create |
| `tests/gui/test_axis_interaction.py` | Layer A/B: `_AlignedAxisItem` 分岐・アクティブ状態・paint・divider 廃止 | Create |
| `tests/gui/test_region_divider_item.py` | 連動ディバイダーのテスト | **Delete** |
| `tests/gui/test_graph_panel_multi_axis.py` | 連動 divider 依存テストの除去/置換 | Modify |
| `tests/realgui/test_active_axis_resize.py` | Layer C: グリップ実リサイズ | Create |
| `tests/realgui/test_active_axis_zoom_pan.py` | Layer C: 内側ズーム/外側パン＋カーソル | Create |
| `tests/realgui/test_multi_column_axis.py` | Layer C: 移動を「アクティブ化→枠線ドラッグ」に更新 | Modify |

---

## テスト戦略（gui-test-plan 分析）

`docs/gui-testing-layers.md` を enforce。レイヤー必須運用表に従う。

| タスク | 変更種別 | A | B | C | 入力経路の再現性 |
|---|---|---|---|---|---|
| 1 `resize_axis_edge` | VM/純ロジック | 必須 | — | — | — |
| 2 `set_axis_range` | VM/純ロジック | 必須 | — | — | — |
| 3 `classify_axis_zone` | 純ロジック | 必須 | — | — | — |
| 4 アクティブ状態+クリック起動 | 入力→ハンドラ | 必須 | 必須 | 推奨 | press は item 直叩きで Layer B 可 |
| 5 hover→cursor/paint | 入力→ハンドラ/状態 | 必須 | 必須(状態) | **必須(cursor 実描画)** | hover の cursor 反映は実機のみ確証 |
| 6 ドラッグ分岐 | 入力→ハンドラ | 必須 | 必須(分岐直叩き) | **必須** | リサイズ/ズーム/パンは直接ドラッグ→Layer B 可。移動=QDrag は **Layer C 専用** |
| 7 divider 撤去 | ウィジェット構成 | 必須 | 該当 | — | — |
| 8 widget ゾーン/wheel/dblclick 撤去 | ウィジェット構成 | 必須 | 該当 | — | — |
| 9 realgui リサイズ | 入力→ハンドラ | — | — | **必須** | 実 OS 入力。QDrag 不使用＝単純駆動 |
| 10 realgui ズーム/パン+カーソル | 入力→ハンドラ | — | — | **必須** | 実 OS 入力＋カーソル形状＋描画レンジ |
| 11 realgui 移動 | 入力→ハンドラ | — | — | **必須** | QDrag＝背景スレッド+watchdog（既存踏襲） |

**②実質性（realgui は実経路でしか証明できない結果を assert）**:
- リサイズ（タスク9）: ドラッグ後の **描画ストリップ**（`_y_axes[i].sceneBoundingRect()` の相対 top/height）を assert（VM 値の再チェックは naive。Layer A と重複）。対象軸のみ変化・他軸不動を幾何で確認。
- ズーム/パン（タスク10）: ドラッグ後の **AxisItem.range**（`_y_axes[i].range`）が縮小/移動したことを assert＋**カーソル形状**（`view.cursor().shape()` がゾーン別）。`QApplication.primaryScreen().grabWindow` でスクショ（`QT_QPA_PLATFORM=windows`）。
- 移動（タスク11）: `dropEvent` 発火（`drop_seen`）＋ 移動先列の **描画ストリップ**（既存 `test_multi_column_axis.py` 同様）。
- アンチパターン禁止: 「スクショ保存のみ・assert 無し」「VM 値だけ再チェック」。

**①証拠ゲート（merge 前・該当のみ）**:
```
- [ ] uv run pytest --realgui tests/realgui/test_active_axis_resize.py  + pass ログ/スクショ添付
- [ ] uv run pytest --realgui tests/realgui/test_active_axis_zoom_pan.py + 同上（カーソル形状を観測）
- [ ] uv run pytest --realgui tests/realgui/test_multi_column_axis.py    + 同上
```
非 Windows/ディスプレイ無しで実行できない場合は**ゲート未充足**（`skipped` を緑と誤認しない）。実行は `/gui-verify` で scoped 自動化。

**honest layering note**:
- リサイズ/ズーム/パンの分岐ロジックを Layer B で「ハンドラ直叩き」検証するのは可（`item._begin_drag(zone, ...)` 等の純メソッドを呼ぶ）。ただし **実際にその zone がドラッグで起動するか・カーソルが変わるか・QDrag 移動が配送されるかは Layer B では証明不可**（Layer C 必須）。直叩きを「Layer C 相当」と誤称しない。
- 移動の QDrag は合成 `sendEvent` で配送再現不可（`docs/gui-testing-layers.md` §Layer C 専用ケース）。

---

## Task 1: VM `resize_axis_edge`（モデルB 単一辺リサイズ）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- Test: `tests/gui/test_graph_panel_resize_edge.py`

**Interfaces:**
- Produces: `GraphPanelVM.resize_axis_edge(axis_index: int, edge: str, delta_ratio: float) -> None`（`edge ∈ {"top","bottom"}`、`delta_ratio` は下方向正）。対象軸のみ `top_ratio`/`height_ratio` を変更し `_notify("axes")`。他軸は不変。制約3つでクランプ。
- Consumes: `self._axes: list[YAxisVM]`（`top_ratio`/`height_ratio`/`column`）、列内縦順 = `sorted(col_axes, key=top_ratio)`。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_graph_panel_resize_edge.py
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.viewmodels.y_axis_vm import YAxisVM


def _panel_with(axes: list[YAxisVM]) -> GraphPanelVM:
    vm = GraphPanelVM.__new__(GraphPanelVM)  # bypass Session; we only test layout math
    vm._axes = axes
    vm._column_count = 1
    vm._notified: list[str] = []
    vm._notify = lambda topic: vm._notified.append(topic)  # type: ignore[assignment]
    return vm


def test_resize_bottom_grows_into_gap_below_others_unchanged() -> None:
    # A[0.0,0.3] B[0.3,0.3] gap[0.6,0.4]  -> drag B bottom down by 0.2
    a = YAxisVM(top_ratio=0.0, height_ratio=0.3)
    b = YAxisVM(top_ratio=0.3, height_ratio=0.3)
    vm = _panel_with([a, b])
    vm.resize_axis_edge(1, "bottom", 0.2)
    assert (b.top_ratio, round(b.height_ratio, 6)) == (0.3, 0.5)  # bottom moved, top fixed
    assert (a.top_ratio, a.height_ratio) == (0.0, 0.3)            # neighbour unchanged


def test_resize_bottom_does_not_push_neighbour() -> None:
    # A[0.0,0.5] B[0.5,0.5] flush -> drag A bottom down: cannot pass B.top (0.5)
    a = YAxisVM(top_ratio=0.0, height_ratio=0.5)
    b = YAxisVM(top_ratio=0.5, height_ratio=0.5)
    vm = _panel_with([a, b])
    vm.resize_axis_edge(0, "bottom", 0.3)
    assert (a.top_ratio, a.height_ratio) == (0.0, 0.5)  # clamped: no growth
    assert (b.top_ratio, b.height_ratio) == (0.5, 0.5)  # neighbour not pushed


def test_resize_bottom_shrink_clamped_to_min_height_top_fixed() -> None:
    a = YAxisVM(top_ratio=0.0, height_ratio=0.5)
    b = YAxisVM(top_ratio=0.5, height_ratio=0.5)
    vm = _panel_with([a, b])
    vm.resize_axis_edge(0, "bottom", -0.9)  # shrink far past min
    assert a.top_ratio == 0.0                          # opposite (top) edge fixed
    assert round(a.height_ratio, 6) == 0.05            # clamped to MIN_H
    assert (b.top_ratio, b.height_ratio) == (0.5, 0.5)


def test_resize_top_grows_upward_into_gap_bottom_fixed() -> None:
    # gap[0.0,0.4] B[0.4,0.6] -> drag B top up by 0.4 (delta=-0.4)
    b = YAxisVM(top_ratio=0.4, height_ratio=0.6)
    vm = _panel_with([b])
    vm.resize_axis_edge(0, "top", -0.4)
    assert round(b.top_ratio, 6) == 0.0
    assert round(b.height_ratio, 6) == 1.0   # bottom (0.4+0.6=1.0) fixed


def test_resize_top_does_not_push_neighbour_above() -> None:
    a = YAxisVM(top_ratio=0.0, height_ratio=0.5)
    b = YAxisVM(top_ratio=0.5, height_ratio=0.5)
    vm = _panel_with([a, b])
    vm.resize_axis_edge(1, "top", -0.3)  # B top up: cannot pass A.bottom (0.5)
    assert (b.top_ratio, b.height_ratio) == (0.5, 0.5)
    assert (a.top_ratio, a.height_ratio) == (0.0, 0.5)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_resize_edge.py -v`
Expected: FAIL（`AttributeError: 'GraphPanelVM' object has no attribute 'resize_axis_edge'`）

- [ ] **Step 3: 最小実装**

```python
# graph_panel_vm.py — add near resize_axis (which will be removed in Task 7)
MIN_H = 0.05  # module-level if not already present

def resize_axis_edge(self, axis_index: int, edge: str, delta_ratio: float) -> None:
    """Resize a single axis by dragging one edge (model B).

    Only the dragged edge moves: the axis's opposite edge is anchored and the
    neighbour is never pushed. Other axes are untouched; the adjacent gap on the
    dragged side absorbs the change. ``delta_ratio`` is positive downward.
    Constraints: min height 5%, don't pass the neighbour, don't move the opposite edge.
    """
    if not (0 <= axis_index < len(self._axes)):
        return
    axis = self._axes[axis_index]
    col_axes = sorted(
        (a for a in self._axes if a.column == axis.column),
        key=lambda a: a.top_ratio,
    )
    rank = col_axes.index(axis)

    if edge == "bottom":
        # bottom = top + height moves; top fixed. New bottom limited by next.top or 1.0.
        lower_bound = col_axes[rank + 1].top_ratio if rank + 1 < len(col_axes) else 1.0
        new_bottom = axis.top_ratio + axis.height_ratio + delta_ratio
        new_bottom = min(new_bottom, lower_bound)                      # don't push neighbour
        new_bottom = max(new_bottom, axis.top_ratio + MIN_H)          # min height (top fixed)
        axis.height_ratio = new_bottom - axis.top_ratio
    elif edge == "top":
        # top moves; bottom = top + height fixed. New top limited by prev.bottom or 0.0.
        upper = col_axes[rank - 1] if rank - 1 >= 0 else None
        upper_bound = (upper.top_ratio + upper.height_ratio) if upper else 0.0
        bottom = axis.top_ratio + axis.height_ratio
        new_top = axis.top_ratio + delta_ratio
        new_top = max(new_top, upper_bound)                           # don't push neighbour
        new_top = min(new_top, bottom - MIN_H)                        # min height (bottom fixed)
        axis.top_ratio = new_top
        axis.height_ratio = bottom - new_top
    else:
        return

    self._notify("axes")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_panel_resize_edge.py -v`
Expected: PASS（5件）

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_resize_edge.py
git commit -m "feat(gui-vm): add resize_axis_edge (model B single-edge resize)"
```

---

## Task 2: VM `set_axis_range`（アクティブ軸のズーム/パン適用）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- Test: `tests/gui/test_graph_panel_resize_edge.py`（同ファイルに追記）

**Interfaces:**
- Produces: `GraphPanelVM.set_axis_range(axis_index: int, lo: float, hi: float) -> None` — 指定軸の `YAxisVM.set_range(lo, hi)` を呼び `_notify("axes")`。先頭軸固定の `set_y_range` に依存しない、軸指定の経路。

- [ ] **Step 1: 失敗するテストを追記**

```python
def test_set_axis_range_targets_that_axis_only() -> None:
    a = YAxisVM(top_ratio=0.0, height_ratio=0.5, y_range=(0.0, 10.0))
    b = YAxisVM(top_ratio=0.5, height_ratio=0.5, y_range=(0.0, 10.0))
    vm = _panel_with([a, b])
    vm.set_axis_range(1, 2.0, 4.0)        # zoom-in on axis b
    assert b.y_range == (2.0, 4.0)
    assert a.y_range == (0.0, 10.0)       # untouched (NOT the first-axis-fixed path)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_resize_edge.py::test_set_axis_range_targets_that_axis_only -v`
Expected: FAIL（`AttributeError: ... set_axis_range`）

- [ ] **Step 3: 最小実装**

```python
# graph_panel_vm.py
def set_axis_range(self, axis_index: int, lo: float, hi: float) -> None:
    """Set the Y data range of one axis (active-axis zoom/pan target)."""
    if not (0 <= axis_index < len(self._axes)):
        return
    self._axes[axis_index].set_range(min(lo, hi), max(lo, hi))
    self._notify("axes")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_panel_resize_edge.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add -A && git commit -m "feat(gui-vm): add set_axis_range for active-axis zoom/pan"
```

---

## Task 3: View 純関数 `classify_axis_zone`

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（module-level 関数＋定数を追加）
- Test: `tests/gui/test_axis_zone_classify.py`

**Interfaces:**
- Produces: ゾーン定数 `AXZONE_GRIP_TOP/AXZONE_GRIP_BOTTOM/AXZONE_FRAME/AXZONE_ZOOM/AXZONE_PAN`（str）。
  `classify_axis_zone(lx: float, ly: float, w: float, h: float, *, grip_w: float, grip_h: float, frame: float, tol: float) -> str`。
  座標はアイテムローカル（左上原点、x 右増加・y 下増加、内側＝右＝プロット寄り）。優先順位: グリップ → 枠線 → 内/外。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_axis_zone_classify.py
from valisync.gui.views.graph_panel_view import (
    AXZONE_FRAME,
    AXZONE_GRIP_BOTTOM,
    AXZONE_GRIP_TOP,
    AXZONE_PAN,
    AXZONE_ZOOM,
    classify_axis_zone,
)

W, H = 60.0, 120.0
KW = dict(grip_w=40.0, grip_h=8.0, frame=3.0, tol=4.0)


def test_top_centre_is_grip_top() -> None:
    assert classify_axis_zone(W / 2, 2.0, W, H, **KW) == AXZONE_GRIP_TOP


def test_bottom_centre_is_grip_bottom() -> None:
    assert classify_axis_zone(W / 2, H - 2.0, W, H, **KW) == AXZONE_GRIP_BOTTOM


def test_top_corner_is_frame_not_grip() -> None:
    # near top edge but far left of the centred grip -> frame (move), not resize
    assert classify_axis_zone(2.0, 2.0, W, H, **KW) == AXZONE_FRAME


def test_left_interior_is_pan_right_interior_is_zoom() -> None:
    assert classify_axis_zone(W * 0.25, H / 2, W, H, **KW) == AXZONE_PAN   # outer/left
    assert classify_axis_zone(W * 0.75, H / 2, W, H, **KW) == AXZONE_ZOOM  # inner/right


def test_grip_takes_priority_over_frame_and_interior() -> None:
    # a point inside the grip rect (centre, near top) is GRIP even though it also
    # sits on the frame band / interior split.
    assert classify_axis_zone(W / 2, 5.0, W, H, **KW) == AXZONE_GRIP_TOP
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_axis_zone_classify.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 最小実装**

```python
# graph_panel_view.py — module level (near classify_zone)
AXZONE_GRIP_TOP = "ax_grip_top"
AXZONE_GRIP_BOTTOM = "ax_grip_bottom"
AXZONE_FRAME = "ax_frame"
AXZONE_ZOOM = "ax_zoom"
AXZONE_PAN = "ax_pan"


def classify_axis_zone(
    lx: float, ly: float, w: float, h: float,
    *, grip_w: float, grip_h: float, frame: float, tol: float,
) -> str:
    """Classify an item-local point on an active axis spine into a gesture zone.

    Priority: grip (resize) > frame border (move) > interior (inner=zoom / outer=pan).
    Inner = right (plot-side); outer = left (window-edge side). The grip hit-area is
    the centred grip rect expanded by *tol* for grabbability (NOT a full-width band).
    """
    half = grip_w / 2.0
    in_grip_x = abs(lx - w / 2.0) <= half + tol
    if in_grip_x and ly <= grip_h + tol:
        return AXZONE_GRIP_TOP
    if in_grip_x and ly >= h - grip_h - tol:
        return AXZONE_GRIP_BOTTOM
    on_border = lx <= frame or lx >= w - frame or ly <= frame or ly >= h - frame
    if on_border:
        return AXZONE_FRAME
    return AXZONE_ZOOM if lx >= w / 2.0 else AXZONE_PAN
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_axis_zone_classify.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add -A && git commit -m "feat(gui-view): add classify_axis_zone pure function"
```

---

## Task 4: アクティブ軸状態 ＋ クリックでアクティブ化

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`GraphPanelView.__init__` に状態、`_AlignedAxisItem` に click→activate、`set_active_axis` API）
- Test: `tests/gui/test_axis_interaction.py`

**Interfaces:**
- Produces: `GraphPanelView._active_axis_index: int | None`、`GraphPanelView.set_active_axis(index: int | None) -> None`（再描画をトリガ）。`_AlignedAxisItem` は VM index を既に保持（`_vm_axis_index`）、クリックで親 View の `set_active_axis(self._vm_axis_index)` を呼ぶ。
- Consumes: `_AlignedAxisItem.set_vm_axis_index`（既存）。

- [ ] **Step 1: 失敗するテスト（Layer A/B：item の press がアクティブ化を呼ぶ）**

```python
# tests/gui/test_axis_interaction.py
import pytest

from valisync.gui.views.graph_panel_view import GraphPanelView
from tests.gui._panel_factory import make_two_axis_panel  # see helper note below


@pytest.fixture
def panel(qtbot):
    view = make_two_axis_panel()
    qtbot.addWidget(view)
    return view


def test_click_axis_sets_active(panel) -> None:
    assert panel._active_axis_index is None
    panel.set_active_axis(1)
    assert panel._active_axis_index == 1
    panel.set_active_axis(None)
    assert panel._active_axis_index is None
```

> ヘルパ `tests/gui/_panel_factory.py::make_two_axis_panel` は Task 4 の Step 3 で作成（既存 `test_graph_panel_multi_axis.py` の 2 軸構築を関数化。`GraphPanelVM(session)` + `add_signal_to_axis`/`create_new_axis`）。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_axis_interaction.py -v`
Expected: FAIL（`AttributeError: ... _active_axis_index` / ヘルパ未作成）

- [ ] **Step 3: 最小実装**

```python
# graph_panel_view.py GraphPanelView.__init__ (near other state)
self._active_axis_index: int | None = None
self._hover_axis_index: int | None = None
```
```python
# graph_panel_view.py GraphPanelView
def set_active_axis(self, index: int | None) -> None:
    """Set/clear the active axis (transient UI state) and repaint frames."""
    if index == self._active_axis_index:
        return
    self._active_axis_index = index
    for ax in self._y_axes:
        ax.update()  # repaint frame/grips
```
```python
# _AlignedAxisItem — activate on left click (no drag). Centralised gesture entry
# is added in Task 6; here we only wire activation so Task 4 is testable.
def mousePressEvent(self, ev) -> None:  # pyqtgraph passes a MouseClickEvent on click
    view = self.getViewWidget()
    if view is not None and self._vm_axis_index is not None:
        view.set_active_axis(self._vm_axis_index)
    ev.accept()
```
```python
# tests/gui/_panel_factory.py
from pathlib import Path
import tempfile
from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView


def make_two_axis_panel() -> GraphPanelView:
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1,s2"] + [f"{i*0.01:.3f},{i%50}.0,{(i*2)%50}.0" for i in range(50)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    session = Session()
    session.load(csv, FormatDefinition(
        name="fmt", delimiter=Delimiter.COMMA, timestamp_column=0,
        timestamp_unit="sec", signal_start_column=1, signal_end_column=2, has_header=True))
    keys = sorted(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(keys[0], 0)
    vm.create_new_axis(keys[1])
    return GraphPanelView(vm)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_axis_interaction.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add -A && git commit -m "feat(gui-view): active-axis state + click-to-activate"
```

---

## Task 5: hover→ゾーン別カーソル ＋ フレーム/グリップ描画

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`_AlignedAxisItem`: `setAcceptHoverEvents(True)`、`hoverMoveEvent`、`paint` 拡張、グリップ寸法定数）
- Test: `tests/gui/test_axis_interaction.py`（状態/カーソルの Layer A/B）。実カーソルは Task 10 realgui。

**Interfaces:**
- Produces: `_AlignedAxisItem` クラス定数 `GRIP_W=40.0, GRIP_H=8.0, FRAME=3.0, TOL=4.0`。`_AlignedAxisItem.cursor_for_local(lx, ly) -> Qt.CursorShape`（純: `classify_axis_zone` → カーソル）。アクティブ/ホバー時のみ paint でフレーム＋グリップを描く。
- Consumes: `classify_axis_zone`（Task 3）、`view._active_axis_index`/`set_hover_axis`。

- [ ] **Step 1: 失敗するテスト（Layer A：cursor_for_local のマッピング）**

```python
from PySide6.QtCore import Qt
from valisync.gui.views.graph_panel_view import _AlignedAxisItem


def _item(w=60.0, h=120.0):
    it = _AlignedAxisItem(orientation="left")
    it.setWidth(w)
    it._test_h = h  # height comes from geometry; helper returns h in cursor_for_local
    return it


def test_cursor_resize_move_zoom_pan():
    it = _item()
    h = 120.0
    assert it.cursor_for_local(30.0, 2.0, h) == Qt.CursorShape.SizeVerCursor   # grip
    assert it.cursor_for_local(2.0, 60.0, h) == Qt.CursorShape.SizeAllCursor   # frame=move
    assert it.cursor_for_local(45.0, 60.0, h) == Qt.CursorShape.CrossCursor    # zoom(inner)
    assert it.cursor_for_local(15.0, 60.0, h) == Qt.CursorShape.OpenHandCursor # pan(outer)
```

- [ ] **Step 2: 失敗を確認** → FAIL（`cursor_for_local` 未定義）

- [ ] **Step 3: 最小実装**

```python
# _AlignedAxisItem — class constants + cursor mapping + hover + paint
GRIP_W, GRIP_H, FRAME, TOL = 40.0, 8.0, 3.0, 4.0

def cursor_for_local(self, lx: float, ly: float, h: float) -> "Qt.CursorShape":
    from PySide6.QtCore import Qt
    z = classify_axis_zone(lx, ly, self.width(), h,
                           grip_w=self.GRIP_W, grip_h=self.GRIP_H,
                           frame=self.FRAME, tol=self.TOL)
    return {
        AXZONE_GRIP_TOP: Qt.CursorShape.SizeVerCursor,
        AXZONE_GRIP_BOTTOM: Qt.CursorShape.SizeVerCursor,
        AXZONE_FRAME: Qt.CursorShape.SizeAllCursor,
        AXZONE_ZOOM: Qt.CursorShape.CrossCursor,
        AXZONE_PAN: Qt.CursorShape.OpenHandCursor,
    }[z]

def _is_active_or_hover(self) -> bool:
    view = self.getViewWidget()
    if view is None or self._vm_axis_index is None:
        return False
    return self._vm_axis_index in (view._active_axis_index, view._hover_axis_index)
```
```python
# __init__ of _AlignedAxisItem (after super().__init__): self.setAcceptHoverEvents(True)

def hoverMoveEvent(self, ev) -> None:
    view = self.getViewWidget()
    if view is None or self._vm_axis_index is None:
        return
    view.set_hover_axis(self._vm_axis_index)
    if self._vm_axis_index == view._active_axis_index:
        p = ev.pos()
        self.setCursor(self.cursor_for_local(p.x(), p.y(), self.boundingRect().height()))
    else:
        self.unsetCursor()

def hoverLeaveEvent(self, ev) -> None:
    view = self.getViewWidget()
    if view is not None:
        view.set_hover_axis(None)
    self.unsetCursor()
```
```python
# paint override: draw frame + grips when active/hover (case C: spine outline only)
def paint(self, p, *args) -> None:
    super().paint(p, *args)
    if not self._is_active_or_hover():
        return
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPen
    r = self.boundingRect()
    p.setPen(QPen(QColor("#f59e0b"), 2))
    p.drawRect(r.adjusted(1, 1, -1, -1))
    if self._vm_axis_index == (self.getViewWidget()._active_axis_index):
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor("#b45309"), 1))
        cx = r.center().x()
        for cy in (r.top() + 1, r.bottom() - 1):
            p.drawRoundedRect(QRectF(cx - self.GRIP_W / 2, cy - self.GRIP_H / 2,
                                     self.GRIP_W, self.GRIP_H), 3, 3)
```
```python
# GraphPanelView.set_hover_axis (mirrors set_active_axis, repaint)
def set_hover_axis(self, index: int | None) -> None:
    if index == self._hover_axis_index:
        return
    self._hover_axis_index = index
    for ax in self._y_axes:
        ax.update()
```

- [ ] **Step 4: テストが通ることを確認** → `uv run pytest tests/gui/test_axis_interaction.py -v` PASS

- [ ] **Step 5: コミット**
```bash
git add -A && git commit -m "feat(gui-view): hover cursor + active-frame/grip paint on axis"
```

---

## Task 6: `_AlignedAxisItem` ドラッグ分岐（グリップ=リサイズ／枠線=移動／内=ズーム／外=パン）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`_AlignedAxisItem.mouseDragEvent` をゾーン分岐に置換）
- Test: `tests/gui/test_axis_interaction.py`（分岐ロジックの Layer B 直叩き）

**Interfaces:**
- Produces: `_AlignedAxisItem.mouseDragEvent` がアクティブ軸でのみゾーン別に分岐。
  - グリップ → `view.vm.resize_axis_edge(idx, "top"/"bottom", delta_ratio)`（`delta_ratio = ev.pos().y() 移動量 / panel_height`、`isStart` で基準辺決定）。
  - 枠線 → 既存の QDrag（`encode_axis_index`）を起動。
  - 内側 → 範囲選択ズーム: `isStart` で開始 Y データ、`isFinish` で `view.vm.set_axis_range(idx, y0, y1)`。
  - 外側 → パン: `set_axis_range(idx, lo+shift, hi+shift)`。
  - データ変換 `_local_y_to_data(ly, h, idx)`: ストリップ内線形（top=y_hi, bottom=y_lo、軸の現 `y_range`）。
- Consumes: `resize_axis_edge`/`set_axis_range`（Task 1/2）、`classify_axis_zone`（Task 3）、`encode_axis_index`（既存）。

- [ ] **Step 1: 失敗するテスト（Layer B：分岐ヘルパを直叩き）**

```python
def test_begin_drag_grip_bottom_calls_resize_edge(panel, monkeypatch):
    panel.set_active_axis(0)
    it = panel._y_axes[0]
    calls = []
    monkeypatch.setattr(panel.vm, "resize_axis_edge",
                        lambda i, e, d: calls.append((i, e, round(d, 4))))
    h = it.boundingRect().height()
    # start at bottom grip, drag down by 10px (panel height ~ master rect height)
    it._begin_axis_drag(it.width() / 2, h - 2.0)
    it._update_axis_drag(dy_pixels=10.0)
    assert calls and calls[0][0] == 0 and calls[0][1] == "bottom"


def test_begin_drag_inner_is_zoom(panel, monkeypatch):
    panel.set_active_axis(0)
    it = panel._y_axes[0]
    got = []
    monkeypatch.setattr(panel.vm, "set_axis_range",
                        lambda i, lo, hi: got.append((i, lo, hi)))
    h = it.boundingRect().height()
    it._begin_axis_drag(it.width() * 0.75, h * 0.2)   # inner=zoom
    it._finish_axis_drag(it.width() * 0.75, h * 0.8)
    assert got and got[0][0] == 0           # set_axis_range called on axis 0


def test_drag_ignored_when_not_active(panel, monkeypatch):
    panel.set_active_axis(None)
    it = panel._y_axes[0]
    fired = []
    monkeypatch.setattr(panel.vm, "resize_axis_edge", lambda *a: fired.append(a))
    started = it._begin_axis_drag(it.width() / 2, 2.0)
    assert started is False and not fired
```

- [ ] **Step 2: 失敗を確認** → FAIL（`_begin_axis_drag` 未定義）

- [ ] **Step 3: 最小実装**

`mouseDragEvent` を、`isStart` でゾーン判定して `_begin_axis_drag` に委譲し、中間で `_update_axis_drag`、`isFinish` で `_finish_axis_drag`/`resize` 確定 or QDrag 起動に振り分ける構造へ置換する。純粋に単体テスト可能な `_begin/_update/_finish` ヘルパへロジックを切り出す（イベントは座標を渡すだけ）。

```python
# _AlignedAxisItem
def _panel_height(self) -> float:
    return max(self.boundingRect().height(), 1.0)

def _local_y_to_data(self, ly: float, h: float) -> float:
    view = self.getViewWidget()
    rng = view.vm.axes[self._vm_axis_index].y_range or (0.0, 1.0)
    lo, hi = rng
    frac = min(max(ly / max(h, 1.0), 0.0), 1.0)  # 0=top, 1=bottom
    return hi - frac * (hi - lo)                  # top=hi, bottom=lo

def _begin_axis_drag(self, lx: float, ly: float) -> bool:
    view = self.getViewWidget()
    if view is None or self._vm_axis_index != view._active_axis_index:
        return False
    h = self.boundingRect().height()
    self._zone = classify_axis_zone(lx, ly, self.width(), h,
                                    grip_w=self.GRIP_W, grip_h=self.GRIP_H,
                                    frame=self.FRAME, tol=self.TOL)
    self._drag_start_data = self._local_y_to_data(ly, h)
    self._drag_h = h
    return True

def _update_axis_drag(self, dy_pixels: float) -> None:
    view = self.getViewWidget()
    if self._zone == AXZONE_GRIP_TOP:
        view.vm.resize_axis_edge(self._vm_axis_index, "top", dy_pixels / self._panel_height())
    elif self._zone == AXZONE_GRIP_BOTTOM:
        view.vm.resize_axis_edge(self._vm_axis_index, "bottom", dy_pixels / self._panel_height())

def _finish_axis_drag(self, lx: float, ly: float) -> None:
    view = self.getViewWidget()
    end = self._local_y_to_data(ly, self._drag_h)
    if self._zone == AXZONE_ZOOM:
        view.vm.set_axis_range(self._vm_axis_index, self._drag_start_data, end)
    elif self._zone == AXZONE_PAN:
        lo, hi = view.vm.axes[self._vm_axis_index].y_range or (0.0, 1.0)
        shift = self._drag_start_data - end
        view.vm.set_axis_range(self._vm_axis_index, lo + shift, hi + shift)
```
```python
# mouseDragEvent: route by zone. Grips/zoom/pan = direct drag; frame = QDrag move.
def mouseDragEvent(self, ev) -> None:
    from PySide6.QtCore import Qt
    if ev.button() != Qt.MouseButton.LeftButton:
        ev.ignore(); return
    if ev.isStart():
        p = ev.pos()
        if not self._begin_axis_drag(p.x(), p.y()):
            ev.ignore(); return
        if self._zone == AXZONE_FRAME:
            if self._vm_axis_index is not None:
                view = self.getViewWidget()
                drag = QDrag(view)
                drag.setMimeData(encode_axis_index(self._vm_axis_index))
                drag.exec(Qt.DropAction.MoveAction)
            ev.accept(); return
        self._last_y = ev.pos().y()
    if self._zone in (AXZONE_GRIP_TOP, AXZONE_GRIP_BOTTOM) and not ev.isStart():
        dy = ev.pos().y() - self._last_y
        self._last_y = ev.pos().y()
        self._update_axis_drag(dy)
    if ev.isFinish() and self._zone in (AXZONE_ZOOM, AXZONE_PAN):
        p = ev.pos()
        self._finish_axis_drag(p.x(), p.y())
    ev.accept()
```

- [ ] **Step 4: テストが通ることを確認** → PASS

- [ ] **Step 5: コミット**
```bash
git add -A && git commit -m "feat(gui-view): zone-routed axis drag (resize/move/zoom/pan)"
```

---

## Task 7: 連動ディバイダー撤去（`RegionDividerItem` 削除）

**Files:**
- Delete: `src/valisync/gui/views/region_divider_item.py`, `tests/gui/test_region_divider_item.py`
- Modify: `src/valisync/gui/views/graph_panel_view.py`（divider 生成ループ・`_position_dividers`・`self._dividers`・import 除去、`_sync_overlay_geometry` 末尾の `_position_dividers(R)` 呼び除去）
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（連動 `resize_axis` 削除）
- Modify: `tests/gui/test_graph_panel_multi_axis.py`（`test_dragging_divider_resizes_adjacent_regions`, `resize_axis` 系を削除／edge 版へ置換）

**Interfaces:**
- Removes: `RegionDividerItem`, `GraphPanelVM.resize_axis`, `GraphPanelView._dividers`, `_position_dividers`。

- [ ] **Step 1: 失敗するテスト（divider が生成されないことを Layer B で固定）**

```python
def test_no_dividers_created(panel) -> None:
    assert not hasattr(panel, "_dividers") or panel._dividers == []
    # _AlignedAxisItems still present for each axis
    assert len(panel._y_axes) == len(panel.vm.axes)
```

- [ ] **Step 2: 失敗を確認** → FAIL（現状 `_dividers` に要素が入る／属性が残る）

- [ ] **Step 3: 削除実装**

`git rm` でファイル削除。`graph_panel_view.py` の `_reconcile_axes` 内 divider 生成ブロック（`by_col` ループ）と `_position_dividers`、`self._dividers = []`、`from .region_divider_item import RegionDividerItem` を除去。`_sync_overlay_geometry` の `self._position_dividers(R)` 行を除去。`graph_panel_vm.py` の `resize_axis` メソッドを削除。

```bash
git rm src/valisync/gui/views/region_divider_item.py tests/gui/test_region_divider_item.py
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS（divider 依存テストは削除済み。残りは緑）

- [ ] **Step 5: コミット**
```bash
git add -A && git commit -m "refactor(gui): remove coupled RegionDividerItem and resize_axis"
```

---

## Task 8: widget レベル Y ゾーン・ホイール・ダブルクリック撤去（X は常時のまま）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`
- Test: `tests/gui/test_axis_interaction.py`

**Interfaces:**
- Removes: `GraphPanelView.wheelEvent`, `mouseDoubleClickEvent`、`mousePressEvent`/`mouseReleaseEvent` の Y ゾーン分岐（`ZONE_Y_*`）。`classify_zone` は X 専用に縮退（Y ストリップは `_AlignedAxisItem` が処理）。X の `apply_zone_drag`（X_INNER/X_OUTER）は維持。

- [ ] **Step 1: 失敗するテスト（Y ゾーンドラッグは widget レベルで起きない＝アクティブ軸経由のみ）**

```python
def test_widget_has_no_wheel_or_doubleclick_zoom(panel) -> None:
    # wheel/double-click handlers removed (no Y/X wheel zoom, no dbl reset)
    assert "wheelEvent" not in type(panel).__dict__
    assert "mouseDoubleClickEvent" not in type(panel).__dict__
```

- [ ] **Step 2: 失敗を確認** → FAIL（現状ハンドラ有り）

- [ ] **Step 3: 実装**

`wheelEvent` と `mouseDoubleClickEvent` を削除。`mousePressEvent`/`mouseReleaseEvent` から `ZONE_Y_*` 分岐を除去し、X ゾーン（`ZONE_X_*`）のみ残す。`_WHEEL_IN/_WHEEL_OUT` 定数と `apply_zone_wheel`/`reset_zone` を削除（X 用の `apply_zone_drag` は残す）。`cursor_for_zone`/`classify_zone` は X 判定のみ使用。

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS

- [ ] **Step 5: コミット**
```bash
git add -A && git commit -m "refactor(gui): drop widget-level Y-zone, wheel, double-click (axis-item owns Y)"
```

---

## Task 9: Layer C realgui — グリップ実リサイズ

**Files:**
- Create: `tests/realgui/test_active_axis_resize.py`

**Interfaces:**
- Consumes: `_AlignedAxisItem`（グリップ）、`resize_axis_edge`、`_sync_overlay_geometry`（描画ストリップ）。
- 駆動: QDrag 不使用＝OLE ハング無し。`mouse_event` の press→move(複数)→release を**メインスレッドで** `processEvents` を挟みつつ注入可（背景スレッド不要）。DPI 変換は `devicePixelRatioF`。

- [ ] **Step 1: テストを書く（②描画ストリップを assert／VM 値だけは不可）**

```python
"""Layer C: real-OS grip drag resizes only the active axis (model B)."""
from __future__ import annotations
import contextlib, ctypes, sys, time
from pathlib import Path
import pytest
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.realgui
_MOVE, _LDOWN, _LUP = 0x0001, 0x0002, 0x0004


def test_grip_drag_resizes_only_active_axis(qtbot: QtBot, tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("real OS input is Windows-only")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    if QGuiApplication.platformName() == "offscreen":
        pytest.skip("requires a real display — run: uv run pytest --realgui tests/realgui/")
    from tests.gui._panel_factory import make_two_axis_panel

    user32 = ctypes.windll.user32
    view = make_two_axis_panel()
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 800, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000)

    view.set_active_axis(0)  # activate top axis
    QApplication.processEvents()

    R = view._view_boxes[0].sceneBoundingRect()
    def strip(i): 
        r = view._y_axes[i].sceneBoundingRect(); return ((r.y()-R.y())/R.height(), r.height()/R.height())
    top0, h0 = strip(0); top1, h1 = strip(1)

    # bottom grip of axis 0 = bottom-centre of its spine
    spine0 = view._y_axes[0].sceneBoundingRect()
    grip_scene = QPoint(int(spine0.center().x()), int(spine0.bottom() - 2))
    vp = view.plot_widget.mapFromScene(grip_scene)
    g = view.plot_widget.viewport().mapToGlobal(vp)
    dpr = view.devicePixelRatioF()
    gx, gy = round(g.x()*dpr), round(g.y()*dpr)

    def at(x, y, f): user32.SetCursorPos(int(x), int(y)); user32.mouse_event(f, 0, 0, 0, 0)
    at(gx, gy, _LDOWN); time.sleep(0.05)
    for k in range(1, 6):                       # drag DOWN ~60px to grow axis 0
        at(gx, gy + k*12, _MOVE); QApplication.processEvents(); time.sleep(0.03)
    at(gx, gy + 60, _LUP)
    for _ in range(4): QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "after_resize.png"))

    ntop0, nh0 = strip(0); ntop1, nh1 = strip(1)
    assert nh0 > h0 + 0.03, f"active axis 0 did not grow (screens: {tmp_path})"   # rendered
    assert ntop0 == pytest.approx(top0, abs=0.02)                                  # top edge fixed
    assert nh1 == pytest.approx(h1, abs=0.02), "neighbour height changed (model B violated)"
```

- [ ] **Step 2: 実機で実行（証拠ゲート）**

Run: `uv run pytest --realgui tests/realgui/test_active_axis_resize.py -v`
Expected: PASS（スクショ `after_resize.png` 保存）。**非 Windows/ディスプレイ無しはゲート未充足**。

- [ ] **Step 3: コミット**
```bash
git add -A && git commit -m "test(realgui): grip drag resizes only active axis (model B)"
```

---

## Task 10: Layer C realgui — 内側ズーム / 外側パン ＋ カーソル

**Files:**
- Create: `tests/realgui/test_active_axis_zoom_pan.py`

**Interfaces:**
- ②実質性: 内側ドラッグ後に `_y_axes[0].range`（AxisItem の実レンジ）が**縮む**こと（範囲選択ズームイン）、外側ドラッグ後に**シフト**すること。カーソル形状 `view.cursor().shape()` がゾーン別であること（hover を `mouse_event(_MOVE)` で移動させて観測）。

- [ ] **Step 1: テストを書く**

```python
"""Layer C: inner drag = range-select zoom-in, outer drag = pan, on active axis only."""
from __future__ import annotations
import ctypes, sys, time
from pathlib import Path
import pytest
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.realgui
_MOVE, _LDOWN, _LUP = 0x0001, 0x0002, 0x0004


def test_inner_drag_zooms_in_on_active_axis(qtbot: QtBot, tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows-only")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    if QGuiApplication.platformName() == "offscreen":
        pytest.skip("requires a real display")
    from tests.gui._panel_factory import make_two_axis_panel

    user32 = ctypes.windll.user32
    view = make_two_axis_panel()
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 800, 600); view.show(); qtbot.waitExposed(view)
    for _ in range(3): QApplication.processEvents()
    qtbot.waitUntil(lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000)
    view.set_active_axis(0); QApplication.processEvents()

    before = view._y_axes[0].range[1] - view._y_axes[0].range[0]
    spine0 = view._y_axes[0].sceneBoundingRect()
    # inner = right half of spine (plot-side)
    inner_x = spine0.x() + spine0.width() * 0.75
    y_top = spine0.y() + spine0.height() * 0.30
    y_bot = spine0.y() + spine0.height() * 0.70
    dpr = view.devicePixelRatioF()
    def to_phys(sx, sy):
        vp = view.plot_widget.mapFromScene(QPoint(int(sx), int(sy)))
        g = view.plot_widget.viewport().mapToGlobal(vp)
        return round(g.x()*dpr), round(g.y()*dpr)
    x0, ya = to_phys(inner_x, y_top); _, yb = to_phys(inner_x, y_bot)

    def at(x, y, f): user32.SetCursorPos(int(x), int(y)); user32.mouse_event(f, 0, 0, 0, 0)
    at(x0, ya, _LDOWN); time.sleep(0.05)
    at(x0, (ya+yb)//2, _MOVE); QApplication.processEvents(); time.sleep(0.05)
    at(x0, yb, _MOVE); QApplication.processEvents(); time.sleep(0.05)
    at(x0, yb, _LUP)
    for _ in range(4): QApplication.processEvents()
    QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "after_zoom.png"))

    after = view._y_axes[0].range[1] - view._y_axes[0].range[0]
    assert after < before * 0.9, f"inner drag did not zoom in (screens: {tmp_path})"
```

> パン版 `test_outer_drag_pans_on_active_axis` も同型で追加（外側=左 25% を縦ドラッグ→`range` 中心がシフト、span は不変）。カーソル観測テスト `test_cursor_changes_per_zone`（hover を `_MOVE` で各ゾーンへ→`view.cursor().shape()` が SizeVer/SizeAll/Cross/OpenHand）を追加。

- [ ] **Step 2: 実機で実行（証拠ゲート）**

Run: `uv run pytest --realgui tests/realgui/test_active_axis_zoom_pan.py -v`
Expected: PASS（`after_zoom.png` 保存）。

- [ ] **Step 3: コミット**
```bash
git add -A && git commit -m "test(realgui): inner=zoom-in / outer=pan / per-zone cursor on active axis"
```

---

## Task 11: Layer C realgui — 移動（アクティブ化→枠線ドラッグ）

**Files:**
- Modify: `tests/realgui/test_multi_column_axis.py`

**Interfaces:**
- 既存の移動 realgui を、新ジェスチャ「**まず `set_active_axis` でアクティブ化→スパイン枠線（中心ではなく端＝frame zone）から QDrag**」へ更新。背景スレッド＋watchdog の駆動は既存踏襲。

- [ ] **Step 1: テスト更新**

開始前に `view.set_active_axis(0)` を追加。press 位置を `src_item.sceneBoundingRect()` の**枠線（左端から FRAME px 内側、中心 Y）**へ変更（グリップと内/外を避け frame zone を確実に掴む）。それ以外（背景スレッド駆動・watchdog・drop_seen・描画ストリップ assert）は現行どおり。

```python
# after view.show()/waitExposed and layout settle:
view.set_active_axis(0)
QApplication.processEvents()
# source point = frame band of axis 0 spine (left edge, vertical centre)
spine = view._y_axes[0].sceneBoundingRect()
scene_center = QPoint(int(spine.x() + 2), int(spine.center().y()))  # frame zone (move)
```

- [ ] **Step 2: 実機で実行（証拠ゲート）**

Run: `uv run pytest --realgui tests/realgui/test_multi_column_axis.py -v`
Expected: PASS（`after_drag.png`）。

- [ ] **Step 3: コミット**
```bash
git add -A && git commit -m "test(realgui): axis move via activate + frame-zone QDrag"
```

---

## Task 12: 仕上げ（品質ゲート・設計同期）

**Files:** 横断

- [ ] **Step 1: 全ゲート**
```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
```
Expected: 全 PASS（realgui は既定 skip）。

- [ ] **Step 2: `/gui-verify` で realgui 証拠ゲートを scoped 実行**（タスク9–11 の3本＋スクショ/ログ添付）。

- [ ] **Step 3: 設計同期**
`docs/superpowers/specs/2026-06-28-...-design.md` と実装の差分が出たら spec を追補。`.kiro/specs/valisync-gui-axes/` の要件がずれる場合は `design.md`/`tasks.md` 更新をユーザーに確認。CLAUDE.md Phase 状況の更新候補をユーザーに確認。

- [ ] **Step 4: コミット**
```bash
git add -A && git commit -m "chore: quality gate + spec sync for per-axis resize"
```

---

## Self-Review（spec 突合）

- **§3 受け入れ要件** → Task 1（モデルB制約3つ）/ 4–6（アクティブ・ゾーン・分岐）/ 8（wheel/dblclick撤去）/ 1・7（divider撤去）で網羅。
- **§5 モデルB数式** → Task 1 のクランプ（min/隣接/逆端）で実装＋5テスト。
- **§6 per-axis ズーム/パン** → Task 2 `set_axis_range` ＋ Task 6 内/外分岐 ＋ refresh の per-axis 適用（既存 338–343）。
- **§9 暫定（ズームインのみ）/ リセット後回し** → Task 6 は内側=範囲選択（イン）のみ。reset_x/y は残置（入口無し）。
- **§10 テスト戦略** → Task 9–11 realgui（②描画/レンジ/カーソルを assert、①証拠ゲート）。
- 型整合: `resize_axis_edge(idx, edge, delta)`・`set_axis_range(idx, lo, hi)`・`classify_axis_zone(...)`・`AXZONE_*` を全タスクで一貫使用。
- placeholder 無し（各 step に実コード/実コマンド）。

> 既知の honest layering: Task 6 の `_begin/_update/_finish` 直叩きは Layer B（分岐ロジック）であり、カーソル・実ドラッグ起動・QDrag 配送は Task 9–11 の realgui でのみ証明される。
