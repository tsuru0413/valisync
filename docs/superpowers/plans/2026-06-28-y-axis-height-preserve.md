# Y軸リージョン高さ保持（信号削除時）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 信号削除で軸が空になり刈り取られたとき、残った軸のユーザー調整高さ比を保持して再正規化する（等分リセットしない）。

**Architecture:** `GraphPanelVM._normalize_axes` が束ねていた「構造整合」と「レイアウト方針」を `_compact_axes()`（構造）と `_relayout_columns(preserve_heights)`（方針）に分離して `_normalize_axes` を廃止する。削除パス（`remove_signal`/`prune_missing_signals`）だけ `preserve_heights=True`（列内合計1.0へ比例正規化）を呼ぶ。

**Tech Stack:** Python 3 / PySide6 / pyqtgraph / pytest / pytest-qt。VM はピュア Python（Qt 非依存）。

## Global Constraints

- VM 層（`graph_panel_vm.py`）は PySide6/Qt/pyqtgraph を import しない（既存制約）。
- 品質ゲート（コミット前に全通過）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- ワークツリーでは作業前に `uv sync --extra dev`（しないと `uv run pytest` が親の旧コードへフォールバック）。
- GUI テストは `docs/gui-testing-layers.md` 準拠。Layer A/B は CI（`uv run pytest`）、Layer C は `--realgui`（Windows+実ディスプレイ・ローカルのみ）。
- TDD: 全レイヤー RED→GREEN。コメントは WHY を書く。
- 設計一次情報: `docs/superpowers/specs/2026-06-28-y-axis-height-preserve-design.md`。

---

## ファイル構成

| ファイル | 役割 | 変更種別 |
|---|---|---|
| `src/valisync/gui/viewmodels/graph_panel_vm.py` | `_normalize_axes` 廃止 → `_compact_axes` + `_relayout_columns` 分離、5 呼び出し元を置換 | Modify |
| `tests/gui/test_graph_panel_multi_axis.py` | 直叩きテスト更新 + Layer A 新規 + 結合 E2E（Layer A/B） | Modify |
| `tests/realgui/test_remove_file_preserves_proportions.py` | Layer C（実 divider ドラッグ + 実 Remove File） | Create |
| `docs/multi-axis-empty-region-followup.md` | 案B 解決済みへ更新 | Modify |
| `CLAUDE.md` | Phase 2 axes 行に本 follow-up 解決を反映 | Modify |

---

## 事前準備（最初に一度だけ）

- [ ] **依存を同期**

Run: `uv sync --extra dev`
Expected: 完了（worktree のローカル環境が整う）

- [ ] **ベースライン確認（既存グリーン）**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py tests/gui/test_graph_panel_view.py tests/gui/test_graph_panel_vm.py -q`
Expected: PASS（全既存テスト緑）

---

## Task 1: `_normalize_axes` を `_compact_axes` + `_relayout_columns` に分離（純リファクタ・挙動不変）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`_normalize_axes` 224-261、呼び出し元 122/188/221/266/282、docstring 175/183/196）
- Modify: `tests/gui/test_graph_panel_multi_axis.py:670-687`（`_normalize_axes()` 直叩きを置換）

**Interfaces:**
- Produces:
  - `GraphPanelVM._compact_axes(self) -> None` — 空軸刈り取り + plotted entry の `axis_index` 再マップ。信号0本なら単一フルハイト placeholder へ collapse。レイアウト（top/height）は割り当てない。
  - `GraphPanelVM._relayout_columns(self) -> None` — 列ごとに top_ratio 昇順で並べ、各列を等分（`h = 1/n`）。
- Consumes: なし（既存メソッドの内部分割）。

- [ ] **Step 1: 既存直叩きテストを新メソッド呼び出しへ更新**

`tests/gui/test_graph_panel_multi_axis.py` の `test_normalize_splits_height_per_column`（670-687）の `vm._normalize_axes()` 2 箇所を `vm._relayout_columns()` に置換する（このテストは等分レイアウトの検証であり、構造整合は不要＝軸は既に存在するため）。

```python
def test_normalize_splits_height_per_column() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_two_signals(vm)  # 2 axes, both col=0 by default

    # Move both axes to column 1 (inner column)
    vm.axes[0].column, vm.axes[1].column = 1, 1
    vm._relayout_columns()
    assert [(a.top_ratio, a.height_ratio) for a in _col(vm, 1)] == [
        (0.0, 0.5),
        (0.5, 0.5),
    ]

    # Move axis 1 to column 0 — each axis is now alone in its own column
    vm.axes[1].column = 0
    vm._relayout_columns()
    assert all(a.height_ratio == 1.0 for a in vm.axes)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py::test_normalize_splits_height_per_column -q`
Expected: FAIL（`AttributeError: 'GraphPanelVM' object has no attribute '_relayout_columns'`）

- [ ] **Step 3: `_normalize_axes` を 2 メソッドへ分割**

`graph_panel_vm.py` の `_normalize_axes`（224-261）全体を、以下の 2 メソッドへ置換する。

```python
    def _compact_axes(self) -> None:
        """Prune signal-less axes and remap plotted entries to compacted indices.

        Empty axes (the initial placeholder, or an axis whose signals were all
        moved/removed) must not occupy panel space. When no signals remain,
        collapse to a single full-height placeholder in the inner (last) column.
        Structural only — top_ratio/height_ratio layout is assigned separately by
        :meth:`_relayout_columns`.
        """
        used = sorted({e.axis_index for e in self._plotted})
        if not used:
            keep = self._axes[0] if self._axes else YAxisVM()
            keep.top_ratio, keep.height_ratio = 0.0, 1.0
            keep.column = self._column_count - 1
            self._axes = [keep]
            return
        remap = {old: new for new, old in enumerate(used)}
        self._axes = [self._axes[old] for old in used]
        for entry in self._plotted:
            entry.axis_index = remap[entry.axis_index]

    def _relayout_columns(self) -> None:
        """Assign top_ratio/height_ratio per column, splitting height equally.

        Axes are grouped by column; within each column the vertical order is
        taken from the pre-existing top_ratio, then each column's axes split the
        full column height equally.
        """
        col_groups: dict[int, list[YAxisVM]] = {}
        for axis in self._axes:
            col_groups.setdefault(axis.column, []).append(axis)
        for axes_in_col in col_groups.values():
            ordered = sorted(axes_in_col, key=lambda a: a.top_ratio)
            h = 1.0 / len(ordered)
            cursor = 0.0
            for axis in ordered:
                axis.top_ratio = cursor
                axis.height_ratio = h
                cursor += h
