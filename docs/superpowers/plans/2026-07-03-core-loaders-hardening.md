# core-loaders-hardening 第1弾（TS 堅牢化）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 非単調/重複タイムスタンプ・nan/inf・重複名・空データを「弾く」から「記録どおり受け入れて診断で透明化」へ転換し、サイレントなデータ欠損を根治する（LD-03/04/05/06/08/09）。

**Architecture:** `Signal` の厳密単調検証を撤廃し生データを無改変保持。core が1箇所で提供する整列ビュー `Signal.sorted_view()`（安定ソート＋重複 keep-last・単調時は zero-copy）に、単調前提の全消費経路（補間・統計・LOD・formula・派生演算・export・描画）を切替える。ローダーは異常を O(n) 検出して Diagnostic warning を発行（受け皿は FB の Diagnostics ドック・既設）。

**Tech Stack:** Python 3.12/3.13・numpy・hypothesis（既存 pbt スイート）・PySide6・pytest/pytest-qt・ruff・mypy。

**Spec:** [docs/superpowers/specs/2026-07-03-core-loaders-hardening-design.md](../specs/2026-07-03-core-loaders-hardening-design.md)

## Global Constraints

- 品質ゲート（コミット前に全通過・プロジェクト全体スコープ）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- **生データ無改変**: ローダー・Signal はデータを書き換えない（整列は sorted_view の遅延評価のみ・LD-08 の名前変更は例外で warning 必須）。
- **タスク順序厳守**: Task 1（検証緩和）→ Task 2-4（消費経路切替）→ Task 5-6（ローダーが非単調を流し始める）。順序を崩すと「非単調 Signal が未切替の消費経路に流れる」中間状態が生じる。
- キャンセル（`cancel` パラメータ・`LoadCancelled`）・`LoadOutcome`/診断伝播の既存挙動は不変。
- 同一性検証は参照保持＋`is` 比較（`id()` 禁止 — memory: `gui_id_reuse_flake_object_recreation`）。
- コメントは WHY を書く。コメント内の全角括弧は RUF003 に注意（日本語文字列リテラルは可）。
- GUI 入力経路の変更なし（`/gui-verify` はゲート対象外判定＋headless full のみ。新規 realgui 不要）。
- worktree では作業前に `uv sync --extra dev`。

---

## File Structure

**core（Task 1-3, 5-6）**
- Modify `src/valisync/core/models/signal.py` — 検証緩和・`sorted_view()`・`is_monotonic`。
- Modify `src/valisync/core/interpolation/interpolator.py` / `statistics/range_stats.py` / `downsampler/downsampler.py` — sorted_view 切替。
- Modify `src/valisync/core/formula/engine.py` / `session.py` / `export/csv_exporter.py` — sorted_view 切替。
- Modify `src/valisync/core/loaders/mdf4_loader.py` / `csv_loader.py` — 受け入れ＋検出診断。

**gui（Task 4）**
- Modify `src/valisync/gui/viewmodels/graph_panel_vm.py` — render 窓/auto-fit の sorted_view 切替。

**切替対象外（監査済み・変更しない）**: `sync/synchronizer.py:44`（定数加算のみ・順序保存）・`signal_group_manager.py:75`（namespaced 生コピー）・`graph_panel_vm.py:628`/`graph_panel_view.py:790`（downsampler/render の出力側）。

---

## Task 1: `Signal` — 検証緩和＋`sorted_view`/`is_monotonic`

**Files:**
- Modify: `src/valisync/core/models/signal.py`
- Test: `tests/test_pbt_signal.py`（追加）・`tests/test_session.py`（追加は不要・既存緑維持）
- Create: `tests/test_signal_sorted_view.py`

**Interfaces:**
- Produces: `Signal` は非単調/重複タイムスタンプを受け入れる（維持する不変条件: 長さ一致・**タイムスタンプ有限**・配列 read-only 化）。`Signal.sorted_view() -> tuple[np.ndarray, np.ndarray]`（厳密単調・重複 keep-last・単調時は生配列そのものを返す zero-copy・遅延キャッシュ）。`Signal.is_monotonic: bool`（fast path 判定＝`sorted_view()[0] is timestamps`）。

- [ ] **Step 1: Write the failing tests**

`tests/test_signal_sorted_view.py`（新規）:

```python
"""Signal.sorted_view — 記録どおり保持＋整列ビュー（spec §4.1）の単体テスト."""

from __future__ import annotations

import numpy as np
import pytest

from valisync.core.models import Signal


def _sig(ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        name="s",
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def test_non_monotonic_signal_is_accepted():
    sig = _sig([0.0, 2.0, 1.0], [10.0, 20.0, 30.0])  # 旧実装では ValueError
    assert len(sig.timestamps) == 3


def test_sorted_view_sorts_and_is_strictly_monotonic():
    sig = _sig([0.0, 2.0, 1.0], [10.0, 20.0, 30.0])
    ts, vs = sig.sorted_view()
    assert ts.tolist() == [0.0, 1.0, 2.0]
    assert vs.tolist() == [10.0, 30.0, 20.0]
    assert np.all(np.diff(ts) > 0)


def test_sorted_view_keep_last_on_duplicates():
    # 同一タイムスタンプは記録順で最後の値が残る（CAN 後勝ち・spec §3-3）
    sig = _sig([0.0, 1.0, 1.0, 2.0], [1.0, 2.0, 3.0, 4.0])
    ts, vs = sig.sorted_view()
    assert ts.tolist() == [0.0, 1.0, 2.0]
    assert vs.tolist() == [1.0, 3.0, 4.0]


def test_sorted_view_fast_path_returns_raw_arrays():
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    ts, vs = sig.sorted_view()
    assert ts is sig.timestamps  # zero-copy（参照同一・is 比較）
    assert vs is sig.values
    assert sig.is_monotonic


def test_sorted_view_cached_and_raw_unchanged():
    raw_ts = [0.0, 2.0, 1.0]
    sig = _sig(raw_ts, [1.0, 2.0, 3.0])
    first = sig.sorted_view()
    assert sig.sorted_view()[0] is first[0]  # キャッシュ（再計算しない）
    assert sig.timestamps.tolist() == raw_ts  # 生データ無改変
    assert not sig.is_monotonic


def test_sorted_view_len0_and_len1():
    assert _sig([], []).sorted_view()[0].tolist() == []
    assert _sig([5.0], [1.0]).sorted_view()[0].tolist() == [5.0]
    assert _sig([], []).is_monotonic


def test_all_identical_timestamps_collapse_to_one():
    sig = _sig([1.0, 1.0, 1.0], [7.0, 8.0, 9.0])
    ts, vs = sig.sorted_view()
    assert ts.tolist() == [1.0]
    assert vs.tolist() == [9.0]  # keep-last


def test_non_finite_timestamps_still_rejected():
    with pytest.raises(ValueError, match="non-finite"):
        _sig([0.0, float("nan")], [1.0, 2.0])


def test_sorted_view_arrays_are_readonly():
    ts, vs = _sig([0.0, 2.0, 1.0], [1.0, 2.0, 3.0]).sorted_view()
    assert not ts.flags.writeable
    assert not vs.flags.writeable
```

`tests/test_pbt_signal.py` に追加（既存の hypothesis スタイルに合わせる）:

```python
@given(
    ts=st.lists(
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False),
        min_size=0,
        max_size=60,
    )
)
def test_pbt_sorted_view_monotonic_and_keep_last(ts: list[float]) -> None:
    # values に元 index を入れ、keep-last（同値 ts の最後の記録が残る）を検証
    vs = [float(i) for i in range(len(ts))]
    sig = Signal(
        name="p",
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )
    s_ts, s_vs = sig.sorted_view()
    assert np.all(np.diff(s_ts) > 0)  # 厳密単調
    assert len(s_ts) == len(set(ts))  # 重複は1点に縮退
    for t, v in zip(s_ts.tolist(), s_vs.tolist(), strict=True):
        # v は元配列で t が最後に現れた index
        assert int(v) == max(i for i, x in enumerate(ts) if x == t)
    assert sig.timestamps.tolist() == ts  # 生データ無改変
```

> `tests/test_pbt_signal.py` の既存 import（`given`/`st`/`np`/`Signal`）を再利用。既存の「非単調で ValueError」を assert するテストがあれば、本タスクで「受け入れ＋sorted_view で単調」を assert する形に**書き換える**（削除ではなく意味の反転を明示）。

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_signal_sorted_view.py -v`
Expected: FAIL（`test_non_monotonic_signal_is_accepted` が ValueError／`sorted_view` 未定義）。

- [ ] **Step 3: Implement — signal.py**

`__post_init__` の厳密単調検証（signal.py:33-38）を**削除**し、フィールドコメントを更新:

```python
    timestamps: (
        np.ndarray
    )  # float64, shape=(n,), all finite; 記録どおり（非単調・重複あり得る）
```

```python
    def __post_init__(self) -> None:
        if len(self.timestamps) != len(self.values):
            raise ValueError(
                f"timestamps ({len(self.timestamps)}) and values ({len(self.values)}) "
                "must have the same length"
            )
        if len(self.timestamps) > 0 and not np.all(np.isfinite(self.timestamps)):
            idx = int(np.argmax(~np.isfinite(self.timestamps)))
            raise ValueError(f"timestamps contains non-finite value at index {idx}")
        ...  # 以降の copy/read-only 化は不変
```

クラス末尾にメソッド追加:

```python
    def sorted_view(self) -> tuple[np.ndarray, np.ndarray]:
        """Strictly-monotonic view for computation and rendering (spec §4.1).

        Stable-sorts by timestamp and keeps the last-recorded value for equal
        timestamps (CAN "last received wins"). Already-monotonic signals get
        the raw arrays back untouched (zero-copy), so the common case costs
        one O(n) diff check. Cached after the first call; the computation is
        idempotent, so racing initialisations are harmless.
        """
        cache = getattr(self, "_sorted_view_cache", None)
        if cache is not None:
            return cache
        ts, vs = self.timestamps, self.values
        if len(ts) < 2 or bool(np.all(np.diff(ts) > 0)):
            cache = (ts, vs)
        else:
            order = np.argsort(ts, kind="stable")
            ts_s = ts[order]
            vs_s = vs[order]
            # keep-last: 安定ソートで同値 ts は記録順のまま並ぶので、各ランの
            # 末尾（次の ts が大きくなる位置）だけ残せば「最後の記録」が勝つ
            keep = np.concatenate((np.diff(ts_s) > 0, [True]))
            ts_s = ts_s[keep]
            vs_s = vs_s[keep]
            ts_s.flags.writeable = False
            vs_s.flags.writeable = False
            cache = (ts_s, vs_s)
        object.__setattr__(self, "_sorted_view_cache", cache)
        return cache

    @property
    def is_monotonic(self) -> bool:
        """True when the sorted view is the raw arrays (zero-copy fast path)."""
        return self.sorted_view()[0] is self.timestamps
