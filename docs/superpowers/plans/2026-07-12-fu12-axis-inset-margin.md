# FU-12 軸境界データ張り付き解消（ストリップ・インセット余白）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** auto-fit / 手動ズーム済み軸で、値がレンジ境界（min/max）に一致するデータ区間（例 `Radar.Obj0.dx` の定数 y=45=軸min）がプロット枠に張り付いて視認不可になる FU-12 を、描画層で各軸 strip を上下 `m=3%` 内側へ寄せて解消する。

**Architecture:** `y_range` は実データ範囲のまま（正直）保ち、レンダリング層で各軸のリージョン strip を `m` だけインセットする（どの軸も真のフルハイトにしない）。インセット比率 `effective_region(margin)` を `YAxisVM` の純関数として単一ソース化し、`calculate_virtual_range`（ViewBox 仮想レンジ）と `_sync_overlay_geometry`（スパイン strip geometry）の**両方**が同一の view 側定数 `AXIS_INSET_MARGIN` を注入して消費する。曲線は自軸データ範囲にクリップして余白帯を空に保つ。

**Tech Stack:** PySide6 / pyqtgraph 0.14 / numpy、MVVM（`Observable`）、pytest-qt（Layer A/B）＋ realgui（Layer C）。

## Global Constraints

- **core は Qt 非依存**（`YAxisVM`/`graph_panel_vm.py` は pyqtgraph/PySide を import しない）。`margin` は view 側から注入し VM は純粋を保つ。
- **インセット数式は乗算**: `effective_top = top + m*height`, `effective_height = height*(1-2m)`。**絶対値 `height-2m` は禁止**（`MIN_H=0.05 < 2m=0.06` で負→仮想スパン爆発の実バグ）。
- **単一ソース**: `m` の値リテラルは view 定数 `AXIS_INSET_MARGIN` の1箇所のみ。インセット式は `YAxisVM.effective_region` の1箇所のみ。両サイトがこれを消費。片側だけインセットは tick ドリフトの唯一の誤描画経路。
- **インセットするのは2箇所だけ**: `calculate_virtual_range` と `_sync_overlay_geometry` のスパイン strip。**以下の model 比率ヒットテスト群はインセットしない**（インセットするとデッドゾーン）: `_axis_index_at`（graph_panel_view.py:1521-1523）・`_axis_drop_target`（:1545）・`_update_axis_move_feedback`・グリップ数学 `_grip_grab_offset`/`_update_axis_drag`（:547-552,570-572）・ディバイダー境界。
- **Y のみ**。`reset_x`/X 処理・`_padded_range`/RN-05・`set_axis_range` の正確値保持は不変。
- `margin=0.0` 既定で既存挙動はバイト等価（後方互換）。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過でコミット。
- コミットメッセージ末尾に `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` と `Claude-Session:` トレーラ。

## E2E 十分性（gui-test-plan 分析・タスクへ織込済み）

- **ジャーニー**: 開く→信号をプロット→（auto-fit / 手動ズーム）→**境界値データがフレームから浮いて見える**。触れる区間はプロット表示・軸操作。
- **効果ごとの observable**: ①境界データがフレームから分離（描画 E2E＝ViewBox mapView→scene 幾何アサート＋realgui スクショ）／②スパイン目盛りは実データ範囲のまま（Layer B）／③余白帯が空＝範囲外滲みなし（Layer B masked-data＋realgui 手動ズームスクショ）／④ヒットテスト（グリップ/ゾーン/軸クリック/軸D&D）無回帰（realgui 再監査）。
- **prod スケール**: 本 FU は幾何修正でスケール非依存。realgui は現実ウィンドウサイズ（1000×700 相当）の実ディスプレイで撮る。330k は不要。
- **ゾーン境界注意**: model ヒットテスト境界は不変（意図的に非インセット）だが、**視覚スパインが m 移動**するため realgui の掴み点は live geometry から再計算される→掴み点の move/QDrag ゾーン誤侵入はアサート失敗でなくハング。Task 4 で全掴み点を境界マージン再監査（memory [[gui_realgui_grip_drag_small_steps]]）。