```

- [ ] **Step 4: 5 つの呼び出し元を `_compact_axes()` + `_relayout_columns()` に置換**

`graph_panel_vm.py` の各 `self._normalize_axes()` を以下へ置換する（行番号は現状）。

`set_column_count`（122）:
```python
        self._compact_axes()
        self._relayout_columns()
```
`create_new_axis`（188）:
```python
        self._compact_axes()
        self._relayout_columns()
```
`move_axis_to_column`（221）:
```python
        self._compact_axes()
        self._relayout_columns()
```
`remove_signal`（266）:
```python
        self._compact_axes()
        self._relayout_columns()
```
`prune_missing_signals`（282）:
```python
        self._compact_axes()
        self._relayout_columns()
```

- [ ] **Step 5: docstring の `_normalize_axes` 参照を更新**

`create_new_axis` の docstring（175 付近）:
```python
        A fresh axis is appended for the signal, then :meth:`_compact_axes`
        prunes any empty axis (e.g. the initial placeholder) so the first signal
        fills the whole panel and subsequent signals split it into equal regions.
```
`create_new_axis` のコメント（183 付近）:
```python
        # Give the new axis a transient top_ratio that sorts it after all
        # existing axes in the same column so _relayout_columns places it at the
        # bottom (rule A: new axis appends below existing ones).
```
`move_axis_to_column` の docstring（196 付近）:
```python
        The source slot is vacated and re-split by _relayout_columns (rule 1:
        equal re-split per column). `position` is the insertion index among the
        destination column's other members. Existing 2-arg callers append at the
        bottom.
```

- [ ] **Step 6: 更新テストが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py::test_normalize_splits_height_per_column -q`
Expected: PASS

- [ ] **Step 7: リファクタの安全網（全既存テスト緑）**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py tests/gui/test_graph_panel_view.py tests/gui/test_graph_panel_vm.py tests/gui/test_graph_area_vm.py -q`
Expected: PASS（挙動不変＝全緑）

- [ ] **Step 8: 品質ゲート + コミット**

Run: `uv run ruff check src/ tests/ ; uv run ruff format --check src/ tests/ ; uv run mypy src/`
Expected: いずれもエラーなし（必要なら `uv run ruff format` で整形してから再確認）

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_multi_axis.py
git commit -m "$(cat <<'EOF'
refactor(gui): _normalize_axes を _compact_axes + _relayout_columns に分離し廃止

構造整合（空軸刈り取り+再マップ）とレイアウト方針（列ごと等分）を分離。
全5呼び出し元を明示呼び出しへ置換。挙動不変（既存テスト緑）。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0141ptfNpsj6CMDA6REtu7Pi
EOF
)"
```

---

## Task 2: `_relayout_columns` に `preserve_heights` 比例維持を追加

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`_relayout_columns`）
- Modify: `tests/gui/test_graph_panel_multi_axis.py`（新規テスト 2 件をモジュール末尾の `_normalize_axes` 系テスト近辺、例: `test_normalize_splits_height_per_column` の直後に追加）