```

- [ ] **Step 4: Run tests / 既存 suite の影響確認**

Run: `uv run pytest tests/test_signal_sorted_view.py tests/test_pbt_signal.py -v` → PASS。
Run: `uv run pytest -q` → 既存テストで「非単調 ValueError」を前提にしたものが赤になる場合は Step 1 の注記どおり意味を反転して更新（対象は赤くなったテストのみ・report に列挙）。

- [ ] **Step 5: 型・lint**

Run: `uv run mypy src/ && uv run ruff check && uv run ruff format --check` → clean。

- [ ] **Step 6: Commit**

```bash
git add src/valisync/core/models/signal.py tests/
git commit -m "feat(core): Signal の厳密単調検証を撤廃し sorted_view を新設（記録どおり保持・LD-03/04 基盤）"
```

---

## Task 2: 計算系の sorted_view 切替（interpolator・range_stats・downsampler）

**Files:**
- Modify: `src/valisync/core/interpolation/interpolator.py:33-34`
- Modify: `src/valisync/core/statistics/range_stats.py:44-45`
- Modify: `src/valisync/core/downsampler/downsampler.py:29-34`
- Test: `tests/test_interpolation.py`・`tests/test_statistics.py`・`tests/test_downsampler.py`（各に非単調入力テストを追加）

**Interfaces:**
- Consumes: `Signal.sorted_view()`（Task 1）。
- Produces: 3コンポーネントとも非単調入力で「同データを整列済みで渡した場合と同値」の結果。`Downsampler.downsample` のパススルーは**単調時のみ** signal をそのまま返し、非単調＋`len<=n` では整列ビューから Signal を再構築して返す。

- [ ] **Step 1: Write the failing tests**

各テストファイルに追加（`_sig`/既存ヘルパはファイル内の流儀に合わせる）:

```python
# tests/test_interpolation.py
def test_interpolate_non_monotonic_input_matches_sorted():
    messy = _sig([0.0, 2.0, 1.0], [0.0, 20.0, 10.0])
    tidy = _sig([0.0, 1.0, 2.0], [0.0, 10.0, 20.0])
    interp = Interpolator()
    for t in (0.5, 1.0, 1.5):
        assert interp.interpolate(messy, t, InterpolationMethod.LINEAR) == \
            interp.interpolate(tidy, t, InterpolationMethod.LINEAR)


# tests/test_statistics.py
def test_range_stats_non_monotonic_uses_keep_last():
    # t=1.0 の重複は後勝ち（3.0 が有効・2.0 は集計に入らない）
    messy = _sig([0.0, 1.0, 1.0, 2.0], [1.0, 2.0, 3.0, 4.0])
    result = RangeStatistics().compute(messy, 0.0, 2.0)
    assert result.count == 3
    assert result.max == 4.0
    assert result.mean == pytest.approx((1.0 + 3.0 + 4.0) / 3)


# tests/test_downsampler.py
def test_downsample_non_monotonic_output_is_monotonic():
    ts = [float(x) for x in [0, 5, 1, 6, 2, 7, 3, 8, 4, 9]]
    sig = _sig(ts, [float(i) for i in range(10)])
    out = Downsampler().downsample(sig, 4)
    assert np.all(np.diff(out.timestamps) > 0)


def test_downsample_passthrough_non_monotonic_returns_sorted_signal():
    sig = _sig([0.0, 2.0, 1.0], [1.0, 2.0, 3.0])  # len<=n のパススルー経路
    out = Downsampler().downsample(sig, 10)
    assert np.all(np.diff(out.timestamps) > 0)
    assert out.timestamps.tolist() == [0.0, 1.0, 2.0]


def test_downsample_passthrough_monotonic_returns_same_object():
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    assert Downsampler().downsample(sig, 10) is sig  # fast path は無コピー維持
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_interpolation.py tests/test_statistics.py tests/test_downsampler.py -k "non_monotonic or keep_last" -v`
Expected: FAIL（現行は生配列を直接使用）。

- [ ] **Step 3: Implement**

`interpolator.py:33-34`:

```python
        ts, vs = signal.sorted_view()
```

`range_stats.py:44-45`:

```python
        ts, vs = signal.sorted_view()
```

`downsampler.py:29-34` — 取得とパススルーを差し替え:

```python
        ts, vs = signal.sorted_view()

        # Req 14.4: pass-through when already within target.
        # 非単調入力では raw をそのまま返すと下流（render）に非単調が漏れる
        # ため、整列ビューから作り直した Signal を返す（単調なら無コピー）。
        if len(ts) <= n:
            if signal.is_monotonic:
                return signal
            return Signal(
                name=signal.name,
                timestamps=ts,
                values=vs,
                file_format=signal.file_format,
                bus_type=signal.bus_type,
                source_file=signal.source_file,
                metadata=signal.metadata,
            )
