# rendering-correctness-perf 増分1（RN-03 リサイズガード＋RN-05 Y軸零幅パディング）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 高さのみのパネルリサイズで無駄な LOD 再計算を止め（RN-03）、定数信号の Y 軸を退化した目盛りでなく可読なレンジで描く（RN-05）。

**Architecture:** 両修正とも `GraphPanelVM`（純 Python ViewModel・Qt 非依存）に閉じる。RN-03 は `set_panel_width` に幅変化ガードを足すだけ。RN-05 はモジュール純関数 `_padded_range` ＋ VM メソッド `_fit_axis` を新設し、オートフィット3経路（`reset_axis_y`・`reset_y`・`_auto_fit_ranges`）の `axis.set_range` を `_fit_axis` 経由へ差し替える。View 層・手動レンジ経路は無変更。

**Tech Stack:** Python 3.13 / PySide6（本増分では import しない）/ numpy / pytest。

**設計 spec:** [docs/superpowers/specs/2026-07-10-rendering-perf-r1-resize-yaxis-design.md](../specs/2026-07-10-rendering-perf-r1-resize-yaxis-design.md)（ブランチ `feature/rendering-perf-r1-resize-yaxis` に commit 済み `a314fe8`）

## Global Constraints

- **MVVM 非変更**: View（`src/valisync/gui/views/graph_panel_view.py`）は無変更。修正は `GraphPanelVM` に閉じる。
- **根本解決**（症状の隠蔽・緩和でない）。
- **RN-03**: 描画キャッシュキーは `(round(x_lo), round(x_hi), panel_width_px, 可視信号キー)` で**高さ非依存**。ゆえに幅が変わらなければ再計算・再通知しない。
- **RN-05 は auto-fit のみ**: パディングは3経路（`reset_axis_y`・`reset_y`・`_auto_fit_ranges`）のみ。手動レンジ（`set_y_range` は `y_range` プロパティ setter 経由・`set_axis_range`）は**pad しない**（ユーザー明示値を尊重）。
- **RN-05 パディング方針**（厳密値）: 零幅検出 = `hi - lo <= max(abs(hi), abs(lo), 1.0) * 1e-9`。中心 `v = (lo + hi) / 2.0`。`pad = abs(v) * 0.5 if v != 0.0 else 1.0`。返り値 `(v - pad, v + pad)`。非退化レンジは恒等（変更しない）。
- `YAxisVM.calculate_virtual_range` の `max(span, 1e-9)` clamp は**残置**（ゼロ除算への二重安全）。
- **realgui 不要**: 両修正は VM 純ロジックで入力イベント経路を持たない。Layer A（ViewModel テスト）で実質を尽くす。
- **品質ゲート**（コミット前に全通過）: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`。
- **コミット trailer 必須**（各コミット末尾）:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4
  ```

---

## File Structure

- `src/valisync/gui/viewmodels/graph_panel_vm.py` — RN-03 の `set_panel_width` ガード（既存メソッド）／RN-05 の `_padded_range`（新規モジュール関数）＋`_fit_axis`（新規メソッド）＋3経路の差し替え。
- `tests/gui/test_graph_panel_vm.py` — 両課題の Layer A テスト（既存の `_register_signal`/`_loaded_vm` 作法を再利用）。

---

## Task 1: RN-03 — 高さのみリサイズでの LOD 再計算ガード

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py:731-735`（`set_panel_width`）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Consumes（既存・変更なし）: `self.panel_width_px: int`（既定 800）・`self._invalidate_cache()`・`self._notify(str)`。
- Produces: `set_panel_width(px: int) -> None`（幅不変なら no-op、幅変化なら従来通り invalidate＋notify）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_vm.py` の末尾に追記（`_loaded_vm` は既存ヘルパ・パネル既定幅 800）:

```python
# ─── RN-03: height-only resize guard ─────────────────────────────────────────


def test_set_panel_width_unchanged_is_noop(tmp_path: Path) -> None:
    """A height-only resize re-calls set_panel_width with the SAME width. Since
    LOD depends on panel_width_px (never height), that must NOT invalidate the
    cache or notify (RN-03). A different width still invalidates as before."""
    vm = _loaded_vm(tmp_path)
    vm.set_panel_width(640)  # move off the 800 default to a known width

    calls: list[int] = []
    original = vm._invalidate_cache

    def spy() -> None:
        calls.append(1)
        original()

    vm._invalidate_cache = spy  # type: ignore[method-assign]

    vm.set_panel_width(640)  # same width -> no work
    assert calls == []

    vm.set_panel_width(320)  # different width -> invalidates like before
    assert calls == [1]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py::test_set_panel_width_unchanged_is_noop -v`
Expected: FAIL（ガード未実装で同幅でも `_invalidate_cache` が呼ばれ `calls == [1]` になり `assert calls == []` が落ちる）

- [ ] **Step 3: 幅変化ガードを実装**

