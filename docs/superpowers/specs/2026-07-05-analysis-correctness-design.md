# 設計 spec: analysis-correctness（AN-01/02/03 — 統計・補間の計算の正しさ）

範囲統計とカーソル補間が非有限値（NaN/Inf）・単一サンプル信号で黙って誤った結果を返す3件を、共通の「有限サンプルビュー」で解消する。いずれも「解析結果がユーザーに気づかれず誤る」サイレント欠陥。

- **作成**: 2026-07-05
- **ステータス**: 設計（brainstorming 承認済み・writing-plans へ）
- **関連**: [audit-findings-catalog](../../audit-findings-catalog.md) SS-ANALYSIS（AN-01/02/03）／LD-06（第1弾）が「統計側の防御は AN-01」と明示的に本増分へ委譲済み
- **前提コード**: `core/statistics/range_stats.py`（`RangeStatistics.compute`）・`core/interpolation/interpolator.py`（`Interpolator.interpolate`）・`core/models/signal.py`（`Signal.sorted_view` のキャッシュ＋zero-copy fast path＋delegate パターン）

---

## 1. スコープと確定判断（brainstorming・ユーザー決定）

| ID | 現状の欠陥 | 決定 |
|---|---|---|
| AN-01 | 範囲内に NaN/Inf を1点でも含むと `np.mean/max/min/std` が全て NaN/Inf・`count` は範囲内総数のまま（`range_stats.py:52-58`） | **有限値のみで算出し `count` を「統計に使った有限サンプル数」に変更**。NaN と Inf は一律 `np.isfinite` で除外。範囲内の有限が0（空 or 全非有限）→ 従来の `count=0`・全 NaN 結果 |
| AN-02 | 線形補間は隣接サンプルの片方でも NaN なら NaN を返す（`interpolator.py:55-56`） | **NaN サンプルを「欠測」として除外し、前後の有限サンプル間で補間**。LINEAR/ZOH/NEAREST いずれも有限サンプル基準（散在 NaN のギャップをまたいで補間する帰結は許容） |
| AN-03 | `len(ts) < 2` は常に None＝単一サンプル信号がカーソル一致でも読めない（`interpolator.py:36-37`） | **単一サンプルは ZOH 前方保持**: `t ≥ ts[0]` なら `vs[0]`・`t < ts[0]` は None。方式に依らず保持 |

**共通土台**: 3件はすべて「値が非有限のサンプルを除いた時系列列」を必要とする。既存 `sorted_view()` と同型の **`Signal.finite_view()`**（新規・src 構造変更としてユーザー承認済み）を1つ追加し、両消費側（統計・補間）が共有する。

## 2. 現状分析（根因の確定事実）

**AN-01（`range_stats.py:44-58`）**: `ts, vs = signal.sorted_view()` → `in_range = vs[(ts>=t_start)&(ts<=t_end)]` → `np.mean/max/min/std(in_range)`。`in_range` に NaN が1点でもあれば mean/std は NaN、Inf があれば mean/std は Inf に伝播。`count = len(in_range)` は非ゼロのまま → 「9999/10000 有効でも統計が全 nan、count は 10000」。

**AN-02（`interpolator.py:53-58`）**: LINEAR 分岐で `if np.isnan(vs[lo]) or np.isnan(vs[hi]): return float("nan")`。1つの NaN サンプルがその前後の**両区間**を読み取り不能にする（散在 NaN で広範囲が nan）。

**AN-03（`interpolator.py:36-37`）**: `if len(ts) < 2: return None`。単一サンプル信号はカーソルを厳密に合わせても常に None。

**消費側（GUI・不変更）**: `cursor_readout.py:158-168` は `r.stats.count == 0` で `_NO_DATA` を出し、非0なら mean/max/min/std/count を `.4g` 表示。`graph_panel_vm.py:754/846-849` がカーソル/デルタで `interpolate`/`compute_statistics` を呼ぶ。表示ロジックの改修は不要。

## 3. 設計

### 3.1 共通土台: `Signal.finite_view()`（新規）

`sorted_view()` の戻り（時刻ソート済み・keep-last 済みの `ts, vs`）を受け、**値が非有限（NaN/Inf 両方）のサンプルを除いた** `(ts_f, vs_f)` を返す。`sorted_view()` と同じキャッシュ/最適化パターンを踏襲:

- **zero-copy fast path**: `np.all(np.isfinite(vs))` が真なら sorted_view の `(ts, vs)` を**そのまま**返す（新規配列を作らない・共通ケースは O(n) の isfinite スキャン1回のみ）。
- **非有限ありの場合**: `mask = np.isfinite(vs)` で `ts[mask], vs[mask]`（fancy indexing で新規配列）。`writeable=False` を立てて返す。
- **キャッシュ**: `_finite_view_cache` に `object.__setattr__`（frozen dataclass・冪等なので競合初期化は無害）。
- **delegate**: namespaced ラッパー（`_sorted_view_delegate` 持ち）は `finite_view` も元 Signal へ委譲し、非有限スキャンを元 Signal で1回だけ走らせる（render/カーソルのホットパスで毎回作り直されるラッパー対策）。
- **フィルタは値のみ**: タイムスタンプの非有限はロード時（LD-03）に error skip 済みで、`finite_view` に非有限 ts は来ない前提。

```python
def finite_view(self) -> tuple[np.ndarray, np.ndarray]:
    cache = getattr(self, "_finite_view_cache", None)
    if cache is not None:
        return cache
    delegate = getattr(self, "_sorted_view_delegate", None)
    if delegate is not None:
        cache = delegate.finite_view()
        object.__setattr__(self, "_finite_view_cache", cache)
        return cache
    ts, vs = self.sorted_view()
    if len(vs) == 0 or bool(np.all(np.isfinite(vs))):
        cache = (ts, vs)  # zero-copy
    else:
        mask = np.isfinite(vs)
        ts_f, vs_f = ts[mask], vs[mask]
        ts_f.flags.writeable = False
        vs_f.flags.writeable = False
        cache = (ts_f, vs_f)
    object.__setattr__(self, "_finite_view_cache", cache)
    return cache
```

### 3.2 AN-01: 範囲統計を有限ビューへ

`RangeStatistics.compute` の `sorted_view()` を `finite_view()` に差し替えるだけ:

```python
ts, vs = signal.finite_view()
in_range = vs[(ts >= t_start) & (ts <= t_end)]
if len(in_range) == 0:                       # 空 or 範囲内が全て非有限
    nan = float("nan")
    return StatisticsResult(mean=nan, max=nan, min=nan, std=nan, count=0)
return StatisticsResult(
    mean=float(np.mean(in_range)), max=float(np.max(in_range)),
    min=float(np.min(in_range)), std=float(np.std(in_range, ddof=0)),
    count=len(in_range),                     # 範囲内の有限サンプル数
)
```

`t_start/t_end` の有限性チェック・`t_start > t_end` チェックは不変（Req 13.5/13.6）。`count` の意味が「範囲内総数」→「範囲内の有限数」に変わる（Req 13.4 の更新）。

### 3.3 AN-02 + AN-03: 補間を有限ビューへ

`Interpolator.interpolate` の `sorted_view()` を `finite_view()` に差し替え、`len < 2` 分岐を有限サンプル数ベースの3分岐へ:

```python
ts, vs = signal.finite_view()
n = len(ts)
if n == 0:
    return None
if n == 1:                                   # AN-03: 単一サンプルは ZOH 前方保持
    return float(vs[0]) if t >= ts[0] else None
if t < ts[0] or t > ts[-1]:                  # 複数サンプルの範囲外は従来どおり None
    return None
idx = int(np.searchsorted(ts, t, side="left"))
if idx < len(ts) and ts[idx] == t:           # 厳密一致（vs[idx] は有限保証）
    return float(vs[idx])
lo, hi = idx - 1, idx                         # 前後とも有限（AN-02: NaN 分岐は消滅）
if method is InterpolationMethod.LINEAR:
    alpha = (t - ts[lo]) / (ts[hi] - ts[lo])
    return float(vs[lo] + alpha * (vs[hi] - vs[lo]))
if method is InterpolationMethod.ZERO_ORDER_HOLD:
    return float(vs[lo])
if method is InterpolationMethod.NEAREST:
    return float(vs[lo]) if (t - ts[lo]) <= (ts[hi] - t) else float(vs[hi])
raise ValueError(f"unknown InterpolationMethod: {method!r}")
```

