# FU-20（メモリ最適化＝native dtype 保持で float64 膨張を解消）設計 spec

Tier 2 のアーキ土台。prod（330k 展開）読込で値配列が ~10.8GB を占め 10.9GB 機で OOM。調査スパイクで真因を実測確定し、方式を決定した。

## 真因（実測確定・2026-07-13・調査スパイク）

`prod_demo.mf4`（1.36GB）を全 materialize せず（~10.8GB＝OOM）メタデータ＋1レコードプローブで実測:

| 項目 | 数値 |
|---|---|
| 生チャンネル → LD-14 展開後信号 | 4,324 → **330,004**（76.3×） |
| 展開主因 | 260ch×1000列＋60ch×1100列（レーダ/配列 uint8）＋4004ch×1列 |
| 値要素 総計 | 13.5億 |
| **現状 float64 値 RAM** | **10.82 GB** |
| **native 保持の真の footprint** | **1.36 GB（= 8.0× 削減）** |
| native dtype 内訳 | **uint8 が 13.51億（99.9%）**・float64 は 100万（0.1%） |

**~10.8GB の正体は、`mdf.select` が返す native uint8 配列（~1.36GB）を `mdf_loader.py:470` の `col.astype(np.float64)` が 8× に膨張させた自己招来**である。データの 99.9% は uint8。当初の「遅延ロード（A）が根本解・dtype 圧縮（C）は緩和」という見立ては実測で覆り、**native dtype を保持すれば float64 膨張が消え ~10.8GB→~1.36GB で 10.9GB 機に余裕で収まる**。展開係数の列挙は全 4324ch で 2.25s・+21MB と安価。

## 方式: native dtype 保持＋単一境界 float64 upcast（Approach C）

`Signal.values` を **native dtype で保持**し、float64 化は**唯一の計算境界 `Signal.sorted_view()`** で行う。全計算・描画・export・formula・downsample・統計・補間の各経路は**すべて `sorted_view()`／`finite_view()` を経由**する（消費者監査で確定・下記）ため、この一点で下流の float64 契約を維持できる。**プロット/解析した信号だけ**が float64 コストを払う（遅延・キャッシュ・プロット数で bounded）。

### 消費者監査（生 `.values` を直接計算する経路は存在しない）

- **render**（`graph_panel_vm.py:820` `sig.sorted_view()`）→ **downsample**（`downsampler.py:81` `signal.sorted_view()`・出力は min/max サブセット）→ float64 経由 ✓
- **CSV export**（`csv_exporter.py:86/108` `s.sorted_view()`・`_fmt` は `float(value)` スカラー）✓
- **formula/derived**（`engine.py:322/329/354` `sorted_view()`＋`np.interp`）✓
- **補間**（`interpolator.py` `finite_view()`＋スカラー `float(vs[idx])`）✓
- **範囲統計**（`range_stat_index` は `finite_view()`）✓
- 生 `.values` 直接アクセスは **length チェック・pass-through 構築（`signal_group_manager`/`synchronizer`）・`teardown_service` の nbytes** のみ＝いずれも dtype 非依存で native で正常（nbytes は native で正確化）。

### 変更点

1. **`src/valisync/core/loaders/mdf_loader.py`（`_load_group` 内 `:468-482`）**: `values = col.astype(np.float64, copy=False)` を撤去し、**native 数値 dtype を保持**する。非数値（string/object 等）は `col.dtype.kind not in "iufb"`（int/uint/float/bool）で判定し、従来同様 warning 診断を出してスキップ（現行は astype の ValueError/TypeError で捕捉していた分岐を明示化）。`values.flags.writeable = False` は維持。bool は native のまま保持（compute は sorted_view で float64 化）。
2. **`src/valisync/core/models/signal.py`（`sorted_view()`）**: 返す**値配列を float64 に upcast**する（`astype(np.float64, copy=False)`＝float64 元データは無コピー・native int/float32 は1コピー）。fast path（単調）と sort path の両方。**timestamps は不変**（既に float64）。`is_monotonic` は `sorted_view()[0] is self.timestamps`＝timestamps 同一性判定なので**不変**（値の upcast の影響を受けない）。
3. **`Signal` の契約/docstring 更新**: `values` は「native 数値 dtype（記録どおり）」、`sorted_view()`/`finite_view()` は「float64 を返す（計算/描画の正準型）」と明記。
4. **CSV loader は不変**（`csv_loader.py` の float64 はテキスト由来の float・ファイル小・スコープ外）。

### 保たれる不変条件（負の契約）

