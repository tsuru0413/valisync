# analysis-correctness（AN-01/02/03）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 範囲統計とカーソル補間が非有限値（NaN/Inf）・単一サンプル信号で黙って誤る3件（AN-01/02/03）を、共通の `Signal.finite_view()`（非有限値サンプルを除いた時系列ビュー）で解消する。

**Architecture:** `sorted_view()` と同型の `finite_view()`（キャッシュ＋zero-copy fast path＋delegate）を Signal に追加し、`RangeStatistics.compute` と `Interpolator.interpolate` を `sorted_view()` → `finite_view()` に切替。これで統計は有限値のみ集計（count=有限数）、補間は NaN をまたいで有限サンプル間を補間、単一有限サンプルは ZOH 前方保持になる。

**Tech Stack:** Python 3.12/3.13・numpy・pytest。

## Global Constraints

- 品質ゲート（コミット前に全通過）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- コメントは WHY を書く。全角括弧・記号は docstring/コメントで RUF001/002/003 に触れるため半角化するか `# noqa: RUF00x`。
- `Signal` は frozen dataclass — キャッシュ属性は `object.__setattr__` で設定。
- `finite_view` のフィルタは**値のみ**（`np.isfinite(values)`）。タイムスタンプの非有限はロード時（LD-03）に排除済み前提。
- `count` の意味は本増分で「範囲内総数」→「範囲内の有限数」へ変わる（Req 13.4 更新・設計 §3.2）。

---

### Task 1: `Signal.finite_view()`

`sorted_view()` の上に載る、値が非有限（NaN/Inf）のサンプルを除いた時系列ビュー。同じキャッシュ/最適化パターン（zero-copy fast path・delegate）を踏襲する。

**Files:**
- Modify: `src/valisync/core/models/signal.py`（`sorted_view` の直後に `finite_view` を追加）
- Test: `tests/test_signal_sorted_view.py`（末尾に finite_view テスト群を追加）

**Interfaces:**
- Consumes: `Signal.sorted_view()`（既存）・namespaced ラッパーの `_sorted_view_delegate`（既存・`signal_group_manager.py:88` で設定）
- Produces: `Signal.finite_view(self) -> tuple[np.ndarray, np.ndarray]`（時刻ソート済み・値が有限のみ・キャッシュ）

- [ ] **Step 1: finite_view のテストを書く**

`tests/test_signal_sorted_view.py` の末尾に追加:

```python
# ─── finite_view (AN-01/02/03 共通土台) ──────────────────────────────────────


def test_finite_view_all_finite_is_zero_copy() -> None:
    """全値有限なら sorted_view の配列をそのまま返す (zero-copy)."""
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    sv = sig.sorted_view()
    fv = sig.finite_view()
    assert fv[0] is sv[0] and fv[1] is sv[1]


def test_finite_view_drops_nan_and_inf() -> None:
    """NaN/Inf の値を持つサンプルを除去し時刻と値が対応する."""
    sig = _sig([0.0, 1.0, 2.0, 3.0], [1.0, np.nan, np.inf, 4.0])
    ts, vs = sig.finite_view()
    assert ts.tolist() == [0.0, 3.0]
    assert vs.tolist() == [1.0, 4.0]


def test_finite_view_all_non_finite_is_empty() -> None:
    """全値が非有限なら空ビュー."""
    ts, vs = _sig([0.0, 1.0], [np.nan, np.inf]).finite_view()
    assert ts.tolist() == [] and vs.tolist() == []


def test_finite_view_cached() -> None:
    """2 回目の呼び出しは同一オブジェクト (キャッシュ)."""
    sig = _sig([0.0, 1.0], [np.nan, 2.0])
    first = sig.finite_view()
    assert sig.finite_view()[0] is first[0]


def test_finite_view_readonly_when_filtered() -> None:
    """フィルタ発生時の配列は read-only."""
    ts, vs = _sig([0.0, 1.0], [np.nan, 2.0]).finite_view()
    assert not ts.flags.writeable and not vs.flags.writeable
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_signal_sorted_view.py -k finite_view -v`
Expected: FAIL（`AttributeError: 'Signal' object has no attribute 'finite_view'`）

- [ ] **Step 3: `finite_view` を実装**

`src/valisync/core/models/signal.py` の `sorted_view` メソッド（`is_monotonic` プロパティの直前）の直後に追加:

```python
    def finite_view(self) -> tuple[np.ndarray, np.ndarray]:
        """Finite-valued view for read-out and statistics (AN-01/02/03).

        Builds on ``sorted_view()`` and drops samples whose *value* is
        non-finite (NaN or +/-Inf), so cursor read-out and range statistics
        operate on real data only. All-finite signals get the sorted arrays
        back untouched (zero-copy). Cached; the computation is idempotent so
        racing initialisations are harmless. Timestamps are already finite by
        load-time guarantee (LD-03), so only values are filtered.
        """
        cache = getattr(self, "_finite_view_cache", None)
        if cache is not None:
            return cache
        # namespaced ラッパーは元 Signal に委譲し、非有限スキャンを元で1回だけ
        # 走らせる (render/カーソルのホットパスで毎回作り直されるラッパー対策)
        delegate = getattr(self, "_sorted_view_delegate", None)
        if delegate is not None:
            cache = delegate.finite_view()
            object.__setattr__(self, "_finite_view_cache", cache)
            return cache
        ts, vs = self.sorted_view()
        if len(vs) == 0 or bool(np.all(np.isfinite(vs))):
            cache = (ts, vs)  # zero-copy fast path
        else:
            mask = np.isfinite(vs)
            ts_f = ts[mask]
            vs_f = vs[mask]
            ts_f.flags.writeable = False
            vs_f.flags.writeable = False
            cache = (ts_f, vs_f)
        object.__setattr__(self, "_finite_view_cache", cache)
        return cache
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/test_signal_sorted_view.py -k finite_view -v`
Expected: PASS（5 テスト）

- [ ] **Step 5: delegate 共有のテストを追加**

namespaced ラッパー経由でも finite_view が元 Signal と一致することを確認（`group_signals` が返すラッパーの挙動保証）。`tests/test_signal_sorted_view.py` に追加:

```python
def test_finite_view_delegate_shared_with_namespaced_wrapper() -> None:
    """_sorted_view_delegate を持つラッパーは元 Signal の finite_view を共有."""
    orig = _sig([0.0, 1.0, 2.0], [1.0, np.nan, 3.0])
    wrapper = _sig([0.0, 1.0, 2.0], [1.0, np.nan, 3.0])
    object.__setattr__(wrapper, "_sorted_view_delegate", orig)
    assert wrapper.finite_view()[0] is orig.finite_view()[0]
```

- [ ] **Step 6: 通過を確認**

Run: `uv run pytest tests/test_signal_sorted_view.py -k finite_view -v`
Expected: PASS（6 テスト）

- [ ] **Step 7: ゲート＋コミット**

```bash
uv run ruff check src/valisync/core/models/signal.py tests/test_signal_sorted_view.py
uv run ruff format src/valisync/core/models/signal.py tests/test_signal_sorted_view.py
uv run mypy src/
git add src/valisync/core/models/signal.py tests/test_signal_sorted_view.py
git commit -m "feat(core): Signal.finite_view — 非有限値を除いた時系列ビュー (AN-01/02/03 共通土台)"
```

---

### Task 2: AN-01 — 範囲統計を有限ビューへ

`RangeStatistics.compute` を `finite_view()` に切替。範囲内の統計は有限値のみで算出、`count` は範囲内の有限サンプル数になる。

**Files:**
- Modify: `src/valisync/core/statistics/range_stats.py:44`（`sorted_view()` → `finite_view()`）
- Test: `tests/test_statistics.py`（NaN/Inf-in-range のテストを追加）

**Interfaces:**
- Consumes: `Signal.finite_view()`（Task 1）
- Produces: `RangeStatistics.compute` の挙動更新（count=範囲内の有限数）

- [ ] **Step 1: 非有限を含む範囲のテストを書く**

`tests/test_statistics.py` に追加:

```python
def test_range_with_nan_and_inf_uses_finite_only() -> None:
    """範囲内に NaN/Inf を含んでも有限値のみで統計・count は有限数 (AN-01)."""
    sig = _sig([0.0, 1.0, 2.0, 3.0, 4.0], [10.0, math.nan, math.inf, 20.0, 30.0])
    res = RangeStatistics().compute(sig, 0.0, 4.0)
    assert res.count == 3  # 有限は 10, 20, 30
    assert res.mean == 20.0
    assert res.max == 30.0
    assert res.min == 10.0
    assert math.isfinite(res.std)


def test_range_all_non_finite_yields_nan_zero_count() -> None:
    """範囲内が全て非有限なら count=0・全 NaN (AN-01)."""
    sig = _sig([0.0, 1.0], [math.nan, math.inf])
    res = RangeStatistics().compute(sig, 0.0, 1.0)
    assert res.count == 0
    assert math.isnan(res.mean) and math.isnan(res.std)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_statistics.py -k "nan_and_inf or all_non_finite" -v`
Expected: FAIL（現行は NaN 混在で mean=nan・count=5、Inf で mean=inf）

- [ ] **Step 3: `compute` を finite_view へ切替**

`src/valisync/core/statistics/range_stats.py` の `ts, vs = signal.sorted_view()` を変更:

```python
        ts, vs = signal.finite_view()
```