## File Structure

- `src/valisync/gui/viewmodels/y_axis_vm.py` — `effective_region(margin)` 純関数を追加、`calculate_virtual_range(margin=0.0)` へ委譲（VM 純粋維持）。
- `src/valisync/gui/views/graph_panel_view.py` — 定数 `AXIS_INSET_MARGIN=0.03`、render loop の `calculate_virtual_range` 呼び出しに注入、`_sync_overlay_geometry` のスパイン strip をインセット、曲線クリップを render loop に追加。
- `tests/gui/test_y_axis_vm.py` — 新規 margin>0 ケース（Layer A）。既存 `test_calculate_virtual_range` は margin 既定 0 で不変。
- `tests/gui/test_graph_panel_render_geometry.py` — 既存 geometry 契約テストの意図的更新（インセット期待値）＋アライメント guard 厳格化（abs 0.03→0.005）＋新規 FU-12 ViewBox 受け入れ（auto+manual）＋クリップ Layer B。
- `tests/realgui/test_fu12_boundary_data_visible.py`（新規）— 実ディスプレイで境界データがフレームから浮くことのピクセル走査＋スクショ。
- 更新（意図的 divergence・grep 後）: `tests/realgui/test_move_then_resize.py`・`tests/realgui/test_click_activate_axis.py`（スパイン strip 期待値）。

---

### Task 1: VM インセット数式（`effective_region` ＋ `calculate_virtual_range(margin)`）

**Files:**
- Modify: `src/valisync/gui/viewmodels/y_axis_vm.py:39-59`
- Test: `tests/gui/test_y_axis_vm.py`

**Interfaces:**
- Produces: `YAxisVM.effective_region(margin: float = 0.0) -> tuple[float, float]`（`(eff_top, eff_height)`）／`YAxisVM.calculate_virtual_range(margin: float = 0.0) -> tuple[float, float]`（既存シグネチャに `margin` キーワード追加・既定 0.0）。
- Consumes: なし（純関数）。

- [ ] **Step 1: 失敗テストを書く** — `tests/gui/test_y_axis_vm.py` の末尾に追加:

```python
def test_calculate_virtual_range_margin_zero_is_identity_backcompat() -> None:
    """margin 既定 0.0 では従来の恒等マッピング（後方互換）。"""
    axis = YAxisVM(y_range=(0.0, 100.0), top_ratio=0.0, height_ratio=1.0)
    v_lo, v_hi = axis.calculate_virtual_range()
    assert (v_lo, v_hi) == pytest.approx((0.0, 100.0))


def test_calculate_virtual_range_margin_insets_full_height_axis() -> None:
    """FU-12: margin>0 でフルハイト軸が恒等でなくなり、境界値データが仮想レンジの
    内側（下端から m・上端から m）に着地する。"""
    axis = YAxisVM(y_range=(45.0, 100.0), top_ratio=0.0, height_ratio=1.0)
    v_lo, v_hi = axis.calculate_virtual_range(margin=0.03)
    assert v_lo < 45.0  # y_min は下フレームから浮く
    assert v_hi > 100.0  # y_max は上フレームから浮く
    span = v_hi - v_lo
    assert (45.0 - v_lo) / span == pytest.approx(0.03, abs=1e-6)
    assert (100.0 - v_lo) / span == pytest.approx(0.97, abs=1e-6)


def test_effective_region_multiplicative_survives_min_height() -> None:
    """MIN_H=0.05 (< 2*0.03) の軸で eff_height が負にならない（絶対値 height-2m の
    バグを乗算 height*(1-2m) で回避）。"""
    axis = YAxisVM(top_ratio=0.0, height_ratio=0.05)
    eff_top, eff_h = axis.effective_region(margin=0.03)
    assert eff_h > 0.0
    assert eff_h == pytest.approx(0.05 * (1.0 - 0.06))
    assert eff_top == pytest.approx(0.0 + 0.03 * 0.05)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_y_axis_vm.py -q`