**Interfaces:**
- Produces: `GraphPanelVM._relayout_columns(self, *, preserve_heights: bool = False) -> None` — `preserve_heights=True` で各列の既存 `height_ratio` を列内合計で割って 1.0 へ正規化（相対比保持）。合計0は等分にフォールバック。`False` は等分（Task 1 と同一）。
- Consumes: Task 1 の `_relayout_columns`。

- [ ] **Step 1: 失敗するテストを書く（比例正規化 + ゼロ退避）**

`tests/gui/test_graph_panel_multi_axis.py` に追加:

```python
def test_relayout_columns_preserves_proportions() -> None:
    """preserve_heights=True renormalizes a sub-unity column to 1.0, keeping ratios."""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    vm.add_signal_to_axis("s::a", 0)
    vm.create_new_axis("s::c")  # 2 axes in inner column
    # Heights summing to 0.7 simulate the post-prune state (a 0.3 axis removed).
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.5
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.8, 0.2

    vm._relayout_columns(preserve_heights=True)

    assert vm.axes[0].height_ratio == pytest.approx(0.5 / 0.7)
    assert vm.axes[1].height_ratio == pytest.approx(0.2 / 0.7)
    assert vm.axes[0].top_ratio == pytest.approx(0.0)
    assert vm.axes[1].top_ratio == pytest.approx(0.5 / 0.7)


def test_relayout_total_zero_falls_back_to_equal() -> None:
    """A degenerate zero-sum column falls back to an equal split (no ZeroDivision)."""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    vm.add_signal_to_axis("s::a", 0)
    vm.create_new_axis("s::b")
    vm.axes[0].height_ratio = 0.0
    vm.axes[1].height_ratio = 0.0

    vm._relayout_columns(preserve_heights=True)

    assert vm.axes[0].height_ratio == pytest.approx(0.5)
    assert vm.axes[1].height_ratio == pytest.approx(0.5)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py::test_relayout_columns_preserves_proportions tests/gui/test_graph_panel_multi_axis.py::test_relayout_total_zero_falls_back_to_equal -q`
Expected: FAIL（`TypeError: _relayout_columns() got an unexpected keyword argument 'preserve_heights'`）

- [ ] **Step 3: `preserve_heights` 分岐を実装**

`graph_panel_vm.py` の `_relayout_columns` を以下へ置換する。

```python
    def _relayout_columns(self, *, preserve_heights: bool = False) -> None:
        """Assign top_ratio/height_ratio per column.

        Axes are grouped by column; within each column the vertical order is
        taken from the pre-existing top_ratio. With ``preserve_heights=False``
        each column's axes split the full column height equally. With
        ``preserve_heights=True`` the existing height_ratios are renormalized to
        sum to 1.0 per column (preserving the user's relative sizing after a
        removal); a degenerate zero-sum column falls back to an equal split.
        """
        col_groups: dict[int, list[YAxisVM]] = {}
        for axis in self._axes:
            col_groups.setdefault(axis.column, []).append(axis)
        for axes_in_col in col_groups.values():
            ordered = sorted(axes_in_col, key=lambda a: a.top_ratio)
            n = len(ordered)
            if preserve_heights:
                total = sum(a.height_ratio for a in ordered)
                heights = (
                    [a.height_ratio / total for a in ordered]
                    if total > 0
                    else [1.0 / n] * n
                )
            else:
                heights = [1.0 / n] * n
            cursor = 0.0
            for axis, h in zip(ordered, heights):
                axis.top_ratio = cursor
                axis.height_ratio = h
                cursor += h
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py::test_relayout_columns_preserves_proportions tests/gui/test_graph_panel_multi_axis.py::test_relayout_total_zero_falls_back_to_equal -q`
Expected: PASS

- [ ] **Step 5: 等分パスの回帰確認（既存テスト緑のまま）**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -q`
Expected: PASS（等分側は default False で不変）

- [ ] **Step 6: 品質ゲート + コミット**

Run: `uv run ruff check src/ tests/ ; uv run ruff format --check src/ tests/ ; uv run mypy src/`
Expected: エラーなし

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_multi_axis.py
git commit -m "$(cat <<'EOF'
feat(gui): _relayout_columns に preserve_heights 比例維持を追加

列内の既存 height_ratio を合計1.0へ正規化（相対比保持）。合計0は等分退避。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0141ptfNpsj6CMDA6REtu7Pi
EOF
)"
```

---

## Task 3: `remove_signal` を比例維持へ切替

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`remove_signal`）
- Modify: `tests/gui/test_graph_panel_multi_axis.py`（新規テスト 2 件）

**Interfaces:**
- Consumes: Task 2 の `_relayout_columns(preserve_heights=True)`。
- Produces: `remove_signal` が削除後に残存軸の高さ比を保持する。

- [ ] **Step 1: 失敗するテストを書く（比例維持 + 冪等性）**