（docstring に一文追記: 範囲内の非有限値サンプルは除外し、`count` は範囲内の有限サンプル数を表す（AN-01）。他は不変。）

- [ ] **Step 4: 通過＋既存無回帰を確認**

Run: `uv run pytest tests/test_statistics.py tests/test_pbt_statistics.py -v`
Expected: PASS（新2テスト＋既存の全有限テストは finite_view が zero-copy なので不変）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/core/statistics/range_stats.py tests/test_statistics.py
uv run ruff format src/valisync/core/statistics/range_stats.py tests/test_statistics.py
uv run mypy src/
git add src/valisync/core/statistics/range_stats.py tests/test_statistics.py
git commit -m "fix(core): 範囲統計を有限値のみで算出 (AN-01) — count は範囲内の有限数"
```

---

### Task 3: AN-02 + AN-03 — 補間を有限ビューへ

`Interpolator.interpolate` を `finite_view()` に切替、`len < 2` 分岐を有限サンプル数ベースの3分岐へ。NaN をまたいで補間（AN-02）、単一有限サンプルは ZOH 前方保持（AN-03）。

**Files:**
- Modify: `src/valisync/core/interpolation/interpolator.py:33-58`
- Test: `tests/test_interpolation.py`（挙動変更する2テストを更新＋新規テスト）

**Interfaces:**
- Consumes: `Signal.finite_view()`（Task 1）
- Produces: `Interpolator.interpolate` の挙動更新（NaN 除外補間・単一サンプル ZOH 前方保持）

- [ ] **Step 1: 挙動変更する既存テストを新契約へ更新＋新規テストを追加**

`tests/test_interpolation.py` の該当2テストを置換:

```python
@pytest.mark.parametrize("method", list(InterpolationMethod))
def test_single_sample_zoh_forward_hold(method: InterpolationMethod) -> None:
    """単一サンプルは t>=ts0 で値を保持・t<ts0 は None (AN-03・方式非依存)."""
    sig = _sig([5.0], [1.0])
    interp = Interpolator()
    assert interp.interpolate(sig, 5.0, method) == 1.0  # 厳密一致
    assert interp.interpolate(sig, 9.0, method) == 1.0  # 前方保持 (ZOH)
    assert interp.interpolate(sig, 4.0, method) is None  # サンプル以前


def test_all_non_finite_signal_returns_none() -> None:
    """全値が非有限の信号は有限サンプル0で None (AN-02/03)."""
    sig = _sig([0.0, 1.0], [math.nan, math.inf])
    assert Interpolator().interpolate(sig, 0.5, LINEAR) is None


def test_linear_interpolates_across_nan_gap() -> None:
    """NaN サンプルを欠測として除外し前後の有限サンプル間で線形補間 (AN-02)."""
    sig = _sig([0.0, 5.0, 10.0], [0.0, math.nan, 100.0])
    # 有限は (0,0) と (10,100) → t=5 は線形で 50
    assert Interpolator().interpolate(sig, 5.0, LINEAR) == 50.0


def test_nan_adjacent_now_uses_finite_neighbors() -> None:
    """2 サンプルの片方が NaN → 有限は1点 → ZOH 前方保持で解釈 (AN-02+03)."""
    interp = Interpolator()
    left_nan = _sig([0.0, 10.0], [math.nan, 100.0])  # 有限は (10,100) のみ
    right_nan = _sig([0.0, 10.0], [0.0, math.nan])  # 有限は (0,0) のみ
    assert interp.interpolate(left_nan, 5.0, LINEAR) is None  # t=5 < 10
    assert interp.interpolate(right_nan, 5.0, LINEAR) == 0.0  # t=5 >= 0 保持
```

削除する既存テスト: `test_insufficient_samples_returns_none`（→ `test_single_sample_zoh_forward_hold` に置換）・`test_linear_nan_adjacent_propagates`（→ `test_nan_adjacent_now_uses_finite_neighbors` に置換）。docstring 冒頭の Req 参照（12.10/12.11）を「AN-02/03 で更新」に書き換える。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_interpolation.py -k "zoh_forward or across_nan or non_finite or finite_neighbors" -v`
Expected: FAIL（現行は単一サンプルで常に None・NaN 隣接で NaN 伝播）

- [ ] **Step 3: `interpolate` を finite_view へ切替＋3分岐化**

`src/valisync/core/interpolation/interpolator.py` の本体（`ts, vs = signal.sorted_view()` から NaN 分岐まで）を置換:

```python
        ts, vs = signal.finite_view()
        n = len(ts)

        # AN-02/03: finite_view が非有限値サンプルを除くので、以降 vs は有限のみ。
        if n == 0:
            return None
        # AN-03: 単一サンプルは ZOH 前方保持 (t>=ts0 で値・t<ts0 は None)。
        # 方式に依らず保持 — 1 点では補間対象がないため。
        if n == 1:
            return float(vs[0]) if t >= ts[0] else None

        # 複数サンプルの範囲外は従来どおり None (右端範囲外は本増分では据え置き)
        if t < ts[0] or t > ts[-1]:
            return None

        idx = int(np.searchsorted(ts, t, side="left"))
        if idx < len(ts) and ts[idx] == t:  # 厳密一致 (vs[idx] は有限保証)
            return float(vs[idx])

        # t は ts[idx-1] と ts[idx] の間 (両端とも有限 — AN-02 の NaN 分岐は消滅)
        lo, hi = idx - 1, idx

        if method is InterpolationMethod.LINEAR:
            alpha = (t - ts[lo]) / (ts[hi] - ts[lo])
            return float(vs[lo] + alpha * (vs[hi] - vs[lo]))

        if method is InterpolationMethod.ZERO_ORDER_HOLD:
            return float(vs[lo])

        if method is InterpolationMethod.NEAREST:
            if (t - ts[lo]) <= (ts[hi] - t):
                return float(vs[lo])
            return float(vs[hi])

        raise ValueError(f"unknown InterpolationMethod: {method!r}")
```

docstring を新契約へ更新（単一サンプル ZOH 前方保持・NaN は欠測として除外し有限サンプル間で補間）。

- [ ] **Step 4: 通過＋既存無回帰を確認**

Run: `uv run pytest tests/test_interpolation.py tests/test_pbt_interpolation.py -v`
Expected: PASS（新テスト＋既存の全有限テストは finite_view が zero-copy なので不変）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/core/interpolation/interpolator.py tests/test_interpolation.py
uv run ruff format src/valisync/core/interpolation/interpolator.py tests/test_interpolation.py
uv run mypy src/
git add src/valisync/core/interpolation/interpolator.py tests/test_interpolation.py
git commit -m "fix(core): 補間を有限ビューへ — NaN 除外補間 (AN-02)・単一サンプル ZOH 前方保持 (AN-03)"
```

---

### Task 4: ドキュメント更新（catalog・roadmap・CLAUDE.md）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（AN-01/02/03 を ✅解消に）
- Modify: `docs/roadmap.md`（SS-ANALYSIS 完了）
- Modify: `CLAUDE.md`（改善サブスペックの状況）

- [ ] **Step 1: catalog の AN 行を解消済みへ更新**

`docs/audit-findings-catalog.md` の SS-ANALYSIS セクション（AN-01/02/03）を更新:

- AN-01: 「✅**解消** 範囲統計を `Signal.finite_view()`（非有限値を除いた時系列ビュー）で算出し、有限値のみで mean/max/min/std・`count` は範囲内の有限サンプル数。NaN/Inf 一律除外」
- AN-02: 「✅**解消** 補間を `finite_view()` へ — NaN サンプルを欠測として除外し前後の有限サンプル間で補間（散在 NaN でも読める）」
- AN-03: 「✅**解消** 単一有限サンプルは ZOH 前方保持（t≥ts0 で値・t<ts0 は None）」

- [ ] **Step 2: roadmap の SS-ANALYSIS を更新**

`docs/roadmap.md` の②表 `analysis-correctness` 行を「✅完了（AN-01/02/03・finite_view 共通土台）」相当へ更新し、必要なら着手起点の記述を調整。

- [ ] **Step 3: CLAUDE.md を更新**

改善サブスペックの状況記述に `analysis-correctness` 完了（AN-01/02/03・`Signal.finite_view()` 追加）と spec/plan へのポインタを追記。

- [ ] **Step 4: 最終ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add docs/ CLAUDE.md
git commit -m "docs: analysis-correctness (AN-01/02/03) を catalog/roadmap/CLAUDE.md へ反映"
```

---

## Self-Review

- **Spec coverage**: §3.1 finite_view → Task 1／§3.2 AN-01 → Task 2／§3.3 AN-02+AN-03 → Task 3／§4 docs → Task 4。全カバー。
- **型整合**: `finite_view(self) -> tuple[np.ndarray, np.ndarray]` を Task 1 で定義し Task 2/3 が消費。戻り契約（時刻ソート済み・値有限のみ）は両消費側の前提と一致。
- **プレースホルダ**: なし（各ステップに実コード）。
- **既存挙動の変更明示**: Task 2 は既存の全有限統計テストが無回帰（finite_view zero-copy）、Task 3 は挙動変更する2テスト（`test_insufficient_samples_returns_none`・`test_linear_nan_adjacent_propagates`）を新契約へ置換。各タスクに無回帰確認 Step を配置。
- **GUI**: 表示改修なし（`count==0`→NO_DATA 既存）。GUI テストへの波及は無い見込みだが、Task 4 前の最終 `uv run pytest` で全体無回帰を確認。