`graph_panel_vm.py:731-735` の `set_panel_width` を次へ置換:

```python
    def set_panel_width(self, px: int) -> None:
        """Update the panel pixel width; invalidates the render cache.

        Height-only resizes re-call this with an unchanged width. LOD depends on
        panel_width_px (part of the render cache key), never on height, so
        re-fitting then is pure waste -- bail out unless the pixel budget
        actually changed (RN-03).
        """
        if px == self.panel_width_px:
            return
        self.panel_width_px = px
        self._invalidate_cache()
        self._notify("range")
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py::test_set_panel_width_unchanged_is_noop -v`
Expected: PASS

- [ ] **Step 5: フルスイート＋ゲート**

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors（既存の panel_width/render テストが幅変化時の挙動不変で PASS）

- [ ] **Step 6: コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "$(cat <<'EOF'
fix(gui): 高さのみリサイズでの無駄な LOD 再計算を回避（幅不変ガード・RN-03）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4
EOF
)"
```

---

## Task 2: RN-05 — 定数信号の零幅 Y 軸を可読レンジへ正規化

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`_padded_range` 新規モジュール関数を `_CACHE_KEY_DECIMALS`〔:45〕付近に追加／`_fit_axis` 新規メソッド／3経路 `reset_axis_y`:630・`reset_y`:726・`_auto_fit_ranges`:1252-1253 の `set_range` 差し替え）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Consumes（既存・変更なし）: `YAxisVM.set_range(lo: float | None, hi: float | None)`（`y_axis_vm.py`・import 済み L27）・`YAxisVM.y_range`・`YAxisVM.calculate_virtual_range()`・`self._axes: list[YAxisVM]`・`add_signal` が `_auto_fit_ranges` を呼ぶ（:244）。
- Produces:
  - モジュール関数 `_padded_range(lo: float, hi: float) -> tuple[float, float]`（両引数 non-None float。零幅を中心対称拡張・非退化は恒等）。
  - メソッド `GraphPanelVM._fit_axis(self, axis: YAxisVM, lo: float | None, hi: float | None) -> None`（None は clear・非 None は `_padded_range` を通して `set_range`）。auto-fit 専用。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_vm.py` の末尾に追記。まず定数信号 VM ヘルパを足し（既存 `_register_signal` 再利用）、続けてテスト:

```python
# ─── RN-05: constant-signal Y-axis padding ───────────────────────────────────


def _constant_vm(tmp_path: Path, value: float) -> GraphPanelVM:
    """A GraphPanelVM with one constant-valued signal plotted (values all == value)."""
    session = Session()
    sig = Signal(
        name="flag",
        timestamps=np.array([0.0, 1.0, 2.0], dtype=np.float64),
        values=np.array([value, value, value], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )
    key = _register_signal(session, sig, tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    return vm


def test_padded_range_identity_for_normal_span() -> None:
    """A non-degenerate range passes through unchanged."""
    from valisync.gui.viewmodels.graph_panel_vm import _padded_range

    assert _padded_range(0.0, 20.0) == (0.0, 20.0)


def test_constant_signal_autofit_is_padded(tmp_path: Path) -> None:
    """A constant signal (v=5) auto-fits to a non-degenerate window centred on v
    (+/-50% -> (2.5, 7.5)) instead of the degenerate (5, 5) (RN-05)."""
    vm = _constant_vm(tmp_path, 5.0)
    lo, hi = vm._axes[0].y_range
    assert lo < hi
    assert (lo + hi) / 2.0 == pytest.approx(5.0)
    assert (lo, hi) == pytest.approx((2.5, 7.5))


def test_constant_zero_signal_uses_unit_window(tmp_path: Path) -> None:
    """A constant zero signal cannot use a relative pad; it gets [-1, 1] (RN-05)."""
    vm = _constant_vm(tmp_path, 0.0)
    assert vm._axes[0].y_range == pytest.approx((-1.0, 1.0))


def test_constant_signal_virtual_range_has_finite_span(tmp_path: Path) -> None:
    """calculate_virtual_range yields a sensible (non-1e-9) span once padded."""
    vm = _constant_vm(tmp_path, 5.0)
    v_lo, v_hi = vm._axes[0].calculate_virtual_range()
    assert v_hi - v_lo > 1e-6


def test_manual_set_y_range_zero_width_not_padded(tmp_path: Path) -> None:
    """Manual range entry is the user's explicit value and must NOT be padded,
    even when degenerate (auto-fit-only policy, RN-05)."""
    vm = _loaded_vm(tmp_path)
    vm.set_y_range(3.0, 3.0)
    assert vm._axes[0].y_range == (3.0, 3.0)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "padded_range or constant_signal or constant_zero or manual_set_y_range" -v`