```python
def test_remove_signal_preserves_remaining_proportions() -> None:
    """Removing the middle of 3 regions keeps survivors' relative heights."""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    vm.add_signal_to_axis("s::a", 0)
    vm.create_new_axis("s::b")
    vm.create_new_axis("s::c")
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.5
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.5, 0.3
    vm.axes[2].top_ratio, vm.axes[2].height_ratio = 0.8, 0.2

    vm.remove_signal("s::b")

    assert len(vm.axes) == 2
    assert vm.axes[0].height_ratio == pytest.approx(0.5 / 0.7)
    assert vm.axes[1].height_ratio == pytest.approx(0.2 / 0.7)
    assert vm.axes[0].top_ratio == pytest.approx(0.0)
    assert vm.axes[1].top_ratio == pytest.approx(0.5 / 0.7)


def test_remove_one_signal_from_multisignal_axis_keeps_heights() -> None:
    """Removing one of two signals on an axis leaves it (no prune); heights stay."""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    vm.add_signal_to_axis("s::a", 0)
    vm.add_signal_to_axis("s::a2", 0)  # second signal on the same axis 0
    vm.create_new_axis("s::b")
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.6
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.6, 0.4

    vm.remove_signal("s::a2")  # axis 0 still holds s::a → not pruned

    assert len(vm.axes) == 2
    assert vm.axes[0].height_ratio == pytest.approx(0.6)
    assert vm.axes[1].height_ratio == pytest.approx(0.4)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py::test_remove_signal_preserves_remaining_proportions -q`
Expected: FAIL（現状は等分のため 0.5/0.5 になり approx(0.714) と不一致）

> 注: `test_remove_one_signal_from_multisignal_axis_keeps_heights` は Task 1 時点でも通る可能性が高い（刈り取り無しで等分も0.6/0.4を保つ列なら一致）。冪等性の保証用ロックテスト。

- [ ] **Step 3: `remove_signal` を比例維持へ**

`graph_panel_vm.py` の `remove_signal` の `self._relayout_columns()` を置換:

```python
    def remove_signal(self, signal_key: str) -> None:
        """Remove *signal_key* from the plot and reconcile axes.

        Survivors keep their relative heights (preserve_heights=True): removing a
        region renormalizes the column instead of resetting it to an equal split.
        """
        self._plotted = [e for e in self._plotted if e.signal_key != signal_key]
        self._compact_axes()
        self._relayout_columns(preserve_heights=True)
        self._invalidate_cache()
        self._notify("signals")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py::test_remove_signal_preserves_remaining_proportions tests/gui/test_graph_panel_multi_axis.py::test_remove_one_signal_from_multisignal_axis_keeps_heights -q`
Expected: PASS

- [ ] **Step 5: 既存 remove 回帰確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -k "remove or prune or normalize or relayout" -q`
Expected: PASS（`test_remove_signal_prunes_now_empty_axis` の `==1.0` も比例維持で不変）

- [ ] **Step 6: 品質ゲート + コミット**

Run: `uv run ruff check src/ tests/ ; uv run ruff format --check src/ tests/ ; uv run mypy src/`
Expected: エラーなし

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_multi_axis.py
git commit -m "$(cat <<'EOF'
feat(gui): remove_signal を高さ比例維持へ（削除後に等分リセットしない）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0141ptfNpsj6CMDA6REtu7Pi
EOF
)"
```

---

## Task 4: `prune_missing_signals` を比例維持へ切替 + 列スコープ保証

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`prune_missing_signals`）
- Modify: `tests/gui/test_graph_panel_multi_axis.py`（新規テスト 2 件）

**Interfaces:**
- Consumes: Task 2 の `_relayout_columns(preserve_heights=True)`。
- Produces: `prune_missing_signals` が削除後に残存軸の高さ比を保持する。

- [ ] **Step 1: 失敗するテストを書く（prune 比例維持 + 列スコープ）**