```

（バケット処理以降は `ts`/`vs` が整列済みになるだけで無変更。「Because timestamps are strictly increasing」のコメントは sorted_view 前提として真のまま。）

- [ ] **Step 4: Run tests / gates**

Run: 上記3ファイル -v → PASS（既存含む）。
Run: `uv run pytest -q && uv run mypy src/ && uv run ruff check && uv run ruff format --check` → 全緑。

- [ ] **Step 5: Commit**

```bash
git add src/valisync/core/interpolation/ src/valisync/core/statistics/ src/valisync/core/downsampler/ tests/
git commit -m "feat(core): 補間・範囲統計・Downsampler を sorted_view に切替（非単調入力の受け皿）"
```

---

## Task 3: 派生/出力系の sorted_view 切替（formula・session 演算・export）

**Files:**
- Modify: `src/valisync/core/formula/engine.py:319-332, 350-354`
- Modify: `src/valisync/core/session.py:197-198, 302-358`
- Modify: `src/valisync/core/export/csv_exporter.py:49-73`
- Test: `tests/test_calcbar.py`・`tests/test_export.py`・`tests/test_session.py`（非単調入力テストを追加）

**Interfaces:**
- Consumes: `Signal.sorted_view()`。
- Produces: formula の結果タイムライン・calcbar 派生信号（`_derive` は整列軸で構築）・CSV export・`SourceInfo.t_min/t_max` が非単調入力でも整列済みデータ基準で正しい。

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calcbar.py
def test_integrate_non_monotonic_matches_sorted():
    messy = _sig([0.0, 2.0, 1.0], [1.0, 3.0, 2.0])
    tidy = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    session = Session()
    out_m = session.integrate(messy)
    out_t = session.integrate(tidy)
    assert out_m.timestamps.tolist() == out_t.timestamps.tolist()
    assert out_m.values.tolist() == out_t.values.tolist()
    assert np.all(np.diff(out_m.timestamps) > 0)  # Derived は整列軸


# tests/test_export.py
def test_export_shared_timeline_non_monotonic_sorted_rows(tmp_path):
    sig = _sig([0.0, 2.0, 1.0], [10.0, 30.0, 20.0])
    out = tmp_path / "o.csv"
    CsvExporter().export([sig], out, unified_timeline=False)  # 既存 API 名に合わせる
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    ts_col = [float(line.split(",")[0]) for line in lines[1:]]
    assert ts_col == sorted(ts_col)


# tests/test_session.py
def test_source_info_time_range_non_monotonic(tmp_path):
    # 非単調 CSV は Task 6 まで作れないため、group へ直接 Signal を積んで検証
    session = Session()
    messy = _sig([5.0, 1.0, 3.0], [1.0, 2.0, 3.0])
    key = session._groups.add(_group_of([messy]))  # 既存テストの group 生成ヘルパに合わせる
    info = session.source_info(key)
    assert info.t_min == 1.0 and info.t_max == 5.0
```

> `_group_of` 相当（`SignalGroup(signals=..., source_path=..., file_format=..., loaded_at=...)` を組むヘルパ）が無ければ最小で作る。export の API 名・引数はファイル冒頭の既存テストに合わせて調整（Step 実装コードの対象は `_rows_unified_timeline`/`_rows_shared_timeline`）。

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_calcbar.py tests/test_export.py tests/test_session.py -k non_monotonic -v` → FAIL。

- [ ] **Step 3: Implement**

`formula/engine.py` — 結果タイムライン（:319-332）:

```python
    if any(len(signals[n].timestamps) == 0 for n in refs):
        return np.array([], dtype=np.float64)

    t_start = max(signals[n].sorted_view()[0][0] for n in refs)
    t_end = min(signals[n].sorted_view()[0][-1] for n in refs)
    if t_start > t_end:
        return np.array([], dtype=np.float64)

    parts: list[np.ndarray] = []
    for n in refs:
        ts = signals[n].sorted_view()[0]
        parts.append(ts[(ts >= t_start) & (ts <= t_end)])
```

`_Evaluator._interp`（:350-354）:

```python
    def _interp(self, name: str) -> np.ndarray:
        sig = self._signals[name]
        if len(sig.timestamps) == 0 or len(self._result_ts) == 0:
            return np.zeros(len(self._result_ts), dtype=np.float64)
        ts, vs = sig.sorted_view()  # np.interp は単調な xp が前提
        return np.interp(self._result_ts, ts, vs)
```

`session.py` — `source_info`（:197-198）:

```python
        t_mins = [s.sorted_view()[0][0] for s in group.signals if len(s.timestamps)]
        t_maxs = [s.sorted_view()[0][-1] for s in group.signals if len(s.timestamps)]
```

`session.py` — calcbar 演算（:302-358）。`_require_min_samples` を整列ペア返しに変更し、4演算と `_derive` を追従:

```python
    @staticmethod
    def _require_min_samples(signal: Signal, op: str) -> tuple[np.ndarray, np.ndarray]:
        """Return the sorted (timestamps, values), raising if fewer than 2 samples."""
        t, v = signal.sorted_view()
        if len(v) < 2:
            raise ValueError(f"{op} requires at least 2 samples, got {len(v)}")
        return t, v
```

```python
    def moving_average(self, signal: Signal, window: int) -> Signal:
        """Simple moving average with a shrinking head window (Req 26.1)."""
        t, v = self._require_min_samples(signal, "moving_average")
        n = len(v)
        if not (1 <= window <= n):
            raise ValueError(f"window must be in 1..{n} (signal length), got {window}")
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            start = max(0, i - window + 1)
            out[i] = v[start : i + 1].mean()
        return self._derive(signal, f"sma({signal.name})", out, t)

    def linear_regression(self, signal: Signal) -> Signal:
        """Least-squares line evaluated on the (sorted) input timestamps (Req 26.2)."""
        t, v = self._require_min_samples(signal, "linear_regression")
        slope, intercept = np.polyfit(t, v, 1)
        return self._derive(signal, f"linreg({signal.name})", slope * t + intercept, t)

    def differentiate(self, signal: Signal) -> Signal:
        """Numerical derivative: central difference, one-sided at ends (Req 26.3)."""
        t, v = self._require_min_samples(signal, "differentiate")
        d = np.empty(len(v), dtype=np.float64)
        d[1:-1] = (v[2:] - v[:-2]) / (t[2:] - t[:-2])
        d[0] = (v[1] - v[0]) / (t[1] - t[0])
        d[-1] = (v[-1] - v[-2]) / (t[-1] - t[-2])
        return self._derive(signal, f"diff({signal.name})", d)  # ← t を渡す（下記シグネチャ）

    def integrate(self, signal: Signal) -> Signal:
        """Cumulative trapezoidal integral, starting at 0.0 (Req 26.4)."""
        t, v = self._require_min_samples(signal, "integrate")
        segments = (v[1:] + v[:-1]) / 2.0 * (t[1:] - t[:-1])
        cumulative = np.concatenate([[0.0], np.cumsum(segments)])
        return self._derive(signal, f"integ({signal.name})", cumulative, t)

    def _derive(
        self, source: Signal, name: str, values: np.ndarray, timestamps: np.ndarray
    ) -> Signal:
        """Build a Derived_Signal on the sorted axis its values were computed on."""
        return Signal(
            name=name,
            timestamps=timestamps,
            values=values,
            file_format="Derived",
            bus_type="",
            source_file="",
            metadata={},
        )
