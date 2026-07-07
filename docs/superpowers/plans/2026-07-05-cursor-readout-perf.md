# カーソル UX 増分①（PC-21 readout 追従再配置＋RN-06 カーソル移動 perf）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** カーソル移動時の範囲統計を O(√n) 化（数値安定な並列分散マージ）＋readout 差分更新で真リアルタイム化（RN-06）し、readout をプロット矩形へ追従再配置してレイアウト崩れを解消する（PC-21）。

**Architecture:** RN-06 core は `RangeStatIndex`（信号の `finite_view()` 上の平方分割インデックス・各ブロックに count/mean/M2/min/max を前計算）を新設し、`Signal.range_stat_index()` で遅延キャッシュ、`RangeStatistics.compute` がそれへ委譲する。RN-06 view は `CursorReadout._rebuild` を「構造不変なら QLabel を `setText` 差分更新」に分岐。PC-21 は `GraphPanelView._reposition_readout()` を幾何変化フックから呼び、`CursorReadout` のユーザードラッグ位置は尊重する。

**Tech Stack:** Python 3.12/3.13・numpy・PySide6 6.x・pytest・pytest-qt・hypothesis。

## Global Constraints

- 品質ゲート（コミット前に全通過・pipe で exit code を隠さない）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- `RangeStatistics.compute` の**契約は不変**: closed range `t_start ≤ ts ≤ t_end`・`finite_view()`（非有限値除外・AN-01）・population std（ddof=0）・空範囲は全 NaN・count 0・`t_start/t_end` 非有限は `ValueError`・`t_start > t_end` は `ValueError`。
- `Signal` は frozen dataclass。派生キャッシュは `object.__setattr__` で書く（`sorted_view`/`finite_view` と同型）。namespaced ラッパーは `_sorted_view_delegate` 経由で元 Signal のキャッシュを共有する。
- コメントは WHY を書く。全角括弧など RUF001/002/003 に触れる文字は半角化するか `# noqa`。
- オブジェクト再生成検証に `id()` を使わない（CPython アドレス再利用でフレーク）— 参照を保持し `is`/`is not` で比較（memory `gui_id_reuse_flake_object_recreation`）。

---

### Task 1: `RangeStatIndex`（平方分割＋並列分散マージ・core）

**Files:**
- Create: `src/valisync/core/statistics/range_stat_index.py`
- Modify: `src/valisync/core/statistics/__init__.py`
- Test: `tests/test_range_stat_index.py`

**Interfaces:**
- Consumes: `StatisticsResult`（`valisync.core.statistics.range_stats`・フィールド `mean/max/min/std: float, count: int`）。
- Produces:
  - `class RangeStatIndex` — `__init__(self, ts: np.ndarray, vs: np.ndarray) -> None`（`ts`=finite かつ狭義昇順・`vs`=finite float64。通常 `Signal.finite_view()` の戻り2要素を渡す）。
  - `query(self, t_start: float, t_end: float) -> StatisticsResult`（closed range `t_start ≤ ts ≤ t_end` の population 統計を O(√n) で返す。空は全 NaN・count 0）。

- [ ] **Step 1: Write the failing test**（property-based 一致＋エッジ）

