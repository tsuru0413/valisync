# rendering-correctness-perf 増分2: ダウンサンプラのベクトル化 ＋ X-sync 冗長ガード 設計

**日付**: 2026-07-10
**サブスペック**: `rendering-correctness-perf`（②改善サブスペック）
**対象課題**: RN-04（X 同期の全パネル扇状展開＋UI スレッド同期 LOD 再計算）
**一次情報源**: [docs/audit-findings-catalog.md](../../audit-findings-catalog.md) の RN-04

## 位置づけ

`rendering-correctness-perf` 残り RN-03/04/05 を **2 増分**に分割したうちの**増分2**（最終増分）。増分1（RN-03 幅ガード＋RN-05 Y軸パディング）は PR #72 でマージ済み。RN-01/02（描画正しさ）・RN-06（カーソル perf）も解消済み。本増分完了で `rendering-correctness-perf` は完結する。

## 計測に基づく方針転換（重要）

RN-04 は当初「X 同期の扇状展開アーキテクチャ」の問題と見て、コアレス/オフスレッド/可視のみの3案を検討した。しかし**本番想定ベンチマーク**で以下が判明し、方針を根本原因の直接修正へ転換した（ユーザー承認済み）:

**① 扇状展開フリーズは深刻**（x-sync ON で1ズーム/パンあたり）:

| 構成 | per-panel render | 扇状展開フリーズ（全範囲ズーム） |
|---|---|---|
| 4パネル×2信号×100k点 | 76ms | 311ms |
| 8パネル×3信号×500k点 | 153ms | 1206ms |
| 8パネル×4信号×1M点 | 301ms | 2352ms |

**② 真の根本原因は扇状展開でなくダウンサンプラ**: `src/valisync/core/downsampler/downsampler.py` の min-max LOD が、バケットごとの **Python ループ**（~1600 回）で `np.nanargmin`/`np.nanargmax`（内部で `_replace_nan` コピー＋`any` 走査）を呼ぶ。downsample が起動すると窓内の点数に関係なくこの固定オーバーヘッドが乗る（cProfile で特定）。

**③ ベクトル化を実証**（プロトタイプ・出力インデックス完全一致＝finite/5%NaN/20%NaN/全NaN バケット/50k/500k/1M で全一致）:

| ケース | 現行ループ | ベクトル化 | 倍率 |
|---|---|---|---|
| 狭窓ズームイン（10k点・1600バケット）＝対話の主用途 | 45.9ms | 0.87ms | **~53×** |
| 全範囲ズームアウト（1M点）＝O(m) データ律速 | 62ms | 39ms | ~1.6× |

→ 8パネル×3信号の狭窓扇状展開: 933ms → 約20ms（1秒フリーズが1フレーム未満へ）。

## 目標

RN-04 の X-sync フリーズを、対話の主用途（ズームイン）で解消する。手段は「扇状展開の並列化」でなく、その内側で回るダウンサンプラの**ベクトル化**（全 render が速くなる・single-panel 描画も含む）＋冗長 render の除去。

- 描画結果は**ピクセル不変**（同一サンプルを選択）＝挙動保存の純粋な perf 修正。
- threading なし・低リスク。

## 非目標

- **オフスレッド並列（当初案 B）**: 極端な「全範囲ズームアウト×大信号×多パネル」の残存フリーズ（~1.5s）向けだが、53× 改善後は YAGNI。必要と実測されたら別 follow-up 増分。
- LOD アルゴリズムの意味変更（min-max デシメーションのセマンティクスは不変）・マルチ解像度ピラミッド（mipmap）等の大改修。
- pyqtgraph `setData`（UI スレッド据え置き・本増分の対象外）。

## アーキテクチャ

2つの独立修正。

### 修正1: ダウンサンプラのベクトル化（core）

`Downsampler.downsample`（`src/valisync/core/downsampler/downsampler.py`）の**バケットごと Python ループ**（現行 L67-76）を、セグメント単位の argmin/argmax を求める**ベクトル演算**へ置換する。バケット割当・セグメント境界算出（L52-65）と pass-through（L36-50）・バリデーション（L29-32）は不変。

実証済みアルゴリズム（プロトタイプで現行ループと出力インデックス完全一致）:

```python
# 既存: n_buckets, seg_starts, seg_ends は現行どおり算出済み（L52-65）
n_seg = len(seg_starts)
m = len(vs)

# NaN を極値へ退避（min には +inf、max には -inf を割当て決して勝たせない）
finite = np.isfinite(vs)
v_min = np.where(finite, vs, np.inf)
v_max = np.where(finite, vs, -np.inf)

# 各要素 -> 所属セグメント id（seg 長で arange を反復）
seg_id = np.repeat(np.arange(n_seg), seg_ends - seg_starts)
idx = np.arange(m)

# セグメントごとの min/max 値（reduceat で一括）
seg_min = np.minimum.reduceat(v_min, seg_starts)
seg_max = np.maximum.reduceat(v_max, seg_starts)

# 各セグメントで min/max を達成する「最初の」インデックス
#   （現行 np.nanargmin/nanargmax の first-occurrence と一致）
min_hit = np.where(v_min == seg_min[seg_id], idx, m)
max_hit = np.where(v_max == seg_max[seg_id], idx, m)
argmin_seg = np.minimum.reduceat(min_hit, seg_starts)
argmax_seg = np.minimum.reduceat(max_hit, seg_starts)

sorted_idx = np.unique(np.concatenate([argmin_seg, argmax_seg]))
```