```

> `differentiate` も `_derive(..., d, t)` に統一（上のコメントは transcription 注意用 — 4演算とも第4引数 `t` を渡す）。`_derive` の呼び出し元は本ファイル内の4演算のみ（grep で確認してから変更）。

`csv_exporter.py` — 2メソッドを整列ビュー基準に:

```python
    def _rows_unified_timeline(self, signals: list[Signal]) -> list[str]:
        """Align all signals onto the sorted union of their timestamps (Req 7.4)."""
        names = [s.name for s in signals]
        header = ",".join([_TIMESTAMP_HEADER, *names])

        views = [s.sorted_view() for s in signals]
        unified = np.unique(np.concatenate([ts for ts, _vs in views]))
        # Per-signal lookup from exact timestamp to value（keep-last 済みで一意）.
        lookups = [
            dict(zip(ts.tolist(), vs.tolist(), strict=True)) for ts, vs in views
        ]
        ...  # 以降不変

    def _rows_shared_timeline(self, signals: list[Signal]) -> list[str]:
        """Build CSV lines assuming all signals share one timestamp axis."""
        names = [s.name for s in signals]
        header = ",".join([_TIMESTAMP_HEADER, *names])
        # 共有軸前提: 各信号の ts は同一配列なので keep 判定も同一 index になる
        timestamps = signals[0].sorted_view()[0]
        sorted_values = [s.sorted_view()[1] for s in signals]
        lines = [header]
        for i in range(len(timestamps)):
            cells = [_fmt(timestamps[i])]
            cells.extend(_fmt(vs[i]) for vs in sorted_values)
            lines.append(",".join(cells))
        return lines
```

- [ ] **Step 4: Run tests / gates**

Run: `uv run pytest tests/test_calcbar.py tests/test_export.py tests/test_session.py tests/test_pbt_formula.py tests/test_pbt_calcbar.py -v` → PASS。
Run: `uv run pytest -q && uv run mypy src/ && uv run ruff check && uv run ruff format --check` → 全緑。

- [ ] **Step 5: Commit**

```bash
git add src/valisync/core/ tests/
git commit -m "feat(core): formula・calcbar 派生・export・SourceInfo を sorted_view に切替"
```

---

## Task 4: GUI render の sorted_view 切替（graph_panel_vm）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py:491-494, 578-579, 896-899`
- Test: `tests/gui/test_graph_panel_vm.py`（追加）

**Interfaces:**
- Consumes: `Signal.sorted_view()`。
- Produces: render 窓切出し（searchsorted）と auto-fit 範囲（ts0/tsN）が非単調 Signal でも正しい。`RenderCurve.timestamps` は常に厳密単調。

- [ ] **Step 1: Write the failing test**

`tests/gui/test_graph_panel_vm.py` に追加（session へ非単調 Signal を直接積む — fixture はファイル内既存パターンを再利用し、`x_range を広く固定`する。memory: `gui_offset_render_test_xrange_pitfall`）:

```python
def test_render_data_non_monotonic_signal_yields_monotonic_curve(...):
    # 既存 fixture で panel/vm を組み、非単調 Signal を session に登録して add_signal
    ...
    vm.x_range = (0.0, 10.0)  # auto-fit に依存しない広い固定窓
    curves = vm.render_data(...)
    ts = curves[0].timestamps
    assert len(ts) > 0
    assert np.all(np.diff(ts) > 0)
```

> fixture・`render_data`/`curves` の実シグネチャはファイル内の既存 render テストに合わせて具体化する（このタスクの実装者はまず既存 render テストを1つ読むこと）。

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k non_monotonic -v`
Expected: FAIL（searchsorted が非単調 ts で誤った窓を返す／assert 単調で落ちる）。

- [ ] **Step 3: Implement**

`:578-579`:

```python
            ts, vs = sig.sorted_view()
```

`:491-494` と `:896-899`（同型2箇所・auto-fit 範囲）:

```python
            if sig is None or len(sig.timestamps) == 0:
                continue
            s_ts = sig.sorted_view()[0]
            ts0 = float(s_ts[0])
            tsN = float(s_ts[-1])
```

- [ ] **Step 4: Run tests / gates**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -v` → PASS（既存含む）。
Run: `uv run pytest -q && uv run mypy src/ && uv run ruff check && uv run ruff format --check` → 全緑。