```python
# tests/test_range_stat_index.py
"""RangeStatIndex — 平方分割インデックスの範囲統計が numpy 直接計算と一致する証明的検証。

設計 spec §4.2 の命題1-6 を、finite_view 上のランダム範囲クエリで実証する。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from valisync.core.statistics.range_stat_index import RangeStatIndex

from .conftest import valid_signals

pytestmark = pytest.mark.property


def _reference(vs_range: np.ndarray) -> tuple[float, float, float, float, int]:
    n = len(vs_range)
    if n == 0:
        nan = float("nan")
        return nan, nan, nan, nan, 0
    return (
        float(np.mean(vs_range)),
        float(np.max(vs_range)),
        float(np.min(vs_range)),
        float(np.std(vs_range, ddof=0)),
        n,
    )


@given(
    valid_signals(allow_nan_values=True),
    st.floats(min_value=0.0, max_value=1.0),
    st.floats(min_value=0.0, max_value=1.0),
)
def test_index_matches_numpy_on_finite_view(signal, f1, f2):
    ts, vs = signal.finite_view()  # finite・昇順（命題1の前提）
    span = float(ts[-1] - ts[0]) if len(ts) else 1.0
    pad = span * 0.1 + 1.0
    lo = (float(ts[0]) if len(ts) else 0.0) - pad
    hi = (float(ts[-1]) if len(ts) else 0.0) + pad
    a = lo + f1 * (hi - lo)
    b = lo + f2 * (hi - lo)
    t_start, t_end = (a, b) if a <= b else (b, a)

    res = RangeStatIndex(ts, vs).query(t_start, t_end)

    in_range = vs[(ts >= t_start) & (ts <= t_end)]
    r_mean, r_max, r_min, r_std, r_count = _reference(in_range)
    assert res.count == r_count
    if r_count == 0:
        assert math.isnan(res.mean) and math.isnan(res.std)
        assert math.isnan(res.max) and math.isnan(res.min)
    else:
        assert res.mean == pytest.approx(r_mean, rel=1e-9, abs=1e-12)
        assert res.std == pytest.approx(r_std, rel=1e-9, abs=1e-12)
        assert res.max == r_max
        assert res.min == r_min


def test_empty_signal_query_is_nan():
    idx = RangeStatIndex(np.array([], dtype=np.float64), np.array([], dtype=np.float64))
    res = idx.query(0.0, 1.0)
    assert res.count == 0 and math.isnan(res.mean) and math.isnan(res.std)


def test_single_sample():
    idx = RangeStatIndex(np.array([1.0]), np.array([5.0]))
    res = idx.query(0.0, 2.0)
    assert res.count == 1
    assert res.mean == 5.0 and res.min == 5.0 and res.max == 5.0 and res.std == 0.0


def test_constant_signal_std_is_zero():
    ts = np.arange(1000, dtype=np.float64)
    vs = np.full(1000, 7.0, dtype=np.float64)
    res = RangeStatIndex(ts, vs).query(0.0, 999.0)
    assert res.count == 1000 and res.mean == 7.0 and res.std == 0.0
    assert res.min == 7.0 and res.max == 7.0


def test_large_mean_small_variance_no_cancellation():
    # 大平均・小分散: 素朴な Σv²−(Σv)²/n はキャンセルで壊れるが並列マージは安定。
    rng = np.random.default_rng(0)
    ts = np.arange(5000, dtype=np.float64)
    vs = 1e8 + rng.normal(0.0, 1e-3, 5000)
    res = RangeStatIndex(ts, vs).query(0.0, 4999.0)
    assert res.std == pytest.approx(float(np.std(vs, ddof=0)), rel=1e-6, abs=1e-9)


def test_range_on_block_boundaries():
    # n=10000 → block≈100。ちょうどブロック境界に一致/跨ぐ範囲で完全ブロック経路を突く。
    ts = np.arange(10000, dtype=np.float64)
    vs = np.sin(ts * 0.01).astype(np.float64)
    idx = RangeStatIndex(ts, vs)
    for a, b in [(0.0, 9999.0), (100.0, 200.0), (150.0, 850.0), (99.0, 101.0)]:
        res = idx.query(a, b)
        in_range = vs[(ts >= a) & (ts <= b)]
        assert res.count == len(in_range)
        assert res.mean == pytest.approx(float(np.mean(in_range)), rel=1e-9, abs=1e-12)
        assert res.std == pytest.approx(
            float(np.std(in_range, ddof=0)), rel=1e-9, abs=1e-12
        )
        assert res.min == float(np.min(in_range))
        assert res.max == float(np.max(in_range))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_range_stat_index.py -q`
Expected: FAIL（`ModuleNotFoundError: valisync.core.statistics.range_stat_index`）

- [ ] **Step 3: Write minimal implementation**

