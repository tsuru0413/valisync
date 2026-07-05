# 設計 spec: カーソル/軸 UX 増分①（PC-21 readout 追従再配置＋RN-06 カーソル移動 perf）

ユーザーが実機で発見したカーソル系の2課題を解消する。PC-21＝読み取り表（CursorReadout）が他操作後にプロットからずれて崩れる（BUG）。RN-06＝カーソル移動時の範囲統計計算が重くドラッグがカクつく（PERF・リアルタイム更新は維持）。いずれも Layer A/B で検証可能。ポインタ形状系（PC-22/PC-13/PC-14）は**増分②**（別 spec・realgui 要）に分離。

- **作成**: 2026-07-05
- **ステータス**: 設計（brainstorming 承認済み・writing-plans へ）
- **関連**: [audit-findings-catalog](../../audit-findings-catalog.md) PC-21 / RN-06（ユーザー実機発見 2026-07-05）
- **前提コード（Explore 精読・現行行）**:
  - `gui/views/graph_panel_view.py`: readout 生成 `:719`（`self._readout = CursorReadout(self)`）・one-shot 配置 `:1166-1171`（`_readout_placed` ガードで初回のみ `move(8,8)`）・`_reconcile_axes:885`（軸/カラム追加で `_Y_AXIS_FIXED_WIDTH=72px` ガター確保→プロット原点右シフト）・`_sync_overlay_geometry:840`・`_sync_cursor_from_vm:1138`
  - `gui/views/cursor_readout.py`: `_rebuild:236-274`（毎回全 QLabel を `deleteLater()`＋再生成）・入口 `set_global:116`/`set_delta:136`
  - `gui/viewmodels/graph_panel_vm.py`: `cursor_readings:747-774`（可視全信号を interpolate）・`delta_readings:822-871`（interpolate×2＋`compute_statistics`）
  - `core/statistics/range_stats.py`: `RangeStatistics.compute`（closed range `t_start≤ts≤t_end`・`finite_view()`・population std ddof=0・空は全 NaN/count 0）
  - `core/models/signal.py`: `sorted_view()`/`finite_view()`（frozen dataclass に `object.__setattr__` で遅延キャッシュ・delegate 転送）

---

## 1. スコープと確定判断（brainstorming・ユーザー決定）

| 項目 | 決定 |
|---|---|
| 分割 | **2増分**。本① = PC-21＋RN-06（Layer A/B）。②（別 spec） = PC-22/PC-13/PC-14 ポインタ形状（カスタム QCursor・拡張可能・realgui）。 |
| PC-21 | **プロット矩形に追従再配置**。幾何変化時に readout をプロットビューポート左上＋マージンへ移動。**ユーザーがドラッグ移動したら自動再配置停止**（既存ドラッグ機能を尊重）。 |
| RN-06 | **スレッド/間引き不採用**。計測（下記 §2）で「Global＝実質タダ／Delta 範囲統計だけが計算量ボトルネック」と判明したため、**範囲統計を O(√n) 化（core）＋readout 差分更新（view）**で遅延ゼロの真のリアルタイムを維持。 |
| 分散の数値安定性 | 素朴な `Σv²−(Σv)²/n`（カタストロフィックキャンセル）を避け、**並列分散マージ（Chan/Welford・count/mean/M2）** を採用。np.std 二段パスと機械精度で一致。 |

## 2. 計測（判断根拠・2026-07-05 実測）

代表規模でカーソル1移動あたりの計算コスト（1パネル分・fan-out で×パネル数）:

| 規模 | Global（interpolate のみ） | Delta（interpolate×2＋範囲統計） |
|---|---|---|
| 10 sig × 100k | 0.10 ms | 4.25 ms |
| 10 sig × 1M | 0.05 ms | 95.9 ms |
| 20 sig × 500k | 0.09 ms | 86.8 ms |
| 20 sig × 1M | 0.10 ms | **191.1 ms** |
| 50 sig × 500k | 0.26 ms | **255.3 ms** |