- **AN-02**: `finite_view` が NaN サンプルを除くので `vs[lo]/vs[hi]` は常に有限 → `if np.isnan(...)` 分岐が不要になり消滅。散在 NaN でも前後の有限サンプル間で補間される。
- **AN-03**: `n == 1` で ZOH 前方保持。`n == 0`（全非有限 or 空）は None。
- **単一サンプルの ZOH 前方保持と複数サンプルの右端範囲外 None は非対称**（ユーザーの AN-03 回答に忠実）。複数サンプルの右端 None は本増分では**据え置き**。

### 3.4 消費側・GUI（表示改修なし）

`cursor_readout`/`graph_panel_vm` は不変更。`count` の意味変更（範囲内総数→有限数）は表示フォーマットに影響しない（`count==0`→NO_DATA は「有限データなし」を正しく表す）。

## 4. 検証

- **`finite_view`（Layer A・CI）**: (i) 全値有限 → 戻りが sorted_view と `is` 同一（zero-copy）、(ii) NaN/Inf 混在 → 該当サンプルが除去され値・時刻が対応、(iii) 全非有限 → 空、(iv) 2回目呼び出しがキャッシュ、(v) namespaced ラッパー（`group_signals` 由来）が delegate 共有で元 Signal と同一ビュー。
- **AN-01（Layer A・CI）**: (i) 範囲内に NaN と Inf を混ぜても mean/max/min/std が有限値のみで算出され `count` が有限数、(ii) 範囲内が全て非有限 → `count=0`・全 NaN、(iii) 非有限なし → 従来と同一（回帰）、(iv) **`count` の意味変更で影響する既存テストを更新**（範囲内総数期待 → 有限数期待）。
- **AN-02（Layer A・CI）**: (i) `[v0, NaN, v2]` で v0–v2 間の t が線形補間される（NaN をまたぐ）、(ii) NaN 点の厳密一致時刻でも隣接有限で補間、(iii) ZOH/NEAREST も有限サンプル基準。
- **AN-03（Layer A・CI）**: (i) 単一サンプルで `t == ts[0]` → 値、(ii) `t > ts[0]` → 値（ZOH 前方保持）、(iii) `t < ts[0]` → None、(iv) 0 有限サンプル（全 NaN 信号）→ None。
- **PBT（あれば）**: `test_pbt_statistics`/`test_pbt_interpolation` の性質が有限ビュー化後も保たれるか確認し、非有限を含む生成に対する新しい性質（有限のみ集計）を追加。
- **docs**: catalog（AN-01/02/03 ✅解消）・roadmap（SS-ANALYSIS 完了）・CLAUDE.md。

## 5. エッジケース・留意点

- **Inf の扱い**: `np.isfinite` は NaN・+Inf・-Inf をすべて除外。Inf を「極値として max に残す」ことはしない（mean/std を汚染するため・ユーザー確定）。
- **範囲統計で範囲内が全て非有限**: 空範囲と同じ `count=0` 経路（GUI は NO_DATA 表示）。「範囲に生サンプルはあるが全て無効」と「範囲にサンプルなし」は count=0 で同一表現になる（本増分では区別しない・区別が要れば将来 follow-up）。
- **ホットパス性能**: `finite_view` は zero-copy fast path（全有限時は isfinite スキャン1回のみ）＋キャッシュ＋delegate で、カーソルドラッグ中の毎フレーム・多信号呼び出しでも元 Signal で1回しか非有限スキャンしない。
- **描画は不変更**: プロットは `sorted_view()`/downsampler 経由で NaN ギャップを従来どおり表示。読み取り/統計だけ有限基準（RN クラスタと責務分離）。
- **formula engine・複数サンプルの右端範囲外**: 不変更。

## 6. 非ゴール

描画側の NaN 表示変更（RN クラスタ）／複数サンプル信号の ZOH 前方保持（右端範囲外の据え置き）／「範囲内全非有限」と「範囲内サンプルなし」の区別／formula engine の非有限方針／Inf を極値として保持する選択肢。

## 7. トレーサビリティ

catalog: **AN-01/02/03 を ✅解消**（SS-ANALYSIS 完結）。LD-06（第1弾）が委譲した「統計側の非有限防御」を AN-01 で回収。実装プラン: `docs/superpowers/plans/2026-07-05-analysis-correctness.md`（writing-plans で作成）。