```python
# src/valisync/core/statistics/range_stat_index.py
"""RangeStatIndex — finite_view 上の平方分割で範囲統計を O(√n) に。

設計 spec §4.2 参照。各ブロックに (count, mean, M2, min, max) を前計算し、任意の
closed range を「左部分スライス ⊎ 完全ブロック群 ⊎ 右部分スライス」に分解、各群の
統計を並列分散マージ（Chan/Welford の多群結合）で厳密結合する。M2 は非負項の和で
表せるためカタストロフィックキャンセルが起きず、np.std(ddof=0) と機械精度で一致する。
"""

from __future__ import annotations

import math

import numpy as np

from valisync.core.statistics.range_stats import StatisticsResult


class RangeStatIndex:
    def __init__(self, ts: np.ndarray, vs: np.ndarray) -> None:
        # ts: finite・狭義昇順(finite_view の保証)。vs: finite float64。
        self._ts = ts
        self._vs = vs
        n = len(vs)
        self._n = n
        # ブロックサイズ = ⌈√n⌉。n=0 でも 1 に丸めて空配列を持つ。
        block = max(1, math.isqrt(n))
        self._block = block
        if n == 0:
            self._b_count = np.empty(0, dtype=np.int64)
            self._b_mean = np.empty(0, dtype=np.float64)
            self._b_m2 = np.empty(0, dtype=np.float64)
            self._b_min = np.empty(0, dtype=np.float64)
            self._b_max = np.empty(0, dtype=np.float64)
            return
        nb = (n + block - 1) // block
        b_count = np.empty(nb, dtype=np.int64)
        b_mean = np.empty(nb, dtype=np.float64)
        b_m2 = np.empty(nb, dtype=np.float64)
        b_min = np.empty(nb, dtype=np.float64)
        b_max = np.empty(nb, dtype=np.float64)
        for bi in range(nb):
            s = bi * block
            e = min(s + block, n)
            seg = vs[s:e]
            m = float(seg.mean())
            b_count[bi] = e - s
            b_mean[bi] = m
            b_m2[bi] = float(((seg - m) ** 2).sum())
            b_min[bi] = float(seg.min())
            b_max[bi] = float(seg.max())
        self._b_count = b_count
        self._b_mean = b_mean
        self._b_m2 = b_m2
        self._b_min = b_min
        self._b_max = b_max

    def query(self, t_start: float, t_end: float) -> StatisticsResult:
        ts = self._ts
        lo = int(np.searchsorted(ts, t_start, side="left"))
        hi = int(np.searchsorted(ts, t_end, side="right"))
        if hi <= lo:
            nan = float("nan")
            return StatisticsResult(mean=nan, max=nan, min=nan, std=nan, count=0)

        # 収集した各群の (count, mean, M2, min, max) を多群結合する。
        counts: list[float] = []
        means: list[float] = []
        m2s: list[float] = []
        mins: list[float] = []
        maxs: list[float] = []

        def add_slice(a: int, b: int) -> None:
            if b <= a:
                return
            seg = self._vs[a:b]
            m = float(seg.mean())
            counts.append(float(b - a))
            means.append(m)
            m2s.append(float(((seg - m) ** 2).sum()))
            mins.append(float(seg.min()))
            maxs.append(float(seg.max()))

        block = self._block
        first_full = (lo + block - 1) // block  # 最初の完全内包ブロック index
        last_full = hi // block  # 最後の完全内包ブロックの次(排他)
        if first_full >= last_full:
            # 完全ブロックなし: 全体を1スライスで走査
            add_slice(lo, hi)
        else:
            left_end = first_full * block
            right_start = last_full * block
            add_slice(lo, left_end)
            # 完全ブロック群を1群にベクトル化結合(命題4の多群形)
            cb = self._b_count[first_full:last_full].astype(np.float64)
            mb = self._b_mean[first_full:last_full]
            m2b = self._b_m2[first_full:last_full]
            c_full = float(cb.sum())
            m_full = float((cb * mb).sum() / c_full)
            m2_full = float(m2b.sum() + (cb * (mb - m_full) ** 2).sum())
            counts.append(c_full)
            means.append(m_full)
            m2s.append(m2_full)
            mins.append(float(self._b_min[first_full:last_full].min()))
            maxs.append(float(self._b_max[first_full:last_full].max()))
            add_slice(right_start, hi)

        # 収集群を多群結合: C=Σc, M=Σ(c·mean)/C, M2=ΣM2_g + Σ c_g (mean_g − M)²
        c_arr = np.array(counts, dtype=np.float64)
        m_arr = np.array(means, dtype=np.float64)
        m2_arr = np.array(m2s, dtype=np.float64)
        total_count = float(c_arr.sum())
        total_mean = float((c_arr * m_arr).sum() / total_count)
        total_m2 = float(m2_arr.sum() + (c_arr * (m_arr - total_mean) ** 2).sum())
        var = total_m2 / total_count
        std = math.sqrt(var) if var > 0.0 else 0.0  # 非負項和ゆえ var>=0、負は丸め保険
        return StatisticsResult(
            mean=total_mean,
            max=max(maxs),
            min=min(mins),
            std=std,
            count=int(round(total_count)),
        )
```

そして `__init__.py` に公開追加:

```python
# src/valisync/core/statistics/__init__.py
from valisync.core.statistics.range_stat_index import RangeStatIndex
from valisync.core.statistics.range_stats import RangeStatistics, StatisticsResult

__all__ = ["RangeStatIndex", "RangeStatistics", "StatisticsResult"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_range_stat_index.py -q`
Expected: PASS（6 テスト＋property 全緑）

- [ ] **Step 5: Gate & commit**

```bash
uv run ruff check src/valisync/core/statistics/ tests/test_range_stat_index.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/core/statistics/ tests/test_range_stat_index.py
uv run mypy src/valisync/core/statistics/range_stat_index.py
git add src/valisync/core/statistics/range_stat_index.py src/valisync/core/statistics/__init__.py tests/test_range_stat_index.py
git commit -m "feat(core): RangeStatIndex 平方分割で範囲統計 O(√n)（並列分散マージ・数値安定）"
```

---

### Task 2: `Signal.range_stat_index()` 遅延キャッシュ（delegate 共有）

**Files:**
- Modify: `src/valisync/core/models/signal.py`
- Test: `tests/test_signal_range_stat_index.py`

**Interfaces:**
- Consumes: `RangeStatIndex(ts, vs)`（Task 1）・`Signal.finite_view() -> tuple[np.ndarray, np.ndarray]`。
- Produces: `Signal.range_stat_index(self) -> RangeStatIndex`（初回に `finite_view()` から構築しキャッシュ。`_sorted_view_delegate` があれば元 Signal のインデックスを共有）。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_signal_range_stat_index.py
"""Signal.range_stat_index() の遅延キャッシュと delegate 共有。"""

from __future__ import annotations

import numpy as np

from valisync.core.models import Signal
from valisync.core.statistics import RangeStatIndex