```python
def test_prune_missing_signals_preserves_remaining_proportions(tmp_path: Path) -> None:
    """File-unload prune keeps survivors' relative heights."""
    from valisync.core.session import Session

    session, _ = _loaded_session(tmp_path, n_signals=3)
    keys = sorted(_keys(session))  # 3 namespaced signal names, deterministic order
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])
    vm.create_new_axis(keys[1])
    vm.create_new_axis(keys[2])
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.5
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.5, 0.3
    vm.axes[2].top_ratio, vm.axes[2].height_ratio = 0.8, 0.2

    remaining = [s for s in session.signals() if s.name != keys[1]]
    session.signals = lambda: remaining  # type: ignore[method-assign]
    vm.prune_missing_signals()

    assert len(vm.axes) == 2
    cols = sorted(vm.axes, key=lambda a: a.top_ratio)
    assert cols[0].height_ratio == pytest.approx(0.5 / 0.7)
    assert cols[1].height_ratio == pytest.approx(0.2 / 0.7)


def test_remove_preserves_proportions_per_column() -> None:
    """Renormalization is column-scoped: removing in one column leaves the other."""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())  # column_count == 2
    vm.add_signal_to_axis("c1::a", 0)
    vm.create_new_axis("c1::b")
    vm.create_new_axis("c1::c")
    vm.create_new_axis("c0::d")
    vm.create_new_axis("c0::e")
    # Move d, e to the outer column 0.
    vm.axes[3].column = 0
    vm.axes[4].column = 0
    # Inner column heights 0.5/0.3/0.2; outer column heights 0.5/0.5.
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.5
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.5, 0.3
    vm.axes[2].top_ratio, vm.axes[2].height_ratio = 0.8, 0.2
    vm.axes[3].top_ratio, vm.axes[3].height_ratio = 0.0, 0.5
    vm.axes[4].top_ratio, vm.axes[4].height_ratio = 0.5, 0.5

    vm.remove_signal("c1::b")

    col1 = _col(vm, 1)
    col0 = _col(vm, 0)
    assert [a.height_ratio for a in col1] == [
        pytest.approx(0.5 / 0.7),
        pytest.approx(0.2 / 0.7),
    ]
    assert [a.height_ratio for a in col0] == [pytest.approx(0.5), pytest.approx(0.5)]
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py::test_prune_missing_signals_preserves_remaining_proportions -q`
Expected: FAIL（現状 prune は等分のため 0.5/0.5）

> 注: `test_remove_preserves_proportions_per_column` は `remove_signal`（Task 3 で比例維持済み）を使うため、Task 3 完了後は既に PASS する見込み。列スコープのロックテストとして追加する（FAIL するなら relayout が列ごとに閉じていない＝要修正）。

- [ ] **Step 3: `prune_missing_signals` を比例維持へ**

`graph_panel_vm.py` の `prune_missing_signals` の `self._relayout_columns()` を置換:

```python
        self._plotted = kept
        self._compact_axes()
        self._relayout_columns(preserve_heights=True)
        self._invalidate_cache()
        self._notify("signals")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py::test_prune_missing_signals_preserves_remaining_proportions tests/gui/test_graph_panel_multi_axis.py::test_remove_preserves_proportions_per_column -q`
Expected: PASS

- [ ] **Step 5: 既存 prune 回帰確認**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py -k "prune" -q`
Expected: PASS（`test_prune_missing_signals_drops_signals_absent_from_session` 含む）

- [ ] **Step 6: 品質ゲート + コミット**

Run: `uv run ruff check src/ tests/ ; uv run ruff format --check src/ tests/ ; uv run mypy src/`
Expected: エラーなし

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_multi_axis.py
git commit -m "$(cat <<'EOF'
feat(gui): prune_missing_signals を高さ比例維持へ + 列スコープ回帰テスト

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0141ptfNpsj6CMDA6REtu7Pi
EOF
)"
```

---

## Task 5: 結合 E2E — 配線パス（unload → prune → 保持）を CI で検証（Layer A/B）

**Files:**
- Modify: `tests/gui/test_graph_panel_multi_axis.py`（import 追加 + 新規テスト 1 件）

**Interfaces:**
- Consumes: `AppViewModel().request_load(path, fmt) -> str`、`AppViewModel.unload_file(key)`、`GraphAreaVM(app).panels(0) -> list[GraphPanelVM]`、`_write_csv`/`_csv_format`/`_make_view`（`tests/gui/test_graph_panel_view.py`）。
- Produces: 本番配線（FileBrowser unload → `"unloaded"` → `GraphAreaVM._on_app_change` → `prune_missing_signals`）で高さ比が保持されることの結合保証。

- [ ] **Step 1: import を追加**

`tests/gui/test_graph_panel_multi_axis.py:19` の import を拡張:

```python
from tests.gui.test_graph_panel_view import (
    _csv_format,
    _keys,
    _loaded_session,
    _make_view,
    _write_csv,
)
```

- [ ] **Step 2: 失敗しうる結合テストを書く**

```python
def test_unload_preserves_panel_proportions(qtbot: QtBot, tmp_path: Path) -> None:
    """Wired path: app file-unload → '"unloaded"' → panel prune keeps proportions."""
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM

    app = AppViewModel()
    seen: set[str] = set()

    def _load_one(name: str) -> tuple[str, str]:
        path = _write_csv(tmp_path / name, 50, 1)
        file_key = app.request_load(path, _csv_format(1))
        sig_key = (set(s.name for s in app.signals()) - seen).pop()
        seen.add(sig_key)
        return file_key, sig_key

    _, sig_a = _load_one("a.csv")
    file_b, sig_b = _load_one("b.csv")
    _, sig_c = _load_one("c.csv")

    area = GraphAreaVM(app)
    panel = area.panels(0)[0]
    panel.create_new_axis(sig_a)  # axis 0
    panel.create_new_axis(sig_b)  # axis 1 (middle)
    panel.create_new_axis(sig_c)  # axis 2
    panel.axes[0].top_ratio, panel.axes[0].height_ratio = 0.0, 0.5
    panel.axes[1].top_ratio, panel.axes[1].height_ratio = 0.5, 0.3
    panel.axes[2].top_ratio, panel.axes[2].height_ratio = 0.8, 0.2

    view = _make_view(qtbot, panel)  # confirm the view follows the prune

    app.unload_file(file_b)  # real wired removal → "unloaded" → prune

    assert len(panel.axes) == 2
    cols = sorted(panel.axes, key=lambda a: a.top_ratio)
    assert cols[0].height_ratio == pytest.approx(0.5 / 0.7)
    assert cols[1].height_ratio == pytest.approx(0.2 / 0.7)
    assert len(view._view_boxes) == 2  # type: ignore[attr-defined]
```