- [ ] **Step 5: Commit**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "feat(gui): render 窓と auto-fit を sorted_view に切替（描画も整列ビュー・spec §3-2）"
```

---

## Task 5: mdf4_loader — 受け入れ＋検出診断（LD-03/05）

**Files:**
- Modify: `src/valisync/core/loaders/mdf4_loader.py:164-182` 周辺
- Test: `tests/test_loaders.py`（追加。mf4 生成は `tests/mdf4_helpers.py` を拡張 — 非単調 ts のチャンネルを書けるようにする）

**Interfaces:**
- Produces: 非単調/重複 ch は受け入れ＋warning「Signal '<name>': 非単調 N 箇所・重複タイムスタンプ M 点（表示/演算は整列ビューで補正）」（`signal_name=base_name`）。非有限 ts の ch は skip＋**error** 診断。0ch 成功時に warning「チャンネルが 0 本です（全チャンネルが読み取り不能）」（LD-05）。

- [ ] **Step 1: Write the failing tests**

`tests/test_loaders.py` に追加:

```python
def test_mdf4_non_monotonic_channel_is_accepted_with_warning(tmp_path):
    path = write_mdf4_non_monotonic(tmp_path)  # helpers に追加（下記）
    result = Mdf4Loader().load(path)
    assert result.signal_group is not None
    names = [s.name for s in result.signal_group.signals]
    assert "messy" in names  # 旧実装では skip されていた
    warnings = [d for d in result.diagnostics if d.level == "warning"]
    assert any("非単調" in d.message or "重複" in d.message for d in warnings)
    messy = next(s for s in result.signal_group.signals if s.name == "messy")
    assert not messy.is_monotonic  # 生データ無改変で受け入れ


def test_mdf4_zero_channels_emits_warning(tmp_path):
    path = write_mdf4_all_channels_bad(tmp_path)  # 全 ch が 2D 等で skip される mf4
    result = Mdf4Loader().load(path)
    assert result.signal_group is not None
    assert len(result.signal_group.signals) == 0
    assert any("0 本" in d.message for d in result.diagnostics)
```

> `tests/mdf4_helpers.py` に `write_mdf4_non_monotonic`（timestamps=[0.0, 2.0, 1.0, 1.0] の ch "messy" ＋正常 ch 1本）と `write_mdf4_all_channels_bad` を追加。既存の `write_mdf4` の asammdf 書き出しパターンを流用（asammdf は非単調 ts の Signal append を許容する — 不可なら raw bytes ではなく既存ヘルパで書いた後に検証を skip する append オプションを調査し、どうしても生成不能なら本テストは monkeypatch で `iter_channels` を差し替える方式に切替えて report に明記）。

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_loaders.py -k "non_monotonic_channel or zero_channels" -v` → FAIL（現行は skip される/警告なし）。

- [ ] **Step 3: Implement — mdf4_loader.py**

Signal 構築部（:164-182）を差し替え:

```python
            # 記録どおり受け入れ、異常は O(n) 検出して診断で透明化（spec §4.2）
            if len(timestamps) > 0 and not np.all(np.isfinite(timestamps)):
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        message=(
                            f"Signal '{base_name}': 非有限タイムスタンプを含むため"
                            " skip（時刻軸が破損）"
                        ),
                        signal_name=base_name,
                    )
                )
                continue

            diffs = np.diff(timestamps)
            n_backward = int(np.sum(diffs < 0))
            n_dup = int(np.sum(diffs == 0))
            if n_backward or n_dup:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"Signal '{base_name}': 非単調 {n_backward} 箇所・"
                            f"重複タイムスタンプ {n_dup} 点"
                            "（表示/演算は整列ビューで補正）"
                        ),
                        signal_name=base_name,
                    )
                )

            signals.append(
                Signal(
                    name=signal_name,
                    timestamps=timestamps,
                    values=values,
                    file_format="MDF4",
                    bus_type=_detect_bus_type(getattr(asammdf_sig, "source", None)),
                    source_file=abs_path,
                    metadata=_extract_metadata(asammdf_sig),
                )
            )
```

（旧 `try/except ValueError` は削除 — 非有限は事前チェック済みで、長さ不一致は asammdf 由来では起きない。）

SignalGroup 構築の直前（:164 付近・0ch 判定）に追加:

```python
        if not signals:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    message="チャンネルが 0 本です（全チャンネルが読み取り不能）",
                )
            )
```

- [ ] **Step 4: Run tests / gates**

Run: `uv run pytest tests/test_loaders.py -v` → PASS。
Run: `uv run pytest -q && uv run mypy src/ && uv run ruff check && uv run ruff format --check` → 全緑。

- [ ] **Step 5: Commit**

```bash
git add src/valisync/core/loaders/mdf4_loader.py tests/
git commit -m "feat(core): MDF4 の非単調/重複 ch を受け入れ＋検出診断（LD-03）・0ch warning（LD-05）"
```

---

## Task 6: csv_loader — 対称化＋品質診断（LD-04/06/08/09）

**Files:**
- Modify: `src/valisync/core/loaders/csv_loader.py`（ヘッダ処理 :90-97・ts パース :128 付近・値パース :146-165・Signal 構築 :178-209）
- Modify: `docs/superpowers/specs/2026-07-03-core-loaders-hardening-design.md` §4.3（LD-08 の連番例示を MDF4 実方式 `name[idx]` に修正 — 原則「MDF4 と同じ」が正・例示が不正確だった）
- Test: `tests/test_loaders.py`（追加）

**Interfaces:**
- Produces: (a) 非単調/重複 ts の CSV が成功＋ファイル単位 warning（LD-04）。(b) 値列の非有限（'nan'/'inf' 由来）は受け入れ＋列ごとの件数 warning（LD-06）。(c) 重複ヘッダは MDF4 と同一の `name[0]`/`name[1]` 方式で曖昧化＋warning（LD-08）。(d) データ行 0 は成功＋warning（LD-09）。(e) ts 列の非有限はファイル失敗（error・時刻軸破損）。

- [ ] **Step 1: Write the failing tests**

`tests/test_loaders.py` に追加（`fmt` は既存の FormatDefinition ヘルパ流用）:

```python
def _load_csv_text(tmp_path, text):
    path = tmp_path / "d.csv"
    path.write_text(text, encoding="utf-8")
    return CsvLoader().load(path, _fmt2())  # ts列0・信号列1-2 の既存ヘルパに合わせる


def test_csv_non_monotonic_is_accepted_with_file_warning(tmp_path):
    result = _load_csv_text(tmp_path, "t,a,b\n0.0,1,2\n2.0,3,4\n1.0,5,6\n1.0,7,8\n")
    assert result.signal_group is not None  # 旧実装ではファイル全滅
    assert any(
        d.level == "warning" and "非単調" in d.message for d in result.diagnostics
    )
    assert not result.signal_group.signals[0].is_monotonic  # 生データ無改変


def test_csv_nan_inf_values_accepted_with_count_warning(tmp_path):
    result = _load_csv_text(tmp_path, "t,a,b\n0.0,nan,1\n1.0,inf,2\n")
    assert result.signal_group is not None
    a = result.signal_group.signals[0]
    assert np.isnan(a.values[0]) and np.isinf(a.values[1])
    assert any("非有限値 2 個" in d.message for d in result.diagnostics)


def test_csv_duplicate_headers_disambiguated_like_mdf4(tmp_path):
    result = _load_csv_text(tmp_path, "t,spd,spd\n0.0,1,2\n1.0,3,4\n")
    names = [s.name for s in result.signal_group.signals]
    assert names == ["spd[0]", "spd[1]"]  # MDF4 と同一方式
    assert any("重複ヘッダ" in d.message for d in result.diagnostics)


def test_csv_header_only_succeeds_with_warning(tmp_path):
    result = _load_csv_text(tmp_path, "t,a,b\n")
    assert result.signal_group is not None
    assert all(len(s.timestamps) == 0 for s in result.signal_group.signals)
    assert any("データ行が 0 行" in d.message for d in result.diagnostics)


def test_csv_non_finite_timestamp_fails_with_error(tmp_path):
    result = _load_csv_text(tmp_path, "t,a,b\n0.0,1,2\nnan,3,4\n")
    assert result.signal_group is None
    assert any(d.level == "error" and "タイムスタンプ" in d.message for d in result.diagnostics)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_loaders.py -k csv -v` → 新規5件 FAIL。

- [ ] **Step 3: Implement — csv_loader.py**

(c) ヘッダ抽出（:90-95）の直後に重複曖昧化を追加（`diagnostics: list[Diagnostic] = []` をファイル冒頭処理に用意し、以降の全 LoadResult 生成で共有する — 既存の単発 tuple 生成箇所は据え置き・成功経路のみ集約）:

```python
        # LD-08: 重複ヘッダは MDF4 と同一の name[idx] 方式で曖昧化（取り違え防止）
        name_total: dict[str, int] = {}
        for n in signal_names:
            name_total[n] = name_total.get(n, 0) + 1
        if any(c > 1 for c in name_total.values()):
            name_seen: dict[str, int] = {}
            renamed: list[str] = []
            for n in signal_names:
                idx = name_seen.get(n, 0)
                name_seen[n] = idx + 1
                renamed.append(f"{n}[{idx}]" if name_total[n] > 1 else n)
            dups = sorted(n for n, c in name_total.items() if c > 1)
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    message=f"重複ヘッダ {dups} を連番で改名（name[idx] 方式）",
                )
            )
            signal_names = renamed
```

(e) ts パース（:128-141 の float 変換成功後）に非有限チェックを追加:

```python
            if not math.isfinite(ts):
                return LoadResult(
                    signal_group=None,
                    diagnostics=(
                        Diagnostic(
                            level="error",
                            message=f"非有限タイムスタンプ {ts_str!r}（時刻軸が破損）",
                            line_number=line_number,
                            column_number=format_def.timestamp_column,
                        ),
                    ),
                )
```

（`import math` を追加。）

(b) 値パース（:146-165）の float 成功側で件数集計:

```python
            for sig_idx, col in enumerate(...):  # 既存ループ
                val_str = row[col]
                try:
                    val = float(val_str)
                except ValueError:
                    ...  # 既存の error return 不変
                if not math.isfinite(val):
                    nonfinite_counts[sig_idx] = nonfinite_counts.get(sig_idx, 0) + 1
                values_lists[sig_idx].append(val)
```

（データ行ループの前に `nonfinite_counts: dict[int, int] = {}` を初期化。）

(a)(d) Signal 構築部（:178-209）を差し替え:

```python
        # --- Build Signal objects ---
        timestamps = np.array(timestamps_list, dtype=np.float64)
        abs_path = str(file_path.resolve())

        # LD-04: 非単調/重複はファイル単位で1件の warning（全列が同一時間軸）
        diffs = np.diff(timestamps)
        n_backward = int(np.sum(diffs < 0))
        n_dup = int(np.sum(diffs == 0))
        if n_backward or n_dup:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    message=(
                        f"タイムスタンプ列: 非単調 {n_backward} 箇所・"
                        f"重複 {n_dup} 点（表示/演算は整列ビューで補正）"
                    ),
                )
            )

        # LD-09: ヘッダのみ（データ行 0）は成功＋warning
        if len(timestamps) == 0:
            diagnostics.append(
                Diagnostic(level="warning", message="データ行が 0 行です")
            )

        signals: list[Signal] = []
        for sig_idx, name in enumerate(signal_names):
            values = np.array(values_lists[sig_idx], dtype=np.float64)
            metadata: dict[str, Any] = {}
            if sig_idx in unit_by_sig_idx:
                metadata["unit"] = unit_by_sig_idx[sig_idx]
            # LD-06: 非有限値は受け入れ（NaN は欠測として正当）・件数を可視化
            if nonfinite_counts.get(sig_idx):
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"'{name}': 非有限値 {nonfinite_counts[sig_idx]} 個"
                            "（'nan'/'inf' 文字列由来）"
                        ),
                        signal_name=name,
                    )
                )
            signals.append(
                Signal(
                    name=name,
                    timestamps=timestamps,
                    values=values,
                    file_format="CSV",
                    bus_type="",
                    source_file=abs_path,
                    metadata=metadata,
                )
            )
```