- **Global（線の値＝interpolate）は O(log n) 二分探索で実質タダ** → coalesce すら不要。
- **重いのは Delta の範囲統計だけ**（範囲内サンプル数×信号数に比例）。これが RN-06 の唯一の原因。「頻度」でなく「計算量」の問題なので**アルゴリズムで速くする**。

## 3. PC-21 設計 — readout をプロット矩形に追従再配置

**現状**: readout は plot_widget と兄弟の**レイアウト非管理オーバーレイ**。`_readout_placed` ガードで初回表示時のみ `move(8,8)`。軸/カラム追加（`_reconcile_axes` の 72px ガター）・パネルリサイズでプロット原点が動いても追従しない。

**修正**:
- `_reposition_readout()` を新設。プロットのビューポート矩形（`GraphPanelView` 座標系）の左上 ＋ 小マージン（例 8px）へ readout を `move`。プロット矩形は既存の plot_widget/ViewBox geometry を `GraphPanelView` 座標へマップして得る。
- 呼び出しフック: `_reconcile_axes`（軸/カラム変化）・`resizeEvent`（リサイズ）・`_sync_overlay_geometry`（既存の幾何同期）。
- `_readout_user_moved: bool` を追加。readout のドラッグ移動ハンドラで `True` に。`_reposition_readout()` は `_readout_user_moved` が False のときだけ再配置（ユーザー配置を尊重）。
- カーソル消去・再設置（`_readout_placed` を落とす経路）で `_readout_user_moved` を False にリセット（次の設置で再びプロット追従）。

**非ゴール**: readout をレイアウト管理下に入れる大改修（ドラッグ移動機能を失う）。オーバーレイ方式は維持し、位置追従だけ直す。

## 4. RN-06 設計 — O(√n) 範囲統計（core）＋差分更新（view）

### 4.1 core: 範囲統計の平方分割（`core/statistics/`・純粋・Qt-free）

**データ構造 `RangeStatIndex`（新規）** — 1 信号の `finite_view()`（AN-01 準拠＝非有限を除いた**昇順**の (ts, vs)）から構築:
- ブロックサイズ `B = ceil(sqrt(n))`、ブロック数 `⌈n/B⌉`。
- 各ブロック `b` に **`(count_b, mean_b, M2_b, min_b, max_b)`** を前計算（`M2_b = Σ_{i∈b}(v_i − mean_b)²`）。構築 O(n)・**メモリ O(√n)**（1M サンプルで 5×√n×8B ≈ 40KB/信号）。
- Signal に遅延キャッシュ（`sorted_view`/`finite_view` と同型・`object.__setattr__("_range_stat_index_cache", …)`・delegate 転送）。初回クエリで構築、ドラッグ中の連続クエリで償却。

**範囲クエリ `query(t_start, t_end) -> StatisticsResult`（O(√n)）**:
1. `ts` 昇順より、closed range `t_start ≤ ts ≤ t_end` は連続 index 区間 `[lo, hi)`。`lo = searchsorted(ts, t_start, "left")`, `hi = searchsorted(ts, t_end, "right")`。`count = hi − lo`。
2. `count == 0` → 全 NaN・count 0（現行と同一）。
3. 区間を **左部分ブロック ⊎ 完全ブロック列 ⊎ 右部分ブロック**（互いに素）に分解。
4. 各部分を `(count, mean, M2, min, max)` の統計組にし、**並列マージ演算子 ⊕**（Chan/Welford）で畳み込む:
   - `δ = mean_B − mean_A`, `n = count_A + count_B`
   - `mean = mean_A + δ·count_B/n`
   - `M2 = M2_A + M2_B + δ²·count_A·count_B/n`
   - `min = min(min_A, min_B)`, `max = max(max_A, max_B)`
   部分ブロックは finite_view のスライスから直接 `(count, mean, M2, min, max)` を算出（O(√n) 個）。完全ブロックは前計算値を使用。
5. `var = M2/count`（population・ddof=0）、`std = sqrt(max(var, 0.0))`（丸め由来の微小負値をクランプ）。`mean`/`min`/`max` はマージ結果。