- [ ] **Step 3: テストを実行**

Run: `uv run pytest tests/gui/test_graph_panel_multi_axis.py::test_unload_preserves_panel_proportions -q`
Expected: PASS（Task 4 で prune が比例維持済みのため。Task 4 以前なら 0.5/0.5 で FAIL する関係＝配線の結合保証）

- [ ] **Step 4: 品質ゲート + コミット**

Run: `uv run ruff check src/ tests/ ; uv run ruff format --check src/ tests/ ; uv run mypy src/`
Expected: エラーなし

```bash
git add tests/gui/test_graph_panel_multi_axis.py
git commit -m "$(cat <<'EOF'
test(gui): 結合E2E — file-unload→prune の配線で高さ比保持を検証(Layer A/B)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0141ptfNpsj6CMDA6REtu7Pi
EOF
)"
```

---

## Task 6: Layer C — 実OS入力 E2E（実 divider ドラッグ + 実 Remove File）

> Layer C は **環境依存**（座標・タイミング・DPI・最前面化）。CI では `--realgui` 未指定/非 Windows により自動スキップされる。**実 Windows + 実ディスプレイ**で `uv run pytest --realgui tests/realgui/test_remove_file_preserves_proportions.py -q` を実行して確認する。座標がズレてジェスチャが外れる場合は保存スクショ（`tmp_path`）を見てタイミング/座標を微調整する（Layer C の性質）。divider はプレーン pyqtgraph ドラッグ（QDrag/OLE 非経由）のため thread/watchdog 不要、`processEvents` で駆動する。

**Files:**
- Create: `tests/realgui/test_remove_file_preserves_proportions.py`

**Interfaces:**
- Consumes: `GraphPanelView(panel)._dividers: list[RegionDividerItem]`、`GraphPanelView._view_boxes`、`FileBrowserView(FileBrowserVM(app))`、`AppViewModel`、`GraphAreaVM`、`_Y_AXIS_FIXED_WIDTH`。

- [ ] **Step 1: realgui テストを作成**