- **下流の float64 契約は維持**（全計算が sorted_view/finite_view 経由で float64 を受け取る）。
- **NaN 欠測セマンティクス維持**: int→float64 に NaN は生じず `finite_view` の全 True fast-path で整合。float native チャンネルの NaN は従来どおり `finite_view` で除外。
- **`is_monotonic` 不変**（timestamps 同一性判定）。
- **VM・GUI・downsampler/interpolator/statistics のロジックは不変**（sorted_view の返り値型が拡張されるだけで、既に float64 を期待している）。
- **timestamps は float64 維持**（精度必須・グループ共有で blowup 主因でない）。

## 精度: native→float64 化は実データで厳密

float64 は仮数部 53bit ＝ **2^53（≈9.0×10^15）までの整数を厳密表現**、float32 は float64 の部分集合。

| native | float64 化 | 差 |
|---|---|---|
| uint8/int8, uint16/int16, uint32/int32 | 厳密 | なし |
| float32, float64 | 厳密/恒等 | なし |
| **int64/uint64（|値|>2^53）** | 丸め | あり得る（下記） |

実測 dtype は uint8＋float64 のみ＝**差ゼロ**。唯一の例外 int64/uint64 で 2^53 超は float64 で丸められるが、**これは現行コードと同一挙動**（現行も `astype(float64)` をロード時に実行済み＝新規精度損失は無い）。むしろ native 保持で **storage は今より忠実**（正確な int64 が `Signal.values` に残り、丸めは sorted_view 経由の計算時のみ＝現行と同じ）。ADAS 物理信号値が int64 で 9×10^15 超になることは事実上なく、厳密 export が要件化したら full-native（export を native 読み）で後日救済可能。本 spec では **int64>2^53 の特別扱いはしない**（現行と同一挙動を維持・native storage が自動で現行以上の忠実性を与える）。

## スコープ

**MDF のみ**（pain は MDF 展開・CSV は安価な random access が無くファイル小）。遅延ロード（Approach A）は**不採用**（C で OOM は解消・A の `Signal` コア再設計は不要＝YAGNI）。

## テスト（gui-test-plan ②）

- **Layer A（core・ヘッドレス）**:
  - loader が **native dtype を保持**（wide uint8 チャンネルをロード → `signal.values.dtype == uint8`）。sabotage（astype 復活）で RED。
  - `sorted_view()`/`finite_view()` が **float64 を返す**（native uint8 信号 → view の dtype == float64・値は等価）。
  - **PBT で native→float64 厳密性 lock**: uint8/int16/int32/float32 の任意配列で `sorted_view` の値が元と数値等価（`astype(float64)` が値を変えない）。
  - **オーバーフロー安全性**: 大きな uint8 値を多数持つ信号の範囲統計（sum/mean）が uint8 では溢れる値でも float64 経由で正しい（native 直計算なら誤る値で discriminating）。
  - 非数値チャンネルのスキップ＋warning 診断（現行踏襲）。
  - 既存 loader/downsampler/interpolator/statistics テストの無回帰（値等価は dtype 非依存で通るはず・dtype アサーションがあれば native/float64 の期待へ更新）。
- **E2E メモリ実測（本命 observable・prod スケール必須）**:
  - **CI 可能**: 合成の wide-uint8 mdf（`mdf4_helpers` で 2D uint8 チャンネルを作る）を**実ロード経路**でロードし、`Σ signal.values.nbytes` が native 比例（float64 の 1/8）であることを実測。sabotage で 8× に膨れて RED。
  - **ローカル手動（realgui 同様のゲート）**: 実 `prod_demo.mf4`（330k）を実ロードし、プロセス RSS が現行 ~10.8GB 相当から **~1.36GB 相当へ低下**することを Win32 実測（本 spec の数値の実機再現）。CI では重すぎるためローカル限定・証拠添付。
- prod スケール必須（メモリ効果はデータ規模依存＝小データでは 8× 膨張が見えない）。

## ファイル構成（変更予定）

- `src/valisync/core/loaders/mdf_loader.py`: `_load_group` の float64 astype 撤去＋非数値スキップ判定。
- `src/valisync/core/models/signal.py`: `sorted_view()` の値 float64 upcast＋契約/docstring 更新。
- テスト: `tests/test_loaders.py`（native dtype 保持・非数値スキップ）・`tests/test_signal_sorted_view.py`（sorted_view/finite_view の float64 返却・オーバーフロー安全性）・`tests/test_pbt_signal.py`（native→float64 厳密性 PBT）・`tests/test_pbt_mdf4.py`（無回帰）・メモリ実測テスト（新規・合成 wide-uint8）。`tests/test_demo_mf4.py:113/425` の dtype アサーションはデモ生成器（asammdf レベル samples）の検証で `Signal.values` とは無関係＝無影響。
- **不変**: VM・GUI・downsampler/interpolator/statistics/csv_exporter/formula のロジック・timestamps float64・CSV loader。