Expected: FAIL（`calculate_virtual_range()` に `margin` 引数が無い / `effective_region` 未定義）

- [ ] **Step 3: 最小実装** — `y_axis_vm.py` の `calculate_virtual_range` を差し替え、直前に `effective_region` を追加:

```python
    def effective_region(self, margin: float = 0.0) -> tuple[float, float]:
        """このリージョンを各辺 *margin*（自身の高さの割合）だけ内側へ寄せた
        ``(top, height)`` を返す。

        どの軸も真のフルハイトにしないことで、境界値データがプロット枠に乗らない
        （FU-12）。高さは**乗算** ``height*(1-2m)`` ── ``height-2m`` は
        ``height < 2*margin`` で負になり仮想スパンが爆発する。margin=0.0 は
        model 比率をそのまま返す（後方互換）。
        """
        eff_top = self.top_ratio + margin * self.height_ratio
        eff_height = max(self.height_ratio * (1.0 - 2.0 * margin), 1e-9)
        return (eff_top, eff_height)

    def calculate_virtual_range(self, margin: float = 0.0) -> tuple[float, float]:
        """Calculate the full ViewBox Y-range to map [y_lo, y_hi] to this region.

        This implements the 'unclipped overlay' mapping. The full ViewBox
        occupies the entire panel; we set its Y-range such that the data range
        [y_min, y_max] corresponds to the vertical strip [top_ratio, top_ratio+height].

        *margin* insets the strip (FU-12): with margin>0 the data band lands
        ``margin`` of the strip's height inside each edge, so boundary-valued
        data never coincides with the plot frame.

        top_ratio is 0.0 at the top of the panel and 1.0 at the bottom.
        Pyqtgraph Y-axis increases upwards (0.0 at bottom).
        """
        y_min, y_max = self.y_range if self.y_range is not None else (0.0, 1.0)
        span = max(y_max - y_min, 1e-9)
        eff_top, eff_height = self.effective_region(margin)

        v_hi = y_max + eff_top * span / eff_height
        v_lo = y_max - (1.0 - eff_top) * span / eff_height

        return (v_lo, v_hi)
```

- [ ] **Step 4: 全 VM テストが通ることを確認**