```python
"""Layer C: real-OS-input E2E for Y-axis height preservation on file unload.

Opt-in — run with ``--realgui`` on Windows + a real display::

    uv run pytest --realgui tests/realgui/test_remove_file_preserves_proportions.py -q

It (1) real-drags a region divider on a GraphPanelView to make the regions
non-equal, then (2) issues a genuine right-click on a FileBrowserView row and
triggers "Remove File", and asserts the surviving graph regions keep their
relative heights. The divider drag is a plain pyqtgraph mouse drag (no QDrag/OLE
modal loop), so it is driven inline with processEvents — no background thread is
needed. Excluded from CI — see docs/gui-testing-layers.md (Layer C).

Note: hijacks the mouse cursor for ~2 s. Coordinates/timing are environment
sensitive; on a miss inspect the screenshots saved under tmp_path.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.realgui

_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010


def test_remove_file_preserves_graph_panel_proportions(
    qtbot: QtBot, tmp_path: Path
) -> None:
    if sys.platform != "win32":
        pytest.skip("real OS input uses Win32 mouse_event (Windows-only)")

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMenu

    if QGuiApplication.platformName() == "offscreen":
        pytest.skip(
            "requires a real display — run: uv run pytest --realgui tests/realgui/"
        )

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.file_browser_view import FileBrowserView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    user32 = ctypes.windll.user32

    def _fmt() -> FormatDefinition:
        return FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        )

    def _write_csv(path: Path) -> Path:
        lines = ["t,s1"]
        for i in range(50):
            lines.append(f"{i * 0.01:.3f},{float(i % 50):.1f}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    # ─── App + 3 single-signal files (3 regions; middle file gets removed) ─────
    app = AppViewModel()
    seen: set[str] = set()

    def _load(name: str) -> tuple[str, str]:
        key = app.request_load(_write_csv(tmp_path / name), _fmt())
        sig = (set(s.name for s in app.signals()) - seen).pop()
        seen.add(sig)
        return key, sig

    _, sig_a = _load("a.csv")
    file_b, sig_b = _load("b.csv")
    _, sig_c = _load("c.csv")

    area = GraphAreaVM(app)
    panel = area.panels(0)[0]
    panel.create_new_axis(sig_a)  # axis 0 (top)
    panel.create_new_axis(sig_b)  # axis 1 (middle, file_b)
    panel.create_new_axis(sig_c)  # axis 2 (bottom)

    # ─── GraphPanelView (for the real divider drag) ───────────────────────────
    gpv = GraphPanelView(panel)
    qtbot.addWidget(gpv)
    gpv.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    gpv.setGeometry(120, 120, 700, 600)
    gpv.show()
    qtbot.waitExposed(gpv)
    QApplication.processEvents()
    QApplication.processEvents()
    qtbot.waitUntil(
        lambda: bool(gpv._dividers)  # type: ignore[attr-defined]
        and gpv._dividers[0].sceneBoundingRect().width() > 0,  # type: ignore[attr-defined]
        timeout=3000,
    )

    dpr = gpv.devicePixelRatioF()

    def _phys(global_pt: object) -> tuple[int, int]:
        return round(global_pt.x() * dpr), round(global_pt.y() * dpr)  # type: ignore[attr-defined]

    # Divider 0 sits between region 0 and region 1. Drag it UP to shrink region 0,
    # producing non-equal heights we can later check survive the file removal.
    div = gpv._dividers[0]  # type: ignore[attr-defined]
    scene_c = div.sceneBoundingRect().center()
    vp = gpv.plot_widget.mapFromScene(scene_c)  # type: ignore[attr-defined]
    start_global = gpv.plot_widget.viewport().mapToGlobal(vp)  # type: ignore[attr-defined]
    sx, sy = _phys(start_global)
    drag_px = round(gpv.height() * 0.18 * dpr)  # move up ~18% of the panel height

    def _at(x: int, y: int, flag: int) -> None:
        user32.SetCursorPos(int(x), int(y))
        user32.mouse_event(flag, 0, 0, 0, 0)

    _at(sx, sy, _MOUSEEVENTF_LEFTDOWN)
    QApplication.processEvents()
    for step in range(1, 6):  # incremental moves so pyqtgraph emits drag deltas
        _at(sx, sy - round(drag_px * step / 5), _MOUSEEVENTF_MOVE)
        QApplication.processEvents()
        time.sleep(0.03)
    _at(sx, sy - drag_px, _MOUSEEVENTF_LEFTUP)
    for _ in range(3):
        QApplication.processEvents()

    # Region 0 must now differ from region 1 (the drag actually moved heights).
    heights_before = [a.height_ratio for a in sorted(panel.axes, key=lambda a: a.top_ratio)]
    assert abs(heights_before[0] - heights_before[1]) > 0.02, (
        "real divider drag did not change region heights; "
        f"got {heights_before}. Tune coords/timing — see tmp_path screenshots."
    )

    # ─── FileBrowserView (for the real Remove File right-click) ───────────────
    fbv = FileBrowserView(FileBrowserVM(app))
    qtbot.addWidget(fbv)
    fbv.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    fbv.setGeometry(840, 120, 360, 240)
    fbv.show()
    qtbot.waitExposed(fbv)
    # file_b is the 2nd loaded → row index 1 in loaded_file_keys order.
    row = app.loaded_file_keys.index(file_b)
    qtbot.waitUntil(
        lambda: fbv.list_view.visualRect(fbv.model.index(row, 0)).height() > 0,
        timeout=3000,
    )

    lv = fbv.list_view
    center = lv.visualRect(fbv.model.index(row, 0)).center()
    rx, ry = _phys(lv.viewport().mapToGlobal(center))

    # Real right-click opens the context menu; then trigger "Remove File".
    _at(rx, ry, _MOUSEEVENTF_RIGHTDOWN)
    user32.mouse_event(_MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    qtbot.waitUntil(
        lambda: isinstance(QApplication.activePopupWidget(), QMenu), timeout=3000
    )
    menu = QApplication.activePopupWidget()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "menu.png"))
    remove_action = next(a for a in menu.actions() if a.text() == "Remove File")
    remove_action.trigger()
    menu.close()
    for _ in range(3):
        QApplication.processEvents()

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "after.png"))

    # ─── Assert: middle region pruned, survivors keep their relative heights ──
    assert len(panel.axes) == 2, (
        f"expected 2 regions after Remove File, got {len(panel.axes)}. "
        f"Screenshots: {tmp_path}"
    )
    cols = sorted(panel.axes, key=lambda a: a.top_ratio)
    ratio_before = heights_before[0] / heights_before[2]
    ratio_after = cols[0].height_ratio / cols[1].height_ratio
    assert ratio_after == pytest.approx(ratio_before, rel=0.05), (
        "surviving regions did not keep their relative heights after removal; "
        f"before={heights_before}, after={[c.height_ratio for c in cols]}. "
        f"Screenshots: {tmp_path}"
    )
    assert len(gpv._view_boxes) == 2  # type: ignore[attr-defined]
```