**RangeStatistics.compute の切替**: `compute` は `signal.range_stat_index().query(t_start, t_end)` に委譲（現行のバリデーション＝t_start/t_end finite・t_start≤t_end はそのまま前段で維持）。結果は現行と同一契約（`StatisticsResult`）。

### 4.2 数学的正当性（証明）

**記法**: 範囲内の finite サンプル値を `{v_lo, …, v_{hi−1}}`、`k = hi − lo`。母集団平均 `μ = (1/k)Σv_i`、母分散 `σ² = (1/k)Σ(v_i − μ)²`。現行 `RangeStatistics` は `np.mean/np.min/np.max/np.std(ddof=0)`＝これらの定義値。

**命題1（区間の連続性）**: `finite_view()` は `sorted_view()` 由来で **ts が狭義単調増加**（keep-last 済み）。よって述語 `t_start ≤ ts_i ≤ t_end` を満たす `i` は連続区間 `[lo, hi)` を成す。∵ 単調増加列で下限・上限で挟む条件は連続。`searchsorted(left/right)` はこの `lo/hi` を与える。∎

**命題2（互いに素な分解）**: `[lo, hi)` は 左部分 `[lo, e_L)` ⊎ 完全ブロック群 `[e_L, s_R)` ⊎ 右部分 `[s_R, hi)` に一意分解でき、3 者は互いに素で和が全体。∎（区間の分割）

**命題3（加法的集約の正確性）**: `count`・`Σv`・`Σv²` は互いに素な和集合上で加法的。ブロック前計算 `(count_b, mean_b, M2_b)` は `Σv = count_b·mean_b`、`Σv² = M2_b + count_b·mean_b²` を保持するに等しい（分散の定義展開）。∎

**命題4（並列マージの正当性・Chan et al. 1979）**: 互いに素な集合 A・B に対し、上記 ⊕ は結合後の `(count, mean, M2)` を**厳密に**与える。
- `mean` の証明: `mean = (count_A·mean_A + count_B·mean_B)/n = mean_A + (mean_B−mean_A)·count_B/n`（代数変形）。∎
- `M2` の証明: `M2 = Σ_{A∪B}(v−mean)²`。`Σ_A(v−mean)² = M2_A + count_A(mean_A−mean)²` 等を用い、`mean_A−mean = −δ·count_B/n`、`mean_B−mean = δ·count_A/n` を代入すると `M2 = M2_A + M2_B + δ²·count_A·count_B/n`。∎
- ⊕ は**結合的**（Chan の定理）ゆえ 3 部分（左・完全群・右）を任意順で畳み込んでも同一結果。完全ブロック群は前計算 `(count_b, mean_b, M2_b)` を順次 ⊕ するのと等価。∎

**命題5（min/max）**: `min/max` は和集合上で `min/max(min/max_A, min/max_B)`（結合的・冪等）。ブロック前計算 `min_b/max_b` と部分スライスの min/max のマージで厳密。∎

**命題6（導出統計の一致）**: 命題3–5 より、クエリの `(count, mean, M2, min, max)` は現行 `np` 直接計算と**数学的に恒等**。`var = M2/count = σ²`、`std = √σ²`。∎

**数値的性質**: 並列マージ（Chan/Welford）は **二段パス（平均を引いてから二乗和）と数学的に等価かつ数値的に安定** — 素朴な `Σv²/k − μ²` に生じるカタストロフィックキャンセル（`μ²` が `Σv²/k` に近い＝大平均・小分散）を回避する。したがって `np.std(ddof=0)`（内部で安定二段パス相当）と**機械精度（相対 ~1e-12）で一致**。`std` の微小負値は理論上生じないが、丸めの保険で `max(var, 0.0)` をクランプ。

**検証（証明の実コード化）**: property-based（hypothesis）で、ランダム信号（規模・値域・NaN/Inf 混在を可変）× ランダム範囲 `[t_start, t_end]` に対し、`RangeStatIndex.query` の各フィールドが現行 `RangeStatistics`（愚直 `np`）と一致（`mean/std/M2` は `math.isclose(rel_tol=1e-9, abs_tol=1e-12)`、`min/max` は完全一致、`count` は完全一致）。エッジ: 空範囲・単一サンプル・全非有限・定数信号（σ²=0）・大平均小分散（例 1e8 ± 1e-3）・範囲がブロック境界に一致/跨ぐ。