Run: `uv run pytest tests/gui/test_y_axis_vm.py -q`
Expected: PASS（新規3件＋既存 `test_calculate_virtual_range` パラメトリック4件＝margin 既定0で不変）

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/viewmodels/y_axis_vm.py tests/gui/test_y_axis_vm.py
git commit -m "feat(gui): YAxisVM.effective_region で軸 strip インセット数式を追加（FU-12 土台・margin 既定0で後方互換）"
```

---

### Task 2: View インセット配線（2サイト）＋ Layer B 幾何 ＋ 既存契約テスト更新 ＋ FU-12 受け入れ

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（モジュール定数追加・render loop :957・`_sync_overlay_geometry` :997-1003）
- Test: `tests/gui/test_graph_panel_render_geometry.py`（既存更新＋新規）

**Interfaces:**
- Consumes: `YAxisVM.effective_region` / `calculate_virtual_range(margin)`（Task 1）。
- Produces: モジュール定数 `AXIS_INSET_MARGIN: float`（=0.03）。

- [ ] **Step 1: 既存アライメント guard を厳格化 ＋ 新規 FU-12 受け入れテストを書く** — `tests/gui/test_graph_panel_render_geometry.py` を編集。

(a) `test_waveform_data_band_coincides_with_axis_spine_strip` 内の2つの `abs=0.03` を `abs=0.005` に変更（データ帯とスパインは同一 m でインセットされ厳密に一致する＝片側インセットのバグを検出可能にする）。

(b) 末尾に新規テストを追加（`AXIS_INSET_MARGIN` を import）:

```python
def test_boundary_data_lifts_off_frame_autofit(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-12: フルハイト軸のオートフィットで、データ最小値がプロット下枠に張り付かず
    strip の m 内側に描かれる（報告バグそのもの）。"""
    from PySide6.QtCore import QPointF

    from valisync.gui.views.graph_panel_view import AXIS_INSET_MARGIN

    session, _ = _loaded_session(tmp_path, n_signals=1)
    keys = sorted(_keys(session))
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])  # 単一フルハイト軸・auto-fit
    view = _mounted(qtbot, vm)

    assert vm.axes[0].y_range is not None
    y_lo, y_hi = vm.axes[0].y_range
    R = _plot_rect(view)
    vb = view._view_boxes[0]
    data_bot = vb.mapViewToScene(QPointF(0.0, y_lo)).y()
    data_top = vb.mapViewToScene(QPointF(0.0, y_hi)).y()
    frame_bot = R.y() + R.height()
    frame_top = R.y()
    # 下枠・上枠の双方から少なくとも nominal margin の半分は浮く（full-height h=1）。
    assert frame_bot - data_bot >= 0.5 * AXIS_INSET_MARGIN * R.height()
    assert data_top - frame_top >= 0.5 * AXIS_INSET_MARGIN * R.height()


def test_boundary_data_lifts_off_frame_manual_range(qtbot: QtBot, tmp_path: Path) -> None:
    """C は手動ズームも救う（A/_padded_range は救えない）: set_axis_range で min が
    データ値と一致する正確レンジを与えても、その値はフレームから浮く。"""
    from PySide6.QtCore import QPointF

    from valisync.gui.views.graph_panel_view import AXIS_INSET_MARGIN

    session, _ = _loaded_session(tmp_path, n_signals=1)
    keys = sorted(_keys(session))
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])
    view = _mounted(qtbot, vm)
    assert vm.axes[0].y_range is not None
    y_lo, y_hi = vm.axes[0].y_range
    vm.set_axis_range(0, y_lo, y_hi)  # 正確値（pad なし）を手動設定
    view.refresh()

    R = _plot_rect(view)
    vb = view._view_boxes[0]
    data_bot = vb.mapViewToScene(QPointF(0.0, y_lo)).y()
    frame_bot = R.y() + R.height()
    assert frame_bot - data_bot >= 0.5 * AXIS_INSET_MARGIN * R.height()
```

- [ ] **Step 2: 失敗を確認**（インセット未実装なので浮かない＝新規2件 FAIL・厳格化した既存も片側検証で FAIL しうる）

Run: `uv run pytest tests/gui/test_graph_panel_render_geometry.py -q`
Expected: FAIL（`frame_bot - data_bot` が ~0＝インセット未実装。`ImportError: AXIS_INSET_MARGIN` の場合もこの段階では期待どおり）

- [ ] **Step 3: View にインセットを実装** — `graph_panel_view.py`。

(a) モジュール先頭付近（他のモジュール定数 `_Y_AXIS_FIXED_WIDTH` 等の近く）に定数を追加:

```python
# FU-12: 各 Y 軸リージョンをその高さの 3% だけ上下に内側へ寄せる。どの軸も真の
# フルハイトにしないことで、レンジ境界に一致するデータがプロット枠に張り付いて
# 見えなくなるのを防ぐ。calculate_virtual_range と _sync_overlay_geometry の両方が
# この単一の値を YAxisVM.effective_region 経由で消費する（片側だけの適用は禁止）。
AXIS_INSET_MARGIN: float = 0.03
```

(b) render loop の仮想レンジ呼び出し（現 :957）に margin を注入:

```python
                full_lo, full_hi = axis_vm.calculate_virtual_range(AXIS_INSET_MARGIN)
```

(c) `_sync_overlay_geometry` のスパイン strip（現 :997-1003）をインセット比率で構築:

```python
            eff_top, eff_height = axis_vm.effective_region(AXIS_INSET_MARGIN)
            strip = QRectF(
                band.x(),
                R.y() + eff_top * R.height(),
                band.width(),
                eff_height * R.height(),
            )
            self._y_axes[i].setGeometry(strip)
```

- [ ] **Step 4: 新規 FU-12 受け入れ＋厳格化アライメントが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_panel_render_geometry.py -q`
Expected: 新規2件 PASS・`test_waveform_data_band_coincides_with_axis_spine_strip`（abs=0.005）PASS。既存の絶対 strip 位置テスト（下記）は strip 移動で FAIL する → Step 5 で意図的更新。

- [ ] **Step 5: 既存の絶対 strip 契約テストを意図的に更新**（deliberate divergence — スパインは m インセットされたので model 位置ではなくインセット位置に描かれる）。

`test_axis_spines_render_at_absolute_strips_with_blank_gap`（現 :86-89）— survivors A(top=0,h=0.5)/C(top=0.8,h=0.2) のインセット期待値へ:

```python
    # インセット後（FU-12）: 各リージョンは自高さの AXIS_INSET_MARGIN=0.03 だけ内側。
    # A: top 0.0+0.03*0.5=0.015, h 0.5*0.94=0.47 / C: top 0.8+0.03*0.2=0.806, h 0.2*0.94=0.188
    assert a_top == pytest.approx(0.015, abs=0.01)
    assert a_h == pytest.approx(0.47, abs=0.01)
    assert c_top == pytest.approx(0.806, abs=0.01)
    assert c_h == pytest.approx(0.188, abs=0.01)
```

`test_axis_spine_renders_at_absolute_strip`（現 :111-115）— top=0.0→0.021・top=0.7→0.709 へ:

```python
    # インセット位置（top + 0.03*height）。axis0: 0.0+0.03*0.7=0.021 / axis1: 0.7+0.03*0.3=0.709
    for i, expected_top in ((0, 0.021), (1, 0.709)):
        top_frac, _h = _strip_of_axis(view, i)
        assert top_frac == pytest.approx(expected_top, abs=0.01), (
            f"axis {i} spine not at its inset strip (got {top_frac})"
        )
```

`test_region_geometry_follows_resize`（現 :131-136）— 同様にインセット期待値へ:

```python
    top0, h0 = _strip_of_axis(view, 0)
    assert top0 == pytest.approx(0.021, abs=0.01)  # 0.0 + 0.03*0.7
    assert h0 == pytest.approx(0.7 * 0.94, abs=0.01)  # 0.658
    top1, h1 = _strip_of_axis(view, 1)
    assert top1 == pytest.approx(0.709, abs=0.01)  # 0.7 + 0.03*0.3
    assert h1 == pytest.approx(0.3 * 0.94, abs=0.01)  # 0.282
```

- [ ] **Step 6: tests/ 全域で旧 strip 式の stale アサートを grep**（memory [[gui_behavior_change_stale_parallel_realgui_test]]・[[gui_region_overlay_viewbox_fixed_axis_spine_height]]）— スパイン高さ/位置を `height_ratio*R.height` や `top_ratio*R.height` で検算している箇所を洗い出す:

Run:
```bash
grep -rn "height_ratio \* R\|top_ratio \* R\|height_ratio\*R\|sceneBoundingRect().height()" tests/ | grep -i "axis\|spine\|strip"
```
発見した Layer B/realgui のスパイン幾何アサートは同じインセット式へ更新（realgui は Task 4 でまとめて実機再監査）。この grep 結果はレビュー用にレポートへ記録。

- [ ] **Step 7: 全 headless GUI テスト＋ゲート**

Run: `uv run pytest tests/gui/ -q && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS

- [ ] **Step 8: コミット**

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_render_geometry.py
git commit -m "fix(gui): FU-12 軸 strip を m=3% インセットして境界データをフレームから浮かせる（仮想レンジ＋スパイン geometry の両サイト・単一ソース）"
```

---

### Task 3: 曲線クリップ（インセット余白帯を空に保つ）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py:927`（render loop の `setData`）
- Test: `tests/gui/test_graph_panel_render_geometry.py`（新規 Layer B）

**Interfaces:**
- Consumes: render loop の per-curve `axis_index` と `self.vm.axes[axis_index].y_range`。
- Produces: なし（描画挙動のみ）。

**設計判断（レビュー向け）**: 各曲線の描画値を自軸データ範囲 `[y_lo, y_hi]` で NaN マスクし、範囲外点を描かない（承認プロトタイプ fu12_fig3 の clipped と同一手法）。**オートフィットでは y_lo/y_hi がデータの min/max ゆえマスクは no-op**（挙動不変）。手動ズーム時のみ範囲外を余白帯から除去。マスクは格納データ（`getData()`/`curve_xy()`）に反映される＝範囲外セグメントは非ヒット化する（`_curve_at`）。オフセットドラッグは X シフトのみで Y レンジ帰属は不変ゆえ整合。既存 unclipped-overlay の跨ぎ滲みも止まる（承認済み honest-margin の帰結）。

- [ ] **Step 1: 失敗テストを書く** — `tests/gui/test_graph_panel_render_geometry.py` 末尾:

```python
def test_curve_clipped_to_axis_range_keeps_margins_empty(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """手動ズームで範囲外点が NaN マスクされ、インセット余白帯に範囲外データが
    滲まない（FU-12 honest margins）。オートフィットではマスク無し（no-op）。"""
    import numpy as np

    session, _ = _loaded_session(tmp_path, n_signals=1)
    keys = sorted(_keys(session))
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])
    view = _mounted(qtbot, vm)

    eid = view.curve_keys()[0]
    _, ys0 = view.curve_xy(eid)  # auto-fit: 全点有限（マスク無し）
    ys0 = np.asarray(ys0, dtype=float)
    assert np.isfinite(ys0).all(), "オートフィットで点がマスクされた（no-op のはず）"

    lo, hi = float(np.nanmin(ys0)), float(np.nanmax(ys0))
    mid = (lo + hi) / 2.0
    vm.set_axis_range(0, mid, hi)  # 上半分へズーム → 下半分が範囲外
    view.refresh()

    _, ys1 = view.curve_xy(eid)
    ys1 = np.asarray(ys1, dtype=float)
    assert np.isnan(ys1).any(), "範囲外点が未マスク＝余白帯に範囲外データが滲む"
    finite = ys1[np.isfinite(ys1)]
    assert finite.size > 0
    assert finite.min() >= mid - 1e-9  # 残った点は全て範囲内
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_render_geometry.py::test_curve_clipped_to_axis_range_keeps_margins_empty -q`
Expected: FAIL（クリップ未実装で `np.isnan(ys1).any()` が False）

- [ ] **Step 3: 最小実装** — render loop の現 `item.setData(curve.timestamps, curve.values)`（:927）を、自軸レンジでのマスクに差し替え:

```python
            # FU-12 クリップ: インセット余白帯を空に保つため、この軸のデータ範囲外の
            # 点を NaN にして描かない。オートフィット（range==データ extents）では
            # 全点が範囲内ゆえ no-op。範囲外セグメントは非ヒット化する（描かれない箇所は
            # クリックできない＝正しい）。
            vals = np.asarray(curve.values, dtype=float)
            ax = (
                self.vm.axes[curve.axis_index]
                if curve.axis_index < len(self.vm.axes)
                else None
            )
            if ax is not None and ax.y_range is not None:
                y_lo, y_hi = ax.y_range
                vals = np.where((vals < y_lo) | (vals > y_hi), np.nan, vals)
            item.setData(curve.timestamps, vals)
```

（`np` は既存 import を使用。既存 import が無ければ `import numpy as np` を追加。）

- [ ] **Step 4: 通過を確認 ＋ オフセットドラッグ/曲線ヒット無回帰**

Run: `uv run pytest tests/gui/test_graph_panel_render_geometry.py tests/gui/test_graph_panel_view.py -q`
Expected: 全 PASS（新規クリップ＋既存の曲線/オフセット系無回帰）

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_render_geometry.py
git commit -m "fix(gui): FU-12 曲線を自軸データ範囲にクリップしインセット余白帯を空に保つ（auto-fit は no-op）"
```

---

### Task 4: realgui ①ゲート証拠（境界データ可視）＋ 掴み点再監査

**Files:**
- Create: `tests/realgui/test_fu12_boundary_data_visible.py`
- Update（意図的・実機再監査）: `tests/realgui/test_move_then_resize.py`・`tests/realgui/test_click_activate_axis.py`（スパイン strip 期待値がインセットで変化した箇所のみ）

**Interfaces:**
- Consumes: `tests/realgui/conftest.py` の共有ヘルパ（実 OS 入力・QSettings 隔離・grabWindow）。
- Produces: 実ディスプレイのスクショ証拠（①ゲート）。

**分類**: 描画 E2E（入力なし）。observable は実ディスプレイのスクショ上で境界曲線ピクセルがフレーム行より内側にある（視覚判定）＋自動ピクセル走査の backstop。

- [ ] **Step 1: 実機ピクセル走査テストを書く** — `tests/realgui/test_fu12_boundary_data_visible.py`。実ウィンドウを `QT_QPA_PLATFORM=windows` で表示し、境界値=軸 min の状態にして window を grab、プロット下端付近の曲線色ピクセルの最下行がフレーム下端より内側（≈ m*plot_height 上）にあることをアサート。既存 realgui スケルトン（`tests/realgui/test_click_activate_axis.py` 等）の mount/grab パターンに合わせる:

```python
"""Layer C (realgui): FU-12 — 境界値データが実ディスプレイでプロット枠から浮く。

実ウィンドウを表示し、軸レンジの min にデータ値が一致する状態で window を grab、
プロット下端付近を走査して「曲線色の最下ピクセル行がフレーム下端より内側」を確認する。
headless では ViewBox 幾何で証明済み（test_boundary_data_lifts_off_frame_*）。
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPointF

pytestmark = pytest.mark.realgui


def test_fu12_boundary_data_visible_on_real_display(realgui_view) -> None:
    # realgui_view: conftest が実ディスプレイに mount 済みの GraphPanelView と VM を返す
    # fixture（既存 realgui テストと同じ）。単一フルハイト軸・auto-fit 済みとする。
    view, vm = realgui_view
    assert vm.axes[0].y_range is not None
    y_lo, y_hi = vm.axes[0].y_range
    vm.set_axis_range(0, y_lo, y_hi)  # min==データ値（境界条件を確定）
    view.refresh()

    R = view._view_boxes[0].sceneBoundingRect()
    vb = view._view_boxes[0]
    # 期待される浮き（scene px）: フレーム下端 - データ y_lo のスクリーン位置。
    frame_bot_scene = R.y() + R.height()
    data_bot_scene = vb.mapViewToScene(QPointF(0.0, y_lo)).y()
    lift_px = frame_bot_scene - data_bot_scene
    assert lift_px >= 0.5 * 0.03 * R.height(), (
        f"境界データがフレームから浮いていない（lift={lift_px:.1f}px）"
    )

    # スクショ証拠（①ゲート・視覚判定用に保存）。
    img = view.grab().toImage()
    img.save(str(_screenshot_path("fu12_boundary_data_visible.png")))
```

（`realgui_view` fixture / `_screenshot_path` が conftest に無ければ、既存 realgui テストの mount ヘルパを流用して追加する。fixture 構築は既存パターン準拠＝本 Step で確定。）

- [ ] **Step 2: realgui で実行し証拠取得**

Run: `uv run pytest tests/realgui/test_fu12_boundary_data_visible.py --realgui -q`
Expected: PASS＋`fu12_boundary_data_visible.png` に境界曲線がフレームより内側で描かれた実ディスプレイ画像。

- [ ] **Step 3: グリップ/ゾーン/軸クリック/軸D&D realgui を再監査**（視覚スパインが m 移動＝掴み点が live geometry から再計算されるため）:

Run: `uv run pytest tests/realgui/test_move_then_resize.py tests/realgui/test_click_activate_axis.py tests/realgui/ -k "grip or zone or axis or resize or move" --realgui -q`
Expected: 全 PASS。スパイン strip 期待値をアサートしている箇所が FAIL したらインセット式へ更新（掴み点ドラッグは小刻みステップ・memory [[gui_realgui_grip_drag_small_steps]]／掴み点が可視矩形外にならないよう auto-fit レンジ内 target・memory [[gui_realgui_offscreen_target_opens_os_system_menu]]）。ハングした場合は grabMouse/ゾーン誤侵入を疑い widget 空間で座標再計算（memory [[gui_realgui_zone_widgetspace_and_offscreen_clamp]]）。

- [ ] **Step 4: 変更した realgui テストをコミット**

```bash
git add tests/realgui/
git commit -m "test(realgui): FU-12 境界データ可視の実機証拠＋スパイン m インセットでグリップ/ゾーン掴み点を再監査"
```

---

## Self-Review

**1. Spec coverage:**
- Approach C（y_range 正直・描画層インセット）→ Task 1（数式）＋Task 2（配線）✓
- 乗算インセット `height*(1-2m)` → Task 1 Step3＋`test_effective_region_multiplicative_survives_min_height` ✓
- 単一ソース（値=`AXIS_INSET_MARGIN`・式=`effective_region`）→ Task 2 Step3 ✓
- 2サイト適用・5+サイト非インセット → Global Constraints＋Task 2（負契約は既存コード不変で担保）✓
- Y のみ・`_padded_range`/RN-05/`reset_x` 不変 → 触れていない ✓
- アライメント guard 厳格化（abs 0.03→0.005）→ Task 2 Step1(a) ✓
- 既存 geometry 契約テストの意図的更新＋grep → Task 2 Step5/6 ✓
- クリップ（余白帯を空）→ Task 3 ✓
- FU-12 受け入れ（ViewBox mapView→scene・auto+manual）→ Task 2 Step1(b) ✓
- realgui honest 証拠＋掴み点再監査 → Task 4 ✓
- 残存 follow-up（細軸 sub-pixel の pixel floor）→ 本プラン非対象（spec 残存節・下記メモ）✓

**2. Placeholder scan:** realgui fixture（`realgui_view`/`_screenshot_path`）は「既存 conftest ヘルパを流用・無ければ既存パターンで追加」と実体を指定済み（Task 4 は既存 realgui スケルトンの再利用が前提）。他にプレースホルダなし。

**3. Type consistency:** `effective_region(margin) -> (float, float)` を Task 1 で定義、Task 2 が `eff_top, eff_height = axis_vm.effective_region(AXIS_INSET_MARGIN)` で消費。`calculate_virtual_range(margin=0.0)` のキーワードを render loop が `AXIS_INSET_MARGIN` 位置引数で渡す（整合）。`AXIS_INSET_MARGIN: float` を Task 2 で定義、テストが import。

**4. 完了後メモ更新（プラン外・merge 後にユーザー確認）**: memory [[gui_region_overlay_viewbox_fixed_axis_spine_height]]（スパイン高さ = `height_ratio*R.height` → `effective_region().height*R.height`）／CLAUDE.md Phase 表の FU-12 反映／catalog の FU-12 ✅化＋細軸 pixel floor を follow-up 登録。