- [ ] **Step 2: ローカル実機で実行（CI 不可）**

Run（Windows + 実ディスプレイ）: `uv run pytest --realgui tests/realgui/test_remove_file_preserves_proportions.py -q`
Expected: PASS（マウスを ~2 秒占有）。外れる場合は `tmp_path` のスクショ（`menu.png`/`after.png`）で座標・タイミングを調整。

- [ ] **Step 3: CI 既定では自動スキップされることを確認**

Run: `uv run pytest tests/realgui/test_remove_file_preserves_proportions.py -q`
Expected: skipped（`--realgui` 未指定）

- [ ] **Step 4: 品質ゲート + コミット**

Run: `uv run ruff check tests/ ; uv run ruff format --check tests/`
Expected: エラーなし

```bash
git add tests/realgui/test_remove_file_preserves_proportions.py
git commit -m "$(cat <<'EOF'
test(gui): Layer C — 実divider ドラッグ+実Remove File で高さ保持を検証

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0141ptfNpsj6CMDA6REtu7Pi
EOF
)"
```

---

## Task 7: ドキュメント更新（案B 解決の反映）

**Files:**
- Modify: `docs/multi-axis-empty-region-followup.md`
- Modify: `CLAUDE.md`（Phase 状況テーブルの axes 行）

**Interfaces:** なし（ドキュメントのみ）。

- [ ] **Step 1: follow-up doc に解決を追記**

`docs/multi-axis-empty-region-followup.md` の「採用方針 (推奨)」節の末尾に、以下を追記する。

```markdown
## 対応状況（2026-06-28 更新）

- **案A（空軸刈り取り）**: PR #10（`49086f2`）で `remove_signal` に `_normalize_axes` 適用済み。回帰テスト `test_remove_signal_prunes_now_empty_axis`。
- **案B（高さ保持）**: `feature/valisync-gui-axes-height-preserve` で実装。`_normalize_axes` を `_compact_axes` + `_relayout_columns(preserve_heights)` に分離（`_normalize_axes` は廃止）、`remove_signal`/`prune_missing_signals` を比例維持化。設計: [docs/superpowers/specs/2026-06-28-y-axis-height-preserve-design.md](superpowers/specs/2026-06-28-y-axis-height-preserve-design.md) / 計画: [docs/superpowers/plans/2026-06-28-y-axis-height-preserve.md](superpowers/plans/2026-06-28-y-axis-height-preserve.md)。
```

- [ ] **Step 2: CLAUDE.md の axes 行を更新**

`CLAUDE.md` の Phase 状況テーブルの `Phase 2 / valisync-gui-axes` 行末尾（「信号削除時の空リージョン残存は別 follow-up — 詳細は …」の文）を以下へ置換する。

```markdown
信号削除時の空リージョン残存は案A（PR #10）+ 案B（高さ保持, `feature/valisync-gui-axes-height-preserve`）で解決済み — 詳細は [docs/multi-axis-empty-region-followup.md](docs/multi-axis-empty-region-followup.md)
```

- [ ] **Step 3: 全テスト最終確認**

Run: `uv run pytest -q`
Expected: PASS（realgui は skip）

- [ ] **Step 4: 品質ゲート + コミット**

Run: `uv run ruff check src/ tests/ ; uv run ruff format --check src/ tests/ ; uv run mypy src/`
Expected: エラーなし

```bash
git add docs/multi-axis-empty-region-followup.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: 多軸 空リージョン follow-up 案B（高さ保持）解決を反映

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0141ptfNpsj6CMDA6REtu7Pi
EOF
)"
```

---

## Self-Review

**1. Spec coverage（design doc 各節 → タスク対応）:**
- 根本原因 / 2責務分離 → Task 1。
- 比例維持・ゼロ退避 → Task 2。
- `remove_signal` 比例維持・冪等 → Task 3。
- `prune_missing_signals` 比例維持・列スコープ → Task 4。
- `_normalize_axes` 廃止・全呼び出し元置換・docstring/テスト更新 → Task 1。
- Layer A（VM 純ロジック）→ Task 2–4。
- Layer A/B 結合 E2E（unload→prune）→ Task 5。
- Layer C（実 divider + 実 Remove File）→ Task 6。
- 配線事実（remove_signal 未配線）→ Task 5/6 が prune 側を対象にする形で反映。
- スコープ外（等分挙動・隣接加算）→ 変更せず（default False 維持）。

**2. Placeholder スキャン:** TBD/TODO なし。各コードステップは実コードを記載。

**3. Type 整合:** `_compact_axes(self) -> None`、`_relayout_columns(self, *, preserve_heights: bool = False) -> None` を Task 1→2 で一貫使用。`remove_signal`/`prune_missing_signals` は両メソッドを呼ぶ形で統一。テストヘルパ `_col`/`_keys`/`_loaded_session`/`_make_view`/`_write_csv`/`_csv_format` は既存定義を参照（Task 5 で import 追加）。
