# Y軸リージョン高さ保持（移動・並べ替え）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 軸の移動（列またぎ）と同列内の並べ替えで、ユーザー調整済みの高さを等分リセットせず保持する（超過時のみ合計で割って収める）。

**Architecture:** 根本修正。`GraphPanelVM.move_axis_to_column` を等分レイアウト（`_relayout_columns`）から、新しい高さ保持レイアウト（`_layout_column_preserving`）へ切り替える。移動先列のみ再計算し、移動元列は touch しない（抜けた帯が空白として残る＝削除と同じ仕組み）。フラグ追加ではなく経路ごとに必要なレイアウトを明示的に呼ぶ。

**Tech Stack:** Python 3.12/3.13, PySide6（View 層のみ・本変更では不変）, pytest, uv, ruff, mypy。`GraphPanelVM` は純Python ViewModel。

**設計の一次情報源:** [docs/superpowers/specs/2026-06-28-y-axis-move-height-preserve-design.md](../specs/2026-06-28-y-axis-move-height-preserve-design.md)

## Global Constraints

- **MVVM 純度**: `src/valisync/gui/viewmodels/graph_panel_vm.py` と `y_axis_vm.py` は PySide6/Qt/pyqtgraph を import しない（純Python）。
- **統一原理**: 「収まれば高さ保持／除去された帯は空白／超過時のみ列を合計で割って 1.0 に収める」。閾値による挙動の急変を作らない。
- **スコープ外（変更禁止）**: `create_new_axis` / `set_column_count` の等分挙動、`remove_signal` / `prune_missing_signals` の絶対保持＋空白、最後の信号削除時の全高プレースホルダ collapse。
- **品質ゲート（コミット前に全通過）**: `uv run pytest` 全 green、`uv run ruff check`、`uv run ruff format --check`、`uv run mypy src/`。
- **GUI テストレイヤー**: VM 純ロジックのため Layer A 必須（CI）。Layer C（`--realgui`）はローカル・Windows・実表示でのみ実行（CI 非対象）。docs/gui-testing-layers.md 準拠。
- **commit 規約**: コミットメッセージ末尾にリポジトリ規約の `Co-Authored-By:` / `Claude-Session:` トレーラを付ける。
- **事前準備**: worktree では最初に一度 `uv sync --extra dev` を実行（しないと `uv run pytest` が親の旧コードにフォールバックする）。

---

## Pre-flight（最初に一度だけ）

- [ ] **依存を同期**

Run: `uv sync --extra dev`
Expected: 依存解決が完了し `.venv` が用意される。

- [ ] **ベースライン確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -q`
Expected: 既存テストが全 PASS（変更前の緑を確認）。

---

## File Structure

| ファイル | 役割 | 本計画での変更 |
|---|---|---|
| `src/valisync/gui/viewmodels/graph_panel_vm.py` | グラフパネル ViewModel（軸レイアウトを保持） | `_layout_column_preserving` を追加（Task 1）、`move_axis_to_column` を高さ保持へ再構成（Task 2） |
| `tests/gui/test_graph_panel_multi_axis.py` | Layer A: VM 純ロジックテスト | ヘルパ単体テスト追加（Task 1）、移動の保持テスト追加＋既存1件を更新（Task 2） |
| `tests/realgui/test_multi_column_axis.py` | Layer C: 実OSドラッグ | 高さ保持アサート追加（Task 3） |
| `docs/multi-axis-empty-region-followup.md` / `CLAUDE.md` | 追跡ドキュメント | 移動・並べ替えの高さ保持を反映（Task 3） |

---

### Task 1: 高さ保持の列レイアウトヘルパ `_layout_column_preserving`

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`_relayout_columns` の直後、現在の 271 行付近に追加）
- Test: `tests/gui/test_graph_panel_multi_axis.py`

**Interfaces:**
- Consumes: `YAxisVM`（`top_ratio: float`, `height_ratio: float` を持つ）。
- Produces: `GraphPanelVM._layout_column_preserving(self, axes_in_order: list[YAxisVM]) -> None` — 渡された軸群を**縦順そのままに**上から積み、各 `height_ratio` を保持（合計>1.0 のときだけ `1.0/合計` で一律縮小）し `top_ratio` を再計算する。Task 2 の `move_axis_to_column` が使用。

- [ ] **Step 1: Write the failing tests**

`tests/gui/test_graph_panel_multi_axis.py` の末尾に追記：

```python
# ─── Task: _layout_column_preserving (height-preserving column layout) ────────