（旧 `try/except ValueError` は削除 — 非有限 ts は (e) で遮断済み・長さ不一致は構造上起きない。）成功 return の `diagnostics=tuple(diagnostics)` に集約リストを渡す（既存の成功 return を確認して合わせる）。

spec §4.3 の LD-08 例示（`name`・`name_2`…）を実装どおり `name[0]`/`name[1]`（MDF4 と同一）に修正。

- [ ] **Step 4: Run tests / gates**

Run: `uv run pytest tests/test_loaders.py tests/test_pbt_csv.py -v` → PASS。
Run: `uv run pytest -q && uv run mypy src/ && uv run ruff check && uv run ruff format --check` → 全緑。

- [ ] **Step 5: Commit**

```bash
git add src/valisync/core/loaders/csv_loader.py docs/superpowers/specs/2026-07-03-core-loaders-hardening-design.md tests/
git commit -m "feat(core): CSV の非単調受け入れ・nan/inf 件数・重複ヘッダ連番・0行 warning（LD-04/06/08/09）"
```

---

## Task 7: Layer B 接続確認＋`/gui-verify`＋仕上げ

**目的:** 非単調ファイルが end-to-end で「開けて・描けて・診断がドックに残る」ことの結線確認と、①ゲートの対象外判定。

**Files:**
- Test: `tests/gui/test_main_window.py`（追加1件）

- [ ] **Step 1: Layer B 接続テスト**

```python
def test_non_monotonic_csv_loads_and_records_diagnostics(qtbot, tmp_path):
    window = _make_window(qtbot)
    path = tmp_path / "messy.csv"
    path.write_text("t,v\n0.0,1.0\n2.0,2.0\n1.0,3.0\n", encoding="utf-8")
    key = window.app_vm.request_load(path, _csv_format())
    window._on_loaded(  # 実配線と同じ経路で診断を反映
        LoadOutcome(key=key, diagnostics=window.app_vm.session.load(
            path, _csv_format()).diagnostics)
    )
    assert window.diagnostics_vm.counts()[1] >= 1  # warning がドックに載る
```

> 上記は骨子 — 実装時は「`session.load` を2回呼ばない」形に整える（`request_load` は診断を返さないため、`outcome = window.app_vm.session.load(path, _csv_format())` → `window._on_loaded(outcome)` の直接経路で1回に。既存 `test_on_loaded_records_warnings_and_activates` のパターンに合わせる）。

- [ ] **Step 2: Run test** → PASS（Task 6 まで完了していれば RED にならない想定 — 接続確認テストのため sabotage（csv_loader の warning 発行を一時的に外す）で「落ちること」を確認して復元。

- [ ] **Step 3: `/gui-verify`（①ゲート）**

- [ ] `git diff --name-only main...HEAD -- src/valisync/gui/` の変更が `graph_panel_vm.py`（ViewModel・入力経路なし）のみであることを確認 → **GUI 入力経路の変更なし＝realgui ゲート対象外**と判定を記録
- [ ] 念のため描画系 realgui の回帰1本のみ scoped 実行: `uv run pytest --realgui tests/realgui/test_x_axis_zoom_pan.py`（render 供給変更の実機確認・マウス数秒占有）
- [ ] headless full `uv run pytest` 0 errors
- [ ] CI 緑（push 後確認）

- [ ] **Step 4: Commit**

```bash
git add tests/gui/test_main_window.py
git commit -m "test(gui): 非単調 CSV の end-to-end 接続確認（ロード成功＋Diagnostics 表示）"
```

---

## Self-Review

**1. Spec coverage（spec §8 対応表）**
- LD-03 → Task 1（基盤）＋Task 5 ✓／LD-04 → Task 6(a) ✓／LD-05 → Task 5 ✓／LD-06 → Task 6(b) ✓／LD-08 → Task 6(c) ✓／LD-09 → Task 6(d) ✓
- spec §4.1 消費経路の全列挙 → File Structure（切替7ファイル＋対象外4箇所の監査結果）✓
- spec §6 エッジケース → 非有限 ts（T1/T5/T6e）・全点同一（T1）・長さ0/1（T1）・キャッシュ（T1）・Derived 単調（T3 `_derive`）✓
- spec §7 テスト戦略 → pbt（T1）・fast path `is` 比較（T1）・消費経路同値検証（T2/T3）・render 単調 assert（T4）・Layer B 接続（T7）・realgui 対象外判定（T7）✓

**2. Placeholder scan:** Task 4 Step 1 と Task 7 Step 1 のテストは骨子＋「既存パターンに合わせて具体化」の指示付き（fixture 実名が実装時確認事項のため）。Task 5 の mdf4 ヘルパは生成不能時の代替（monkeypatch 方式）まで明記。他は実コード。

**3. Type consistency:** `sorted_view() -> tuple[np.ndarray, np.ndarray]`・`is_monotonic: bool` は T1 定義＝T2-T6 使用で一貫。`_require_min_samples -> tuple` と `_derive(..., timestamps)` の変更は T3 内で完結（呼び出し元4演算のみ・grep 確認手順付き）。`Diagnostic(signal_name=...)` の使用は既存モデルのフィールドどおり。