Expected: FAIL — `test_padded_range_identity_for_normal_span` は `ImportError`（`_padded_range` 未定義）、`test_constant_signal_autofit_is_padded` は `y_range == (5.0, 5.0)` で `(2.5, 7.5)` に一致せず落ちる（`test_manual_set_y_range_zero_width_not_padded` は現状でも通り得るが、Step 3 後も通ることでガードを担保）。

- [ ] **Step 3: `_padded_range` と `_fit_axis` を実装し3経路を差し替え**

3-1. モジュール関数を追加（`graph_panel_vm.py` の `_CACHE_KEY_DECIMALS: int = 9`〔:45〕の直後、`class GraphPanelVM` の前）:

```python
def _padded_range(lo: float, hi: float) -> tuple[float, float]:
    """Expand a degenerate (~zero-width) auto-fit range around its centre.

    A constant signal fits to (v, v); mapped verbatim that yields a 1e-9-wide,
    degenerate Y axis (RN-05). Widen it to a readable window centred on v:
    +/-50% of |v|, or [-1, 1] when v == 0. Non-degenerate ranges pass through
    unchanged. Auto-fit callers only -- manual set_y_range keeps exact values.
    """
    if hi - lo > max(abs(hi), abs(lo), 1.0) * 1e-9:
        return (lo, hi)
    v = (lo + hi) / 2.0
    pad = abs(v) * 0.5 if v != 0.0 else 1.0
    return (v - pad, v + pad)
```

3-2. VM にメソッドを追加（クラス内・`set_panel_width` の近く等、既存メソッド群の間で可）:

```python
    def _fit_axis(self, axis: YAxisVM, lo: float | None, hi: float | None) -> None:
        """Store an auto-fit result on *axis*, widening a degenerate constant-signal
        span so its Y axis stays readable (RN-05). None lo/hi clears the range
        (nothing fittable), matching the prior set_range(None, None) behaviour.
        """
        if lo is not None and hi is not None:
            lo, hi = _padded_range(lo, hi)
        axis.set_range(lo, hi)
```

3-3. 3経路の `set_range` を `_fit_axis` へ差し替え:

`reset_axis_y`（:630）:
```python
        self._fit_axis(self._axes[axis_index], lo, hi)
```
（旧 `self._axes[axis_index].set_range(lo, hi)` を置換）

`reset_y`（:726）:
```python
            self._fit_axis(axis, lo, hi)
```
（旧 `axis.set_range(lo, hi)` を置換・for ループ内のインデント維持）

`_auto_fit_ranges`（:1252-1253）— 旧:
```python
                if lo is not None and hi is not None:
                    axis.set_range(lo, hi)
```
を次へ置換（None ガードは `_fit_axis` が内包）:
```python
                self._fit_axis(axis, lo, hi)
```

（注: 手動経路 `set_y_range`〔`y_range` プロパティ setter 経由〕・`set_axis_range`〔:600〕は `set_range` 直呼びのまま **変更しない**＝pad されない。）

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "padded_range or constant_signal or constant_zero or manual_set_y_range" -v`
Expected: PASS（5 件）

- [ ] **Step 5: 既存オートフィット無回帰を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -v`
Expected: 既存の add_signal/reset_y/reset_x/複数軸テストが全 PASS（非退化レンジは `_padded_range` が恒等なので `_loaded_vm` 等の `y_range==(0.0, 20.0)` 期待は不変）。赤があれば非退化レンジで恒等になっているか（`_padded_range(0,20)==(0,20)`）を確認。

- [ ] **Step 6: フルスイート＋ゲート**

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 7: コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "$(cat <<'EOF'
fix(gui): 定数信号の零幅 Y 軸を可読レンジへ正規化（auto-fit 中心対称パディング・RN-05）

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01F5VXcbpjjaqgABi8iPZeo4
EOF
)"
```

---

## Self-Review（プラン執筆後チェック）

**1. Spec coverage:**
- RN-03（幅ガード・キャッシュ高さ非依存の根拠）→ Task 1。✅
- RN-05（`_padded_range`・auto-fit 3経路のみ・手動非 pad・v==0=[-1,1]・中央対称・非退化恒等・clamp 残置）→ Task 2。✅
- テスト戦略（RN-03 invalidate スパイの弁別／RN-05 中心レンジ・v0・手動非 pad・恒等・virtual span）→ Task 1 Step1・Task 2 Step1。✅

**2. Placeholder scan:** 各 step に実コード・実コマンド・期待出力あり。TBD/「適宜」等なし。✅

**3. Type consistency:** `_padded_range(lo: float, hi: float) -> tuple[float, float]`（Task 2 定義）を `_fit_axis` が non-None 時に呼ぶ。`_fit_axis(self, axis: YAxisVM, lo: float | None, hi: float | None) -> None` の `axis` は `self._axes[i]`（YAxisVM・import 済み）。3経路の呼び出し `self._fit_axis(self._axes[axis_index], lo, hi)` / `self._fit_axis(axis, lo, hi)` は型一致。`set_panel_width(px: int)`（Task 1）不変シグネチャ。✅