def test_layout_column_preserving_keeps_heights_when_fits() -> None:
    """合計 <= 1.0 なら縮小せず、各 height を保持し top を上から積む。余りは下部空白。"""
    from valisync.core.session import Session
    from valisync.gui.viewmodels.y_axis_vm import YAxisVM

    vm = GraphPanelVM(Session())
    a = YAxisVM(height_ratio=0.5)
    b = YAxisVM(height_ratio=0.3)
    vm._layout_column_preserving([a, b])

    assert a.top_ratio == pytest.approx(0.0)
    assert a.height_ratio == pytest.approx(0.5)
    assert b.top_ratio == pytest.approx(0.5)
    assert b.height_ratio == pytest.approx(0.3)  # 縮小なし（合計 0.8）
    assert a.height_ratio + b.height_ratio == pytest.approx(0.8)  # 余り 0.2 は空白


def test_layout_column_preserving_divides_when_overflow() -> None:
    """合計 > 1.0 なら 1.0/合計 で一律縮小（相対比維持）、top を積み直す。"""
    from valisync.core.session import Session
    from valisync.gui.viewmodels.y_axis_vm import YAxisVM

    vm = GraphPanelVM(Session())
    a = YAxisVM(height_ratio=0.6)
    x = YAxisVM(height_ratio=0.5)
    b = YAxisVM(height_ratio=0.4)
    vm._layout_column_preserving([a, x, b])  # 合計 1.5 → ÷1.5

    assert a.height_ratio == pytest.approx(0.4)
    assert x.height_ratio == pytest.approx(1.0 / 3.0)
    assert b.height_ratio == pytest.approx(0.4 / 1.5)  # ≈ 0.2667
    assert a.top_ratio == pytest.approx(0.0)
    assert x.top_ratio == pytest.approx(0.4)
    assert b.top_ratio == pytest.approx(0.4 + 1.0 / 3.0)
    assert sum(ax.height_ratio for ax in (a, x, b)) == pytest.approx(1.0)
    # 既存 a:b の相対比 6:4 が維持される
    assert a.height_ratio / b.height_ratio == pytest.approx(0.6 / 0.4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest "tests/gui/test_graph_panel_multi_axis.py::test_layout_column_preserving_keeps_heights_when_fits" "tests/gui/test_graph_panel_multi_axis.py::test_layout_column_preserving_divides_when_overflow" -v`
Expected: FAIL — `AttributeError: 'GraphPanelVM' object has no attribute '_layout_column_preserving'`。

- [ ] **Step 3: Implement the helper**

`src/valisync/gui/viewmodels/graph_panel_vm.py` の `_relayout_columns` メソッド（`def remove_signal` の直前、271 行付近）の**直後**に追加：

```python
    def _layout_column_preserving(self, axes_in_order: list[YAxisVM]) -> None:
        """Lay out one column's axes top-to-bottom, preserving their heights.

        Stacks ``axes_in_order`` from the top using each axis's current
        ``height_ratio``.  Only when the heights sum to more than 1.0 (an axis
        was added to an already-full column) are they scaled down uniformly to
        fit — relative proportions are kept.  When they sum to less than 1.0 the
        remainder stays a blank band at the bottom.  Used by
        :meth:`move_axis_to_column`; the add / column-count paths use
        :meth:`_relayout_columns` (equal split).
        """
        total = sum(a.height_ratio for a in axes_in_order)
        if total > 1.0 + 1e-9:
            scale = 1.0 / total
            for axis in axes_in_order:
                axis.height_ratio *= scale
        cursor = 0.0
        for axis in axes_in_order:
            axis.top_ratio = cursor
            cursor += axis.height_ratio
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest "tests/gui/test_graph_panel_multi_axis.py::test_layout_column_preserving_keeps_heights_when_fits" "tests/gui/test_graph_panel_multi_axis.py::test_layout_column_preserving_divides_when_overflow" -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: Gates + commit**

Run: `uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: いずれもエラーなし。

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_multi_axis.py
git commit -m "feat(gui): add _layout_column_preserving (height-preserving column layout)"
```

---

### Task 2: `move_axis_to_column` を高さ保持へ再構成

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py:193-226`（`move_axis_to_column` の本体を置換）
- Test: `tests/gui/test_graph_panel_multi_axis.py`（移動テスト追加＋既存 `test_move_axis_to_column_revacates_source` を更新）

**Interfaces:**
- Consumes: `GraphPanelVM._layout_column_preserving`（Task 1）。
- Produces: 改修後の `move_axis_to_column(self, axis_index: int, column: int, position: int | None = None) -> None` — 等分（`_relayout_columns`）を呼ばず、移動先列のみ `_layout_column_preserving` で高さ保持配置。移動元列は touch しない（空白が残る）。シグネチャは不変。

- [ ] **Step 1: Write the failing tests（新規3件）**

`tests/gui/test_graph_panel_multi_axis.py` の末尾に追記：

```python
# ─── Task: move_axis_to_column height preservation ───────────────────────────


def test_reorder_within_column_keeps_heights() -> None:
    """同列内の並べ替えは高さを保持し縦順だけ変える（0.6/0.4 を維持・等分にしない）。"""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")
    vm.create_new_axis("sig::b")  # 2 axes, inner column, equal-split 0.5/0.5
    inner = vm.column_count - 1
    # ユーザーが divider で 0.6/0.4 に調整した状態を再現
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.6
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.6, 0.4
    a, b = vm.axes[0], vm.axes[1]

    vm.move_axis_to_column(1, inner, position=0)  # b を最上段へ並べ替え

    col = _col(vm, inner)  # top -> bottom
    assert col[0] is b and col[1] is a  # 縦順が入れ替わった
    assert b.top_ratio == pytest.approx(0.0)
    assert b.height_ratio == pytest.approx(0.4)  # 高さ保持（0.5 にしない）
    assert a.top_ratio == pytest.approx(0.4)
    assert a.height_ratio == pytest.approx(0.6)  # 高さ保持


def test_cross_column_move_fits_keeps_heights() -> None:
    """移動先に余裕（合計 <= 1.0）→ 割らない。移動軸は元の高さ、移動元は空白。"""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")  # axis 0
    vm.create_new_axis("sig::b")  # axis 1
    vm.create_new_axis("sig::c")  # axis 2  (3 axes inner)
    # 配置: col0 に R(0.4)。col1 に P(0.5, top0) と X(0.3, top0.5)。
    vm.axes[0].column, vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0, 0.0, 0.4
    vm.axes[1].column, vm.axes[1].top_ratio, vm.axes[1].height_ratio = 1, 0.0, 0.5
    vm.axes[2].column, vm.axes[2].top_ratio, vm.axes[2].height_ratio = 1, 0.5, 0.3
    r, p, x = vm.axes[0], vm.axes[1], vm.axes[2]

    vm.move_axis_to_column(2, 0, position=None)  # X を col0 の最下段へ

    # 移動先 col0: R(0.4) + X(0.3) = 0.7 ≤ 1.0 → 割らない・余り 0.3 は空白
    assert x.column == 0
    assert r.top_ratio == pytest.approx(0.0)
    assert r.height_ratio == pytest.approx(0.4)  # 既存は高さ保持
    assert x.top_ratio == pytest.approx(0.4)
    assert x.height_ratio == pytest.approx(0.3)  # 移動軸は元の高さ
    assert sum(a.height_ratio for a in _col(vm, 0)) == pytest.approx(0.7)  # 空白あり
    # 移動元 col1: P は touch されず、抜けた帯（0.5-0.8）は空白
    assert p.column == 1
    assert p.top_ratio == pytest.approx(0.0)
    assert p.height_ratio == pytest.approx(0.5)


def test_cross_column_move_overflow_divides_by_sum() -> None:
    """移動先が満杯へ移動（合計 > 1.0）→ その列を合計で割って 1.0（相対比維持）。"""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")  # axis 0
    vm.create_new_axis("sig::b")  # axis 1
    vm.create_new_axis("sig::c")  # axis 2
    # 配置: col0 に A(0.6, top0) と B(0.4, top0.6) で満杯。col1 に X(0.5) と Y(0.5)。
    vm.axes[0].column, vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0, 0.0, 0.6
    vm.axes[1].column, vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0, 0.6, 0.4
    vm.axes[2].column, vm.axes[2].top_ratio, vm.axes[2].height_ratio = 1, 0.0, 0.5
    a_ax, b_ax, x = vm.axes[0], vm.axes[1], vm.axes[2]
    # col1 にもう1軸 Y を用意（移動元に空白が残ることを確認するため）
    vm.create_new_axis("sig::a")  # axis 3 を col1 に作って整える
    y = vm.axes[3]
    y.column, y.top_ratio, y.height_ratio = 1, 0.5, 0.5
    x.top_ratio, x.height_ratio = 0.0, 0.5  # create_new_axis の等分を上書きし直す

    vm.move_axis_to_column(2, 0, position=0)  # X を col0 の最上段へ

    # 移動先 col0: X(0.5)+A(0.6)+B(0.4)=1.5 → ÷1.5
    assert x.column == 0
    assert x.height_ratio == pytest.approx(1.0 / 3.0)
    assert a_ax.height_ratio == pytest.approx(0.4)
    assert b_ax.height_ratio == pytest.approx(0.4 / 1.5)
    assert x.top_ratio == pytest.approx(0.0)
    assert a_ax.top_ratio == pytest.approx(1.0 / 3.0)
    assert sum(a.height_ratio for a in _col(vm, 0)) == pytest.approx(1.0)
    # 既存 A:B の 6:4 比は維持
    assert a_ax.height_ratio / b_ax.height_ratio == pytest.approx(0.6 / 0.4)
    # 移動元 col1: Y は touch されず、抜けた帯（0.0-0.5）は空白
    assert y.column == 1
    assert y.top_ratio == pytest.approx(0.5)
    assert y.height_ratio == pytest.approx(0.5)
```

- [ ] **Step 2: Update the one regression test that assumed equal-split**

`tests/gui/test_graph_panel_multi_axis.py` の既存 `test_move_axis_to_column_revacates_source`（801 行付近）を、新しい「空の列へ移動＝高さ保持＋移動元は空白」挙動へ置換：

```python
def test_move_axis_to_column_revacates_source() -> None:
    """空の列へ移動した軸は元の高さを保つ（全高化しない）。移動元の帯は空白。"""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")
    vm.create_new_axis("sig::b")  # 2 axes inner, equal-split 0.5/0.5
    a, b = vm.axes[0], vm.axes[1]
    vm.move_axis_to_column(0, 0)  # a を空の outer col 0 へ

    # 移動軸は元の高さ 0.5 を保持（1.0 に拡張しない）
    assert a.column == 0
    assert a.top_ratio == pytest.approx(0.0)
    assert a.height_ratio == pytest.approx(0.5)
    # 移動元 inner: b は touch されず、抜けた上半分（0.0-0.5）は空白のまま
    inner_axis = _col(vm, vm.column_count - 1)[0]
    assert inner_axis is b
    assert inner_axis.top_ratio == pytest.approx(0.5)
    assert inner_axis.height_ratio == pytest.approx(0.5)
```

- [ ] **Step 3: Run the new + updated tests to verify they fail**

Run: `uv run pytest "tests/gui/test_graph_panel_multi_axis.py::test_reorder_within_column_keeps_heights" "tests/gui/test_graph_panel_multi_axis.py::test_cross_column_move_fits_keeps_heights" "tests/gui/test_graph_panel_multi_axis.py::test_cross_column_move_overflow_divides_by_sum" "tests/gui/test_graph_panel_multi_axis.py::test_move_axis_to_column_revacates_source" -v`
Expected: FAIL（現行の `move_axis_to_column` は `_relayout_columns` で等分するため、高さが 0.5 等にリセットされ assert に失敗）。

- [ ] **Step 4: Rewrite `move_axis_to_column`**

`src/valisync/gui/viewmodels/graph_panel_vm.py:193-226` の `move_axis_to_column` 本体を**丸ごと**以下へ置換：

```python
    def move_axis_to_column(
        self, axis_index: int, column: int, position: int | None = None
    ) -> None:
        """Move an axis to *column*, inserting at vertical *position* (0=top, None=bottom).

        Heights are **preserved, not equal-split**.  The destination column is
        re-stacked keeping each axis's height (scaled down only if the column
        would overflow — see :meth:`_layout_column_preserving`); the source
        column is left untouched, so the vacated band stays blank (mirroring
        removal).  A same-column move is therefore a pure reorder.  A stale drag
        index (e.g. axes changed mid-drag) is a no-op, not an ``IndexError``.
        """
        if not (0 <= axis_index < len(self._axes)):
            return
        column = max(0, min(column, self._column_count - 1))
        moved = self._axes[axis_index]
        moved.column = column
        others = sorted(
            [a for a in self._axes if a.column == column and a is not moved],
            key=lambda a: a.top_ratio,
        )
        if position is None or position >= len(others):
            insert_at = len(others)
        else:
            insert_at = max(0, position)
        ordered = others[:insert_at] + [moved] + others[insert_at:]
        self._layout_column_preserving(ordered)
        self._notify("axes")
```

注: 旧実装が呼んでいた `_compact_axes()` / `_relayout_columns()` は移動からは呼ばない（移動は軸を空にしないため `_compact_axes` は不要、`_relayout_columns` の等分が高さ保持を壊すため除去）。`_axes` のリスト順も plotted の `axis_index` も変えないので再マップ不要。

- [ ] **Step 5: Run the targeted tests to verify they pass**

Run: `uv run pytest "tests/gui/test_graph_panel_multi_axis.py::test_reorder_within_column_keeps_heights" "tests/gui/test_graph_panel_multi_axis.py::test_cross_column_move_fits_keeps_heights" "tests/gui/test_graph_panel_multi_axis.py::test_cross_column_move_overflow_divides_by_sum" "tests/gui/test_graph_panel_multi_axis.py::test_move_axis_to_column_revacates_source" -v`
Expected: PASS（4 passed）。

- [ ] **Step 6: Run the full GUI suite to confirm no regressions**

Run: `uv run pytest tests/gui/ -q`
Expected: 全 PASS。特に以下が緑のまま（移動リファクタが壊していないこと）:
- `test_move_axis_inserts_at_given_vertical_position`（同列並べ替え・縦順）
- `test_axis_index_at_respects_column`（lone 軸が col0 で全高 1.0 のまま）
- `test_prune_missing_signals_keeps_absolute_heights_with_blank_gap`（Remove File の空白保持）
- `test_normalize_splits_height_per_column`（`_relayout_columns` 等分＝追加/列数変更の回帰）

- [ ] **Step 7: Gates + commit**

Run: `uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: いずれもエラーなし。

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_multi_axis.py
git commit -m "feat(gui): move_axis_to_column preserves heights (reorder/cross-column, blank source)"
```

---

### Task 3: Layer C 実OSドラッグの高さ保持アサート＋追跡ドキュメント更新

**Files:**
- Modify: `tests/realgui/test_multi_column_axis.py`（既存テストにアサート追加）
- Modify: `docs/multi-axis-empty-region-followup.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: Task 2 後の `move_axis_to_column` 挙動（空の列へ移動した軸は元の高さを保持・移動元は空白）。

- [ ] **Step 1: 実OSドラッグの高さ保持アサートを追加**

`tests/realgui/test_multi_column_axis.py` の末尾アサート群（266 行 `assert len(vm.axes) == 2 ...` の直後）に追加。シナリオは「inner の上半分(0.5)の軸を空の col0 へドラッグ」で、移動軸は 0.5 を保持し、inner 残存軸は絶対位置(top0.5)を保ったまま上半分が空白になる：

```python
    # Height preservation (root fix): the moved axis keeps its height (~0.5) —
    # it must NOT be equal-split to full height — and the inner column's
    # remaining axis keeps its absolute position with a blank gap at the top.
    assert vm.axes[0].height_ratio == pytest.approx(0.5, abs=0.05), (
        "moved axis should keep its height (~0.5), not grow to full height; "
        f"got {vm.axes[0].height_ratio!r}. Screenshots saved to {tmp_path}"
    )
    inner_axes = [a for a in vm.axes if a.column == 1]
    assert len(inner_axes) == 1
    assert inner_axes[0].top_ratio == pytest.approx(0.5, abs=0.05), (
        "inner remaining axis should keep its absolute top (blank gap above); "
        f"got top_ratio={inner_axes[0].top_ratio!r}. Screenshots saved to {tmp_path}"
    )
    assert inner_axes[0].height_ratio == pytest.approx(0.5, abs=0.05)
```

また docstring 末尾の検証項目に「移動軸は高さ 0.5 を保持・移動元 inner は上半分が空白」を1行追記する（`* ViewModel reflects ``vm.axes[0].column == 0``` の次に）：

```python
      * heights are preserved: moved axis keeps ~0.5, inner remainder stays at
        top 0.5 with a blank gap above (no equal-split on move)
```

- [ ] **Step 2: （ローカル・Windows・実表示で）Layer C を実行**

Run: `uv run pytest --realgui tests/realgui/test_multi_column_axis.py -q`
Expected: PASS（実機がない CI/headless では skip される。ローカル Windows 実表示でのみ実走）。実行環境が無い場合は「未実行（要ローカル実機）」と記録して次へ。

- [ ] **Step 3: 追跡ドキュメントを更新**

`docs/multi-axis-empty-region-followup.md` の「## 対応状況」節の末尾に追記：

```markdown
- **移動・並べ替えの高さ保持（2026-06-28）**: 削除（案B）と同原理を移動へ拡張。`move_axis_to_column` を `_relayout_columns`（等分）から `_layout_column_preserving`（高さ保持・超過時のみ合計で割る）へ切替。同列並べ替え＝高さ保持、列またぎ移動元＝空白、移動先＝収まれば割らない/超過時のみ割る。設計: [docs/superpowers/specs/2026-06-28-y-axis-move-height-preserve-design.md](superpowers/specs/2026-06-28-y-axis-move-height-preserve-design.md)。
```

`CLAUDE.md` の Phase 状況表 `valisync-gui-axes` 行末（案B の記述の直後）に追記：

```markdown
。軸の移動・並べ替え時の高さ保持も同原理で対応（`_layout_column_preserving`、PR pending）— 設計 [docs/superpowers/specs/2026-06-28-y-axis-move-height-preserve-design.md](docs/superpowers/specs/2026-06-28-y-axis-move-height-preserve-design.md)
```

- [ ] **Step 4: 全ゲート + commit**

Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: pytest 全 PASS（realgui は skip）、lint/format/型すべてクリーン。

```bash
git add tests/realgui/test_multi_column_axis.py docs/multi-axis-empty-region-followup.md CLAUDE.md
git commit -m "test(realgui)+docs: assert move height-preservation; record move/reorder follow-up"
```

---

## Self-Review

**1. Spec coverage（設計の各項目 → タスク対応）:**
- 統一原理（収まれば保持/空白/超過時割る）→ Task 1（ヘルパ）＋ Task 2（move 配線）。
- 同列並べ替え＝高さ保持 → Task 2 `test_reorder_within_column_keeps_heights`。
- 列またぎ移動元＝空白 → Task 2 `test_cross_column_move_fits_keeps_heights` / `_overflow_` / `_revacates_source`（移動元 touch しない）。
- 移動先・収まる＝割らない → Task 2 `test_cross_column_move_fits_keeps_heights`。
- 移動先・超過＝合計で割る → Task 2 `test_cross_column_move_overflow_divides_by_sum`。
- 空の列へ移動＝高さ保持 → Task 2 `test_move_axis_to_column_revacates_source`。
- Remove File の空白保持を壊さない → Task 2 Step 6 回帰確認（`test_prune_missing_signals_keeps_absolute_heights_with_blank_gap`）。
- 追加/列数変更の等分維持 → Task 2 Step 6 回帰確認（`test_normalize_splits_height_per_column`）。
- Layer A 必須 / Layer C 推奨 → Task 1・2（Layer A）、Task 3（Layer C）。

**2. Placeholder scan:** TBD/TODO・曖昧指示なし。各コードステップは完全なコードを含む。

**3. Type consistency:** `_layout_column_preserving(self, axes_in_order: list[YAxisVM]) -> None` を Task 1 で定義し Task 2 で同名・同シグネチャで使用。`move_axis_to_column` のシグネチャは既存と同一（後方互換）。`YAxisVM` の `top_ratio`/`height_ratio`/`column` フィールド名は実装と一致。

---

## Execution Handoff

実装は **subagent-driven-development**（推奨）で Task 1→2→3 を順に消化する。各タスクは独立テスト可能。Task 3 の `--realgui` はローカル Windows 実表示でのみ実走（CI/headless は skip）。