### 4.3 view: readout の差分更新（`cursor_readout.py`）

**現状**: `_rebuild` が毎移動で全 QLabel を `deleteLater()`＋再生成 → Qt ウィジェット churn。

**修正**: 行構成（信号の顔ぶれ・行数）が前回と不変なら、既存 QLabel を **`setText` で差分更新**（値・スワッチ）。行が増減/変化したときだけ従来の `_rebuild`。判定は前回描画した行キー列（信号名 or キーの並び）を保持して比較。

**効果**: 命題群による O(√n) 統計（<1ms）＋差分更新（Qt churn 除去）で、20 信号×4 パネルでも 1 移動 <2ms → 遅延ゼロの 60fps ライブ。coalesce/threads は不要（要望「更新を維持」を最大限満たす）。

## 5. データフロー（不変）
カーソルドラッグ → `sigPositionChanged` → `_on_cursor_line_dragged` → `vm.set_cursor` → notify → `_sync_cursor_from_vm` → `set_global`/`set_delta`（`delta_readings` が `compute_statistics`＝**O(√n)** に）→ readout **差分更新**。fan-out（propagate_cursor）は各パネルで安価に。

## 6. エラー処理・エッジ
- `compute` のバリデーション（t 非有限・t_start>t_end）は現行どおり前段で維持。
- 空範囲・全非有限 → 全 NaN・count 0（現行と同一契約）。
- 定数信号 → σ²=0（クランプで √0=0）。
- readout 差分更新: 行キー不一致は必ず `_rebuild` にフォールバック（安全側）。
- PC-21: プロット矩形が未確定（初回描画前）なら従来の `(8,8)` フォールバック。

## 7. テスト戦略（GUI テストレイヤー準拠）
- **core O(√n) 統計**（Layer 不問・純粋）: §4.2 の property-based 一致検証＋エッジ列挙。`sorted_view`/`finite_view` キャッシュ同型のインデックスキャッシュが再利用される（`is` 比較）。
- **PC-21**（Layer B・qtbot）: 軸/カラム追加・リサイズ後に readout がプロット矩形左上へ追従／ユーザードラッグ後は固定／カーソル再設置で追従復帰。
- **RN-06 差分更新**（Layer B・qtbot）: 行不変で QLabel が再利用（`is`）・行増減で再生成。
- **無回帰**: 既存 `test_statistics`・`test_graph_panel_*`・`test_cursor_readout*` が全緑。

## 8. ファイル構成
- **新規**: `core/statistics/range_stat_index.py`（`RangeStatIndex`＋並列マージ）、`tests/test_range_stat_index.py`（property-based 一致・エッジ）。
- **変更**: `core/statistics/range_stats.py`（`compute` を index 委譲）、`core/models/signal.py`（`range_stat_index()` 遅延キャッシュ＋delegate 転送）、`gui/views/graph_panel_view.py`（`_reposition_readout`＋`_readout_user_moved`＋フック）、`gui/views/cursor_readout.py`（差分更新）。
- **テスト追加**: `tests/gui/test_graph_panel_view.py`（PC-21 追従）・`tests/gui/test_cursor_readout*.py`（差分更新）。

## 9. 非ゴール
増分②（PC-22 カーソル線ホバー形状・PC-13 Y 軸アクティブゲート・PC-14 X ズーム/パン カスタム QCursor）／coalesce/throttle／ワーカースレッド／readout のレイアウト再設計／fan-out（X 同期）の再設計。

## 10. トレーサビリティ
catalog: **PC-21 / RN-06 を解消**（増分①）。増分②は別 spec（`2026-07-…-cursor-axis-pointer-shapes-design.md`）で PC-22/PC-13/PC-14。実装プラン: `docs/superpowers/plans/2026-07-05-cursor-readout-perf.md`（writing-plans）。