def _sig(vs):
    ts = np.arange(len(vs), dtype=np.float64)
    return Signal(
        name="s",
        timestamps=ts,
        values=np.asarray(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
    )


def test_range_stat_index_is_cached():
    s = _sig([1.0, 2.0, 3.0, 4.0])
    idx = s.range_stat_index()
    assert isinstance(idx, RangeStatIndex)
    assert s.range_stat_index() is idx  # same object reused


def test_query_matches_compute_semantics():
    s = _sig([10.0, 20.0, 30.0])
    res = s.range_stat_index().query(0.0, 2.0)
    assert res.count == 3 and res.mean == 20.0


def test_wrapper_shares_delegate_index():
    base = _sig([1.0, 2.0, 3.0, 4.0])
    wrapper = _sig([1.0, 2.0, 3.0, 4.0])
    object.__setattr__(wrapper, "_sorted_view_delegate", base)
    assert wrapper.range_stat_index() is base.range_stat_index()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_signal_range_stat_index.py -q`
Expected: FAIL（`AttributeError: 'Signal' object has no attribute 'range_stat_index'`）

- [ ] **Step 3: Write minimal implementation**

`src/valisync/core/models/signal.py` の `finite_view()` メソッド直後（`is_monotonic` プロパティの前）に追加:

```python
    def range_stat_index(self) -> "RangeStatIndex":
        """Sqrt-decomposition index over finite_view for O(√n) range statistics.

        Built lazily on first query and cached; racing initialisations are
        harmless (idempotent). namespaced ラッパーは finite_view と同じく
        ``_sorted_view_delegate`` 経由で元 Signal のインデックスを共有し、
        カーソルドラッグのホットパスで毎回作り直されるラッパーでも構築は1回。
        """
        cache = getattr(self, "_range_stat_index_cache", None)
        if cache is not None:
            return cache
        # 循環 import 回避のためメソッド内 import(statistics → models(Signal))。
        from valisync.core.statistics.range_stat_index import RangeStatIndex

        delegate = getattr(self, "_sorted_view_delegate", None)
        if delegate is not None:
            cache = delegate.range_stat_index()
            object.__setattr__(self, "_range_stat_index_cache", cache)
            return cache
        ts, vs = self.finite_view()
        cache = RangeStatIndex(ts, vs)
        object.__setattr__(self, "_range_stat_index_cache", cache)
        return cache
```

`signal.py` 冒頭の `from typing import Any` の直下に型チェック用 import を追加（実行時は循環回避で TYPE_CHECKING）:

```python
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from valisync.core.statistics.range_stat_index import RangeStatIndex
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_signal_range_stat_index.py -q`
Expected: PASS（3 テスト）

- [ ] **Step 5: Gate & commit**

```bash
uv run ruff check src/valisync/core/models/signal.py tests/test_signal_range_stat_index.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/core/models/signal.py tests/test_signal_range_stat_index.py
uv run mypy src/valisync/core/models/signal.py
git add src/valisync/core/models/signal.py tests/test_signal_range_stat_index.py
git commit -m "feat(core): Signal.range_stat_index() 遅延キャッシュ（delegate 共有）"
```

---

### Task 3: `RangeStatistics.compute` を index へ委譲

**Files:**
- Modify: `src/valisync/core/statistics/range_stats.py:25-60`
- Test: 既存 `tests/test_statistics.py`・`tests/test_pbt_statistics.py`（無回帰）＋ `tests/test_range_stat_index.py`（委譲一致を1件追加）

**Interfaces:**
- Consumes: `Signal.range_stat_index()`（Task 2）。
- Produces: `RangeStatistics.compute(signal, t_start, t_end) -> StatisticsResult`（契約・戻り型不変。内部で index に委譲）。

- [ ] **Step 1: Write the failing test**（compute が index と一致することを固定）

`tests/test_range_stat_index.py` の末尾に追加:

```python
def test_compute_delegates_to_index():
    from valisync.core.models import Signal
    from valisync.core.statistics import RangeStatistics

    ts = np.arange(2000, dtype=np.float64)
    vs = np.cos(ts * 0.02).astype(np.float64)
    s = Signal(
        name="s",
        timestamps=ts,
        values=vs,
        file_format="Derived",
        bus_type="",
        source_file="",
    )
    a, b = 3.0, 1500.0
    res = RangeStatistics().compute(s, a, b)
    idx = s.range_stat_index().query(a, b)
    assert res.count == idx.count and res.mean == idx.mean and res.std == idx.std
    assert res.min == idx.min and res.max == idx.max
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_range_stat_index.py::test_compute_delegates_to_index -q`
Expected: FAIL（現行 compute は独自 numpy 経路のため std の丸めが index と厳密一致せず、または既に一致でも次段の実装差替で担保）。※既に PASS する場合は Step 3 の差替後も PASS を確認して回帰ガードとする。

- [ ] **Step 3: Write minimal implementation**

`src/valisync/core/statistics/range_stats.py` の `compute` 本体（バリデーション後の `ts, vs = ...` 以降）を index 委譲へ置換:

```python
    def compute(
        self,
        signal: Signal,
        t_start: float,
        t_end: float,
    ) -> StatisticsResult:
        """Return statistics for samples where t_start ≤ timestamp ≤ t_end.

        Raises ValueError when t_start or t_end is NaN/Inf (Req 13.6) or when
        t_start > t_end (Req 13.5). Delegates the range reduction to the
        signal's sqrt-decomposition index (O(√n)); non-finite *values* are
        excluded via finite_view() inside the index and count is the number of
        finite samples in range (AN-01). Empty/all-non-finite range → all-NaN,
        count 0.
        """
        if not math.isfinite(t_start):
            raise ValueError(f"t_start must be finite, got {t_start!r}")
        if not math.isfinite(t_end):
            raise ValueError(f"t_end must be finite, got {t_end!r}")
        if t_start > t_end:
            raise ValueError(f"t_start must be ≤ t_end, got {t_start!r} > {t_end!r}")

        return signal.range_stat_index().query(t_start, t_end)
```

不要になった `import numpy as np` は他で未使用なら削除（ruff が検出）。`math` は残す。

- [ ] **Step 4: Run tests to verify they pass（無回帰込み）**

Run: `uv run pytest tests/test_range_stat_index.py tests/test_statistics.py tests/test_pbt_statistics.py -q`
Expected: PASS（既存統計テスト＋property＋委譲一致すべて緑）

- [ ] **Step 5: Gate & commit**

```bash
uv run ruff check src/valisync/core/statistics/range_stats.py tests/test_range_stat_index.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/core/statistics/range_stats.py
uv run mypy src/valisync/core/statistics/range_stats.py
git add src/valisync/core/statistics/range_stats.py tests/test_range_stat_index.py
git commit -m "refactor(core): RangeStatistics.compute を RangeStatIndex に委譲（契約不変・O(√n)）"
```

---

### Task 4: `CursorReadout` 差分更新（構造不変なら setText）

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`
- Test: `tests/gui/test_cursor_readout_diff.py`

**Interfaces:**
- Consumes: なし（既存の `set_global`/`set_delta`/`set_readings` 呼び出しは不変）。
- Produces: `_rebuild(col_headers, rows)` が構造不変時に既存 QLabel を再利用（`_value_labels: list[list[QLabel]]`・`_swatch_labels: list[QLabel]`・`_row_colors: list[str]`・`_layout_sig`）。

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_cursor_readout_diff.py
"""CursorReadout の差分更新: 行構成不変なら QLabel を再利用し setText で更新する（RN-06）。"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.statistics.range_stats import StatisticsResult
from valisync.gui.viewmodels.graph_panel_vm import DeltaReading
from valisync.gui.views.cursor_readout import CursorReadout


def _dr(name, color, va, dy, stats):
    return DeltaReading(name, color, va, dy, stats, True)


def _stats(mean, mx, mn, std, count):
    return StatisticsResult(mean=mean, max=mx, min=mn, std=std, count=count)


def test_diff_update_reuses_value_labels(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(0.0, 1.0, [_dr("s::a", "#111111", 1.0, 0.1, _stats(1, 2, 0, 0.5, 10))])
    held = w._value_labels[0][0]  # 参照保持（id() 不使用）
    w.set_delta(0.0, 1.0, [_dr("s::a", "#111111", 2.0, 0.2, _stats(2, 3, 1, 0.6, 12))])
    assert w._value_labels[0][0] is held  # 再生成されず再利用
    assert "2" in w.row_texts()[0][1]  # 値は更新済み


def test_row_count_change_triggers_full_rebuild(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(0.0, 1.0, [_dr("s::a", "#111111", 1.0, 0.1, _stats(1, 2, 0, 0.5, 10))])
    held = w._value_labels[0][0]
    w.set_delta(
        0.0,
        1.0,
        [
            _dr("s::a", "#111111", 1.0, 0.1, _stats(1, 2, 0, 0.5, 10)),
            _dr("s::b", "#222222", 5.0, 0.3, _stats(5, 6, 4, 0.7, 10)),
        ],
    )
    assert w._value_labels[0][0] is not held  # 構造変化 → 全再構築


def test_color_change_updates_swatch_in_place(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_delta(0.0, 1.0, [_dr("s::a", "#111111", 1.0, 0.1, _stats(1, 2, 0, 0.5, 10))])
    held = w._swatch_labels[0]
    w.set_delta(0.0, 1.0, [_dr("s::a", "#f9e2af", 1.0, 0.1, _stats(1, 2, 0, 0.5, 10))])
    assert w._swatch_labels[0] is held  # swatch も再利用（色だけ差し替え）
    assert w._row_colors[0] == "#f9e2af"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_cursor_readout_diff.py -q`
Expected: FAIL（`AttributeError: '_value_labels'` — 属性未定義）

- [ ] **Step 3: Write minimal implementation**

`cursor_readout.py` `__init__` の `self._rows: list[...] = []` の直後に差分更新用の参照を追加:

```python
        # 差分更新用: 構造(列見出し＋各行 name/セル数)が不変なら QLabel を再利用し
        # setText で値だけ更新する（毎移動の全 deleteLater/再生成を回避・RN-06）。
        self._value_labels: list[list[QLabel]] = []
        self._swatch_labels: list[QLabel] = []
        self._row_colors: list[str] = []
        self._layout_sig: tuple[tuple[str, ...], tuple[tuple[str, int], ...]] | None = (
            None
        )
```

既存 `_rebuild` を「ディスパッチャ＋全再構築＋差分」に分割。現行 `_rebuild(self, col_headers, rows)` の本体を `_full_rebuild` に移し、参照記録を足す。新 `_rebuild` は構造比較で分岐:

```python
    def _rebuild(
        self,
        col_headers: list[str],
        rows: list[tuple[str, str, list[str]]],
    ) -> None:
        """構造不変なら差分更新、構造が変わったら全再構築（RN-06）。"""
        sig = (
            tuple(col_headers),
            tuple((name, len(cells)) for name, _color, cells in rows),
        )
        if sig == self._layout_sig and len(rows) == len(self._value_labels):
            self._update_in_place(rows)
        else:
            self._full_rebuild(col_headers, rows, sig)

    def _full_rebuild(
        self,
        col_headers: list[str],
        rows: list[tuple[str, str, list[str]]],
        sig: tuple[tuple[str, ...], tuple[tuple[str, int], ...]],
    ) -> None:
        """全 QLabel を破棄・再生成し、差分更新用の参照を記録する。"""
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._rows = []
        self._value_labels = []
        self._swatch_labels = []
        self._row_colors = []
        r0 = 0
        if col_headers:
            for c, head in enumerate(["", "", *col_headers]):
                lbl = QLabel(head)
                lbl.setStyleSheet("color:#7f849c; font-size:9px;")
                lbl.setAlignment(
                    Qt.AlignmentFlag.AlignRight
                    if c >= 2
                    else Qt.AlignmentFlag.AlignLeft
                )
                self._grid.addWidget(lbl, r0, c)
            r0 = 1
        for i, (name, color, cells) in enumerate(rows):
            swatch = QLabel()
            pix = QPixmap(10, 10)
            pix.fill(QColor(color))
            swatch.setPixmap(pix)
            self._grid.addWidget(swatch, r0 + i, 0)
            self._grid.addWidget(QLabel(name), r0 + i, 1)
            vlabels: list[QLabel] = []
            for c, text in enumerate(cells):
                v = QLabel(text)
                v.setAlignment(Qt.AlignmentFlag.AlignRight)
                self._grid.addWidget(v, r0 + i, 2 + c)
                vlabels.append(v)
            self._value_labels.append(vlabels)
            self._swatch_labels.append(swatch)
            self._row_colors.append(color)
            self._rows.append((name, " ".join(cells)))
        self._layout_sig = sig
        self.adjustSize()

    def _update_in_place(
        self,
        rows: list[tuple[str, str, list[str]]],
    ) -> None:
        """既存 QLabel を setText で差分更新（色変化時のみ swatch を差し替え）。"""
        for i, (name, color, cells) in enumerate(rows):
            for c, text in enumerate(cells):
                self._value_labels[i][c].setText(text)
            if self._row_colors[i] != color:
                pix = QPixmap(10, 10)
                pix.fill(QColor(color))
                self._swatch_labels[i].setPixmap(pix)
                self._row_colors[i] = color
            self._rows[i] = (name, " ".join(cells))
        self.adjustSize()
```

- [ ] **Step 4: Run tests to verify they pass（既存 cursor_readout 無回帰込み）**

Run: `uv run pytest tests/gui/test_cursor_readout_diff.py tests/gui/test_cursor_readout.py -q`
Expected: PASS（差分3件＋既存 cursor_readout 全緑）

- [ ] **Step 5: Gate & commit**

```bash
uv run ruff check src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout_diff.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout_diff.py
uv run mypy src/valisync/gui/views/cursor_readout.py
git add src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout_diff.py
git commit -m "feat(gui): CursorReadout 差分更新（構造不変は setText で QLabel 再利用・RN-06）"
```

---

### Task 5: `CursorReadout` ユーザードラッグ検出フラグ（PC-21 の前提）

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`
- Test: `tests/gui/test_cursor_readout_diff.py`（同ファイルに追加）

**Interfaces:**
- Consumes: なし。
- Produces: `was_user_moved(self) -> bool`・`reset_user_moved(self) -> None`（ユーザーがドラッグ移動したら True・GraphPanelView が再配置抑止と復帰に使う）。

- [ ] **Step 1: Write the failing test**

`tests/gui/test_cursor_readout_diff.py` に追加:

```python
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent


def test_drag_sets_user_moved_flag(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    assert w.was_user_moved() is False
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5.0, 5.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mousePressEvent(press)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(40.0, 40.0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseMoveEvent(move)
    assert w.was_user_moved() is True
    w.reset_user_moved()
    assert w.was_user_moved() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_cursor_readout_diff.py::test_drag_sets_user_moved_flag -q`
Expected: FAIL（`AttributeError: 'CursorReadout' object has no attribute 'was_user_moved'`）

- [ ] **Step 3: Write minimal implementation**

`cursor_readout.py` `__init__` の `self._drag_offset ...` 付近に追加:

```python
        # ユーザーが readout をドラッグ移動したか。GraphPanelView は True の間は
        # プロット矩形への自動再配置を抑止する（ユーザー配置を尊重・PC-21）。
        self._user_moved: bool = False
```

`mouseMoveEvent` を移動時にフラグ立てするよう変更:

```python
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(self.pos() + event.position().toPoint() - self._drag_offset)
            self._user_moved = True
        super().mouseMoveEvent(event)
```

introspection セクション（`row_texts` 付近）にアクセサ追加:

```python
    def was_user_moved(self) -> bool:
        """True once the user has drag-repositioned the readout (PC-21)."""
        return self._user_moved

    def reset_user_moved(self) -> None:
        """Clear the user-moved flag so the readout re-anchors to the plot rect."""
        self._user_moved = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gui/test_cursor_readout_diff.py -q`
Expected: PASS

- [ ] **Step 5: Gate & commit**

```bash
uv run ruff check src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout_diff.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout_diff.py
uv run mypy src/valisync/gui/views/cursor_readout.py
git add src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout_diff.py
git commit -m "feat(gui): CursorReadout に user-moved フラグ（PC-21 追従再配置の抑止用）"
```

---

### Task 6: `GraphPanelView._reposition_readout`（PC-21 プロット矩形追従）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`_sync_overlay_geometry:840` 末尾・`_sync_cursor_from_vm:1138`）
- Test: `tests/gui/test_graph_panel_readout_reposition.py`

**Interfaces:**
- Consumes: `CursorReadout.was_user_moved()`/`reset_user_moved()`（Task 5）・`self._view_boxes[0].sceneBoundingRect()`・`self.plot_widget`（QGraphicsView）。
- Produces: `_plot_area_top_left(self) -> QPoint | None`・`_reposition_readout(self) -> None`。

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_graph_panel_readout_reposition.py
"""PC-21: CursorReadout がプロット矩形へ追従再配置され、ユーザードラッグ位置を尊重する。"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import QPoint
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView


def _vm(tmp_path: Path) -> GraphPanelVM:
    csv_file = tmp_path / "d.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "s1"])
        for i in range(100):
            w.writerow([i * 0.01, float(i)])
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    session = Session()
    session.load(csv_file, fmt)
    vm = GraphPanelVM(session)
    vm.add_signal(session.signals()[0].name)
    return vm


def _laid_out_view(qtbot: QtBot, tmp_path: Path) -> GraphPanelView:
    view = GraphPanelView(_vm(tmp_path))
    qtbot.addWidget(view)
    view.resize(1000, 700)
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(
        lambda: bool(view._view_boxes)
        and view._view_boxes[0].sceneBoundingRect().height() > 100
    )
    return view


def test_reposition_moves_readout_to_plot_area(qtbot: QtBot, tmp_path: Path) -> None:
    view = _laid_out_view(qtbot, tmp_path)
    view.vm.set_cursor(0.5)  # readout placed
    view._readout.move(400, 300)  # 意図的に誤配置
    view._reposition_readout()
    tl = view._plot_area_top_left()
    assert tl is not None
    assert view._readout.pos() == QPoint(tl.x() + 8, tl.y() + 8)
    assert view._readout.pos() != QPoint(400, 300)


def test_reposition_respects_user_drag(qtbot: QtBot, tmp_path: Path) -> None:
    view = _laid_out_view(qtbot, tmp_path)
    view.vm.set_cursor(0.5)
    view._readout._user_moved = True  # ユーザーがドラッグ移動した状態
    view._readout.move(400, 300)
    view._reposition_readout()
    assert view._readout.pos() == QPoint(400, 300)  # 動かさない


def test_cursor_clear_resets_user_moved(qtbot: QtBot, tmp_path: Path) -> None:
    view = _laid_out_view(qtbot, tmp_path)
    view.vm.set_cursor(0.5)
    view._readout._user_moved = True
    view.vm.set_cursor(None)  # カーソル消去 → _sync_cursor_from_vm の t is None 経路
    assert view._readout.was_user_moved() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_graph_panel_readout_reposition.py -q`
Expected: FAIL（`AttributeError: 'GraphPanelView' object has no attribute '_reposition_readout'`）

- [ ] **Step 3: Write minimal implementation**

`graph_panel_view.py` に `_sync_cursor_from_vm` の直前（`_sync_overlay_geometry` の後付近でも可）へ2メソッド追加:

```python
    def _plot_area_top_left(self) -> QPoint | None:
        """プロット描画領域(master ViewBox)の左上を GraphPanelView 座標で返す。

        レイアウト未確定(ViewBox 無し)や破棄済み C++ オブジェクトなら None。
        """
        if not self._view_boxes:
            return None
        try:
            scene_tl = self._view_boxes[0].sceneBoundingRect().topLeft()
            view_pt = self.plot_widget.mapFromScene(scene_tl)
            global_pt = self.plot_widget.viewport().mapToGlobal(view_pt)
            return self.mapFromGlobal(global_pt)
        except RuntimeError:
            return None

    def _reposition_readout(self) -> None:
        """readout をプロット矩形左上＋マージンへ移動（ユーザードラッグ位置は尊重・PC-21）。"""
        if self._readout.was_user_moved():
            return
        tl = self._plot_area_top_left()
        if tl is None:
            return
        self._readout.move(tl.x() + 8, tl.y() + 8)
```

`_sync_cursor_from_vm` の初回配置ブロック（`:1166-1171`）を置換:

```python
        if not self._readout_placed:
            # 初回表示時にプロット矩形左上へ配置（以降のカーソル同期では
            # ユーザーがドラッグ移動した位置を乱さない）。
            self._reposition_readout()
            self._readout_placed = True
```

同メソッドの `t is None` 早期 return 部（`:1144-1146`）にユーザー移動フラグのリセットを追加:

```python
        if t is None:
            self._cursor_line.setVisible(False)
            self._cursor_line_b.setVisible(False)
            self._readout.setVisible(False)
            self._readout_placed = False
            self._readout.reset_user_moved()
            return
```

`_sync_overlay_geometry` の末尾（`self._y_axes[i].setGeometry(strip)` ループの後）に追従呼び出しを追加:

```python
        # 幾何変化(軸/カラム追加・リサイズ)後も readout をプロット矩形へ追従させる。
        # _reposition_readout 内で was_user_moved を尊重。init 中の最初の refresh は
        # _readout 未生成なので getattr ガードで skip する。
        if getattr(self, "_readout_placed", False) and not self._readout.isHidden():
            self._reposition_readout()
```

`graph_panel_view.py:28` の import 行に `QPoint` を追加（現状 `QPointF` のみ）:

```python
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gui/test_graph_panel_readout_reposition.py -q`
Expected: PASS（3 テスト）

- [ ] **Step 5: Run cursor 系無回帰**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py tests/gui/test_graph_area_cursor.py tests/gui/test_graph_panel_render_geometry.py -q`
Expected: PASS（既存カーソル/ジオメトリ全緑）

- [ ] **Step 6: Gate & commit**

```bash
uv run ruff check src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_readout_reposition.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_readout_reposition.py
uv run mypy src/valisync/gui/views/graph_panel_view.py
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_readout_reposition.py
git commit -m "feat(gui): CursorReadout をプロット矩形へ追従再配置（PC-21・ドラッグ位置尊重）"
```

---

### Task 7: docs 更新（catalog / roadmap / structure）＋全ゲート

**Files:**
- Modify: `docs/audit-findings-catalog.md`（PC-21・RN-06 を ✅解消 注記）
- Modify: `docs/roadmap.md`（rendering-correctness-perf の RN-06 と plotctl PC-21 の状況更新・増分② を別 spec 予定として記載）
- Modify: `docs/structure.md`（`core/statistics/range_stat_index.py` を追記）

**Interfaces:** なし（ドキュメントのみ）。

- [ ] **Step 1: catalog に解消注記**

`docs/audit-findings-catalog.md` の PC-21 行・RN-06 行に「✅解消（2026-07-05・増分①・PR #<n>）: RangeStatIndex O(√n)＋readout 差分更新／プロット矩形追従再配置」を追記。件数サマリの解消数を+2。

- [ ] **Step 2: roadmap 更新**

`docs/roadmap.md` の該当行に、RN-06（カーソル移動 perf）と PC-21（readout 崩れ）を増分①で解消、増分②（PC-22/PC-13/PC-14 ポインタ形状）を別 spec 予定と明記。

- [ ] **Step 3: structure 更新**

`docs/structure.md` の `core/statistics/` 節に `range_stat_index.py`（平方分割インデックス・範囲統計 O(√n)）を1行追記。

- [ ] **Step 4: 全ゲート**

```bash
uv run pytest -q; echo "pytest exit: ${PIPESTATUS[0]}"
uv run ruff check; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format --check; echo "format exit: ${PIPESTATUS[0]}"
uv run mypy src/
```
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add docs/audit-findings-catalog.md docs/roadmap.md docs/structure.md
git commit -m "docs: カーソル UX 増分①（PC-21/RN-06）解消を catalog/roadmap/structure に反映"
```

---

## Self-Review

**1. Spec coverage:**
- §3 PC-21 追従再配置 → Task 5（フラグ）＋Task 6（`_reposition_readout`＋フック）。✓
- §4.1 O(√n) 範囲統計 → Task 1（`RangeStatIndex`）＋Task 2（Signal キャッシュ）＋Task 3（compute 委譲）。✓
- §4.2 数学的正当性（命題1-6・数値安定・property 検証）→ Task 1 の property-based＋エッジ（定数/大平均小分散/ブロック境界）テスト。✓
- §4.3 readout 差分更新 → Task 4。✓
- §7 テスト戦略（core property・PC-21 Layer B・差分 Layer B・無回帰）→ Task 1/4/5/6 の各テスト＋Task 3/6 の無回帰実行。✓
- §8 ファイル構成 → Task 1（新規 range_stat_index.py＋test）・Task 2-6 の変更が一致。✓

**2. Placeholder scan:** 各コード step は完全なコードを掲載。Task 3 Step 2 は「既に PASS する場合は回帰ガード」と明示（曖昧さ回避）。TBD/TODO なし。✓

**3. Type consistency:** `RangeStatIndex(ts, vs)`・`query(t_start, t_end) -> StatisticsResult` は Task 1/2/3 で一貫。`was_user_moved()`/`reset_user_moved()` は Task 5 定義・Task 6 consume で一致。`_value_labels: list[list[QLabel]]`・`_layout_sig` は Task 4 内で一貫。`_plot_area_top_left() -> QPoint | None` は Task 6 内で一貫。✓

## 非ゴール（増分②・別 spec）
PC-22 カーソル線ホバー形状・PC-13 Y 軸アクティブゲート・PC-14 X ズーム/パン カスタム QCursor（拡張可能なカーソルレジストリ）。coalesce/throttle/ワーカースレッド不採用。