以降の `Signal(timestamps=ts[sorted_idx], values=vs[sorted_idx], ...)` 構築は不変。

**契約の保存**（既存 Req）:
- Req 14.2（各バケットの min/max 保持）: セグメントごとに argmin/argmax の2点を選ぶ（現行同一）。
- Req 14.3/14.6（出力タイムスタンプは入力の部分集合）: `sorted_idx` は入力インデックスなので保証。
- first-occurrence の tie-break: `min_hit`/`max_hit` が「hit した最小インデックス」を取るため `np.nanargmin`/`nanargmax`（先頭優先）と一致。
- 全 NaN バケット: `v_min` 全 +inf → `seg_min` +inf → 全要素が hit → 最初のインデックス（= セグメント先頭 lo）を選ぶ。`v_max` も同様に lo。`unique` で1点に集約＝現行の「keep one sample (lo)」と一致。
- pass-through（`len(ts) <= n`・単調は同一オブジェクト／非単調は整列ビュー再構築）: L36-50 不変。

**数値的安全性**: `seg_min`/`seg_max` は reduceat による**実要素の縮約**なので、対応する min/max 要素と**厳密に float 一致**する（近似計算でない）。`==` 比較は安全。`reduceat` の隣接同一インデックス問題は、`seg_starts` が狭義増加（各々別バケット境界）のため発生しない。

### 修正2: `set_x_range` 不変ガード（VM）

`GraphPanelVM.set_x_range`（`src/valisync/gui/viewmodels/graph_panel_vm.py`）先頭に、レンジが変わらないときの early-return を追加（増分1 RN-03 の `set_panel_width` ガードと同型）:

```python
    def set_x_range(self, lo: float, hi: float) -> None:
        if self.x_range == (lo, hi):
            return
        self.x_range = (lo, hi)
        self._x_range_is_auto = False
        self._invalidate_cache()
        self._notify("range")
```

- **効果**: X-sync の扇状展開では、source パネル自身が `propagate_x_range` により同値で再セットされ**二重描画**していた。ガードでこの2回目を no-op 化。また既に同じレンジのパネル（同期済み）への配送も no-op 化。
- `_x_range_is_auto` の副作用（手動ズーム由来フラグ）も、レンジ不変時は状態変化がないので early-return で正しい（同値再セットは意味的に no-op）。

## テスト戦略（②実質性）

すべて Layer A / core ユニットで実質を尽くせる（GUI 入力経路なし・realgui 不要）。

### 修正1: ダウンサンプラ

- **既存の契約テストが全 PASS（最重要ゲート）**: `tests/test_downsampler.py`（Req 14.2/14.3/14.4/14.6/14.7）と `tests/test_pbt_downsampler.py`（property-based）。これらがベクトル化後も緑であることが「挙動保存」の一次証明。**特に PBT はランダム入力で契約を fuzz するため、ベクトル化の隠れたエッジを捕捉する。**
- **新規パリティテスト**: 現行ループと同一の選択インデックス（または選択された (ts, vs) の集合）を、finite / 一部 NaN / 全 NaN バケット / pass-through 境界（`len==n`, `len==n+1`）で assert。参照実装（現行ループを模したヘルパ）と突き合わせ、ベクトル化の first-occurrence・全 NaN・tie を弁別的に固定する。
- **perf は文書化**（CI アサートにしない＝マシン依存フレーク回避）: ベンチスクリプトの測定値（狭窓 53×・全範囲 1.6×）を spec/PR に記録。

### 修正2: `set_x_range` ガード

- **弁別的ガードテスト**（RN-03 と同型）: `_invalidate_cache` を delegating spy で監視し、同一レンジ再セット=no-op（invalidate/notify なし）・別レンジ=従来どおり invalidate＋notify を assert（ガード削除で RED）。`tests/gui/test_graph_panel_vm.py`。

### 回帰

- 既存の render_data / x-sync（`test_graph_area_vm.py` 等）・LOD（`test_lod_render.py`・`test_lod_benchmark.py`）テストが全 PASS。ダウンサンプラは出力不変なので render 結果も不変。

## 影響ファイル

- `src/valisync/core/downsampler/downsampler.py`（L67-76 のループをベクトル演算へ置換）
- `src/valisync/gui/viewmodels/graph_panel_vm.py`（`set_x_range` 先頭ガード）
- テスト: `tests/test_downsampler.py`（新規パリティテスト追記）・`tests/gui/test_graph_panel_vm.py`（ガードテスト追記）

## タスク分割（writing-plans 用の目安）

- **Task 1**: ダウンサンプラのベクトル化（core・パリティテスト先行＋既存 test_downsampler/PBT 全 PASS がゲート）。
- **Task 2**: `set_x_range` 不変ガード（VM・invalidate スパイ弁別・RN-03 同型）。

両タスク独立・各々独立テスト可能。
