# 遅延ロード（lazy sample load）設計 — メモリ 2GB/ファイルとロード遅延の根治

## 背景と目的

valisync は**ファイルを開いた瞬間に全信号のサンプルを圧縮解除してメモリへ eager 展開**している。実測（実ディスプレイ・本物の GUI プロセス・`prod_demo.mf4` = 1.3GB on-disk / 264k 信号 / 1 ファイル）:

| 項目 | 実測 |
|---|---|
| Qt＋ウィンドウ基盤 | 261 MB |
| ロード中ピーク RSS | 1,369 MB |
| 定常 RSS（1 ファイル） | 1,201 MB |
| ロード実時間 | 13.1s |

ユーザーのファイル（1GB on-disk・float64 主体等で展開後 ~2GB）では **1 ファイルにつき約 2GB**。コンペアモードは各ファイル独立に eager 展開するため約 2 倍。対して asammdf GUI は**遅延ロード**（オープン ~7MB・プロットした信号だけ展開）で 800MB に収まる。

**単一の根本原因**: 全ロードファイルの全信号を eager に圧縮解除・メモリ展開していること。メモリ 2GB/ファイル・ロード 13s・メモリ逼迫由来の全般的な遅さは、すべてこの単一原因から生じる（計測: 同一 VM 処理が 1 ファイル 676ms → 2 ファイル目 2917ms に劣化＝メモリ逼迫）。

**目的**: asammdf と同様、**オープン = メタデータのみ**、実サンプルは**プロット/読み取り時にオンデマンド展開**する。これでメモリは数十MB/ファイルに落ち、ロードはほぼ即時、遅さも大幅改善する。

## 探索で確定した実現性（消費者マップ）

1. **asammdf 8.8.22 は MDF4 を memory-mapped で開く** — 開くだけなら working set ~0（1.36GB ファイルで実測 0.0MB / 0.038s）。ハンドルを開いたまま保持するコストはほぼゼロ。
2. **レンダーは O(プロット中) で O(loaded) ではない**（確定）— プロットしていない信号はサンプルに一切触れない。
3. **全ロード信号のサンプルを舐める消費者は無い**（確定）— カーソル/統計＝アクティブパネルのプロット中のみ、エクスポート＝ユーザー選択分のみ、プレビュー＝1 信号のみ。
4. メタデータ面で唯一サンプルを触るのは `len(sig.timestamps)`（サンプル数）だが、本設計は **timestamps（master）を eager 保持**するため、この 3 箇所は無変更で動く。
5. オンデマンド読みは `mdf.get(group=gi, index=ci, samples_only=True, raw=True)`（1 チャンネル 0.6ms）、名前→位置は `mdf.channels_db`、master は `mdf.get_master(gi)`。

一次探索記録は本セッションのワークフロー成果（消費者マップ）に基づく。

## アーキテクチャ

### 中核: 「master eager / values lazy」＋サンプルソース抽象

- `Signal.timestamps`（= グループ master）は**ロード時に読む**。master はグループ単位で共有・数本だけ・極小で、非有限/非単調の**診断（LD-03）**・`is_monotonic` の**同一性**・**時間範囲**がこれに依存するため、eager が正解かつ安価（`prod_demo` で master 合計 ~0MB、値 541MB）。
- `Signal.values` は**サンプルソース**の背後へ:
  - MDF → `LazyMdfValues(handle, gi, ci, selector)`（初回 `.array()` で `mdf.get(...)` → 必要なら LD-14 展開で該当列抽出 → native dtype 凍結 → キャッシュ）
  - CSV / Derived → `EagerValues(array)`（配列直持ち・従来挙動）
- `sig.values` は初回アクセスで展開＋キャッシュするプロパティ。**消費者コードは無変更**。値の finiteness 検証だけ初回展開へ遅延。

この設計により、探索が挙げた `n_samples` / per-group `t_min/t_max` / master-token といった追加メタデータ機構は**不要**（master が eager ゆえ `len(timestamps)` / `time_range` / `id()` dedup がそのまま動く）。

### 増分分割（依存順・すべて本 spec 内）

| 増分 | 内容 | 効果 |
|---|---|---|
| **A** | 遅延ロード core（サンプルソース抽象・ローダー master+メタのみ・MDF ハンドル保持・values プロパティ化・検証遅延） | メモリ/ロードの本丸 |
| **B** | ハンドル生存＋teardown 再定義（unload で MDF ハンドルを閉じる・「ハンドル解放＋materialized 破棄」へ簡素化） | unload の正しさ・ファイルロック解放 |
| **C** | オフセット全体適用の O(loaded) dict 再構築を O(offset信号) 化 | 「オフセットをファイル全体に適用が遅い」を根治 |
| **D** | 264k 行チャンネル一覧の view 仮想化（QSortFilterProxyModel 撤去・遅延ツリー reset） | 「一覧操作が遅い」を根治 |

A→B→C は core の一連、D は独立性の高い GUI 層（別増分だが同一 spec）。

## 増分A — 遅延ロード core

### 新規ユニット

- `core/models/sample_source.py`:
  - `SampleSource` プロトコル: `.array() -> np.ndarray`（初回展開＋キャッシュ・read-only 凍結）と `is_materialized` プロパティ（テスト用 honest observable）。
  - `EagerValues(array)` — 構築時に配列を凍結保持。`.array()` は常にそれを返す。`is_materialized` は常に True。
  - `LazyMdfValues(handle, gi, ci, selector)` — 初回 `.array()` で `mdf.get(group=gi, index=ci, samples_only=True, raw=True)` → `selector` があれば `_flatten` 後に該当リーフ列抽出 → native dtype（`iufb` 以外は既存同様スキップ済みなので到達しない）→ 凍結 → キャッシュ。失敗時は `SampleReadError` を送出。
- `core/loaders/mdf_handle.py`:
  - `MdfHandle` — 開いたままの `MDF` を包む。`SignalGroup` が 1 個保持し、グループ内の全 `LazyMdfValues` が参照共有。`close()` で `mdf.close()`（増分B で配線）。多重 close は冪等。

### ローダー変更（mdf_loader.py）

`mdf.select`（全チャンネルの値ブロック読み）を廃止し、グループごとに:

1. **1 レコードプローブ**（既存 `_scan_oversized` の probe パスを全チャンネルへ拡張・`_PROBE_OPTIONS` record_count=1）で各チャンネルの形状＝LD-14 展開の列構造（リーフ名 + selector）を確定。値の全読みは発生しない。
2. `master = mdf.get_master(gi)`（float64・グループ共有・**同一性**）。finiteness 検証で LD-03 診断（master_bad → グループ全信号スキップ・従来どおり）、非単調/重複 diff で警告（従来どおり）。すべて master のみ。
3. 各リーフ列に `LazyMdfValues(handle, gi, ci, selector)` を持つ Signal シェルを構築（`timestamps=master` を identity 共有）。value_labels / conversion / unit / comment / source（bus_type）は従来どおりロード時にメタデータ抽出。
4. **`mdf.close()` を finally で呼ばない** — `MdfHandle` に包んで `SignalGroup` へ所有権移譲。

LD-14 展開列の名前規約（`Name[i][j]` / `Name.field`）・重複名 `[idx]` 曖昧化・`name_deduplicated` メタは従来と同一（プローブ形状から列構造を得る点だけが変更）。

### Signal 変更（signal.py）

- `@dataclass(frozen=True)` → 同一の公開読み取り専用属性を持つ通常クラス（`name` / `timestamps` / `values` / `file_format` / `bus_type` / `source_file` / `metadata`）。**確認済み（設計時 grep）**: Signal は dict キー・set・`==` 比較・`dataclasses.replace` に一切使われていない（`_namespaced_map` も `sig.name` 文字列がキー）ため、value-equality/hash 非依存＝通常クラス化は安全。`__post_init__` 相当の timestamps 検証は `__init__` 末尾へ移す。
- `timestamps` は eager 配列属性のまま。`values` は `self._values_source.array()` を返す**プロパティ**。
- 検証: timestamps finiteness は構築時（master・従来どおり）。**values finiteness 検証は初回展開へ遅延**（`finite_view` が既に非有限を除外）。凍結/コピーはソースの初回展開時に実施。
- `sorted_view` / `finite_view` / `range_stat_index` のキャッシュ連鎖は**ロジック無変更**（`self.values` アクセスが展開を誘発するだけ）。
- namespaced ラッパー: **同一の `_values_source` を参照共有**（どちらの初回アクセスでも 1 回だけ展開）＋ master を identity 共有 → `is_monotonic`（`sorted_view()[0] is self.timestamps`）・`_sorted_view_delegate` は不変。
- offset 適用（Synchronizer.apply_offset）で作る新 Signal は `timestamps+delta`（要展開＝offset 信号に限定・bounded）・values は `EagerValues`（元ソースの `.array()` を参照）。delegate は付けない（従来ルール）。

### エラー処理

遅延ゆえ**サンプルアクセスが I/O 失敗し得る**（ネットワークドライブ等）。`LazyMdfValues.array()` 失敗時は `SampleReadError` を送出し、**レンダー / 読み値 / エクスポート境界で捕捉 → 診断 1 件（`信号 'X' のサンプル読み取りに失敗しました`）＋当該カーブは空表示で degrade**（アプリは落とさない）。mmap でファイルを開いたまま保持するため、セッション中のファイル削除は Windows のロックで実質防止される（失敗面は小さいが degrade は必須）。

## 増分B — ハンドル生存＋teardown 再定義

- `unload_file` → `remove_group` の後、グループ保持の `MdfHandle.close()` を呼ぶ（mmap 解放・ファイルロック解除）。
- teardown 再定義: 現行「10GB の numpy を 64MiB/tick で GUI スレッド解放」から「**ハンドルを即閉じ＋materialized キャッシュのぶんだけ pacing 解放**」へ。未展開信号はほぼ解放物が無いため pacing は materialized 部分のみ対象。nbytes 会計は materialized 配列のみ計上。
- 順序: unload 通知で plotted 信号を prune（既存 `prune_missing_signals`）→ その後ハンドル close。close 後の遅延アクセスは `SampleReadError` で degrade。
- 追い出しなし方針（ユーザー決定）ゆえ、materialized 配列は unload まで生存。長時間セッションでは plotted-ever の materialized 集合が単調増加し得る（メモリは「ピークを遅らせる」だけになる場面がある）ことを許容する。

## 増分C — オフセット全体適用の O(loaded) 解消

`GraphPanelVM._signal_map` の offset overlay（offset 有効時に base map 全体 264k を走査して dict 再構築）を、**base map を参照のまま offset を持つ信号だけ上書き挿入**する O(offset信号) へ再構築。サンプル展開は元々 offset 信号に限定されるため不変。dict 全走査（O(loaded) CPU）のみ解消。→ 「オフセットをファイル全体に適用が遅い」を根治。

## 増分D — 264k 行チャンネル一覧の view 仮想化

reset freeze の原因は VM 構築（264k で ~675ms のみ）でなく **QTreeView reset（~2750ms）＋QSortFilterProxyModel remap（~1550ms）**（memory `gui_large_model_reset_freeze_is_view_proxy_not_vm_build` 既測）。

- **QSortFilterProxyModel を撤去**（遅延ツリー上の proxy は reset で全親 rowCount を probe → 全子 materialize を強制＝memory `gui_qsortfilterproxy_over_lazy_tree_forces_full_materialization`）。ソート/フィルタを **VM 側**（`ChannelBrowserVM` の memoized prep・model index 直接解決）へ移す。選択/D&D は源 index 直接に。
- `SignalTreeModel` の遅延性を reset 経路でも保つ（reset で子を全 materialize しない）。reset コストを top-level（base group ~4264）に限定。
- `setSortingEnabled(True)` の stale 既定インジケータ発火（col 0 Descending で本物 sort が走る＝memory `gui_setsortingenabled_fires_stale_default_indicator`）を `header().setSortIndicator(-1)` 前置で是正。
- 本増分は最も独立性が高く重いため、writing-plans でさらに細分し得る。

## 設計判断（確定事項）

- **メモリ上限方針＝上限なし**（ユーザー決定）: プロットした信号の materialized キャッシュは unload まで保持。追い出し/LRU は実装しない（設計簡素化）。未プロット信号は一切展開されないため、オープン時のメモリ問題は根治される。
- **MDF ハンドルは開いたまま保持**: mmap ゆえ WS ~0。多数ファイル同時ロード時の OS ハンドル/アドレス空間コストは実運用上許容（unload で確実に閉じる）。
- **CSV は eager 維持**: mmap/ランダムアクセスの等価物が無く、CSV は通常小さい。lazy 化しない（YAGNI）。
- **Derived / 数式信号は lazy 対象外**: 再読み元が無いため materialized（`EagerValues`）のまま。
- **float64 昇格は当面許容**: 初回 `sorted_view` で materialized 信号の float64 コピーが一時的に倍化するが、プロット中信号に限定されるため許容（native-dtype 描画高速路は別最適化・非スコープ）。
- **master eager**: timestamps はロード時に読む。診断・同一性・時間範囲・`len(timestamps)` を無変更で保つ。将来 master が病的に巨大なファイルが問題化すれば master 遅延化を別増分で検討（現時点 YAGNI）。

## テスト方針

perf/メモリ変更ゆえ実測ベース。GUI 増分（C/D）は writing-plans 時に `/gui-test-plan` で E2E 受け入れを設計する。

- **A・メモリ（決定的 honest observable）**: 実 mf4 をロードし、**未プロット信号のソースが未展開**（`SampleSource.is_materialized == False`）を CI で assert。`sig.values` / `sorted_view()` アクセスで `is_materialized == True` に遷移＋キャッシュされることを assert。実 RSS 数値はローカル計測スクリプト（本セッションで確立した psutil ピーク/定常法）で別途担保（psutil を CI 依存にしない）。
- **同一性/診断**: master が group 内の全信号で identity 共有（`a.timestamps is b.timestamps`）・`is_monotonic` が lazy 展開後も安定・LD-03 非有限 master がロード時に emit・LD-14 展開列が正しい列値を返す。
- **エラー**: `mdf.get` 失敗注入（monkeypatch）→ `SampleReadError` → render/export 境界で degrade＋診断 1 件。
- **B**: unload で `MdfHandle` が閉じる（`mdf.close` 呼出・ファイルロック解除）を assert。多重 unload 冪等。
- **C**: overlay 構築が offset 信号のみ触れる（走査件数 assert・O(loaded) でない）。
- **D**: proxy 撤去・VM ソート/フィルタの等価性（フィルタ後の行集合・選択の源解決）＋ reset freeze 低減は**実ディスプレイ（Layer C / ローカル計測）**で。`setSortIndicator(-1)` 前置の stale sort 抑止を TDD で。
- **回帰**: 既存全テスト通過（サンプルソース抽象が既存 Signal 挙動を完全保存）。
- **①gate realgui**: 実 GUI で実 mf4 をロード → 信号をプロット → オンデマンド展開が e2e で動く（memory `gui_perf_e2e_repro_must_drive_real_load_path` の教訓＝内部 API でなく実ロード経路）。

## 非スコープ（Non-goals）

- CSV の遅延化（eager 維持）。
- materialized キャッシュの追い出し/LRU（上限なし方針）。
- native-dtype 描画高速路（float64 昇格の除去）。
- master 自体の遅延化（現時点 YAGNI）。

## グローバル制約

- 既存の品質ゲート（`uv run pytest` / `ruff check` / `ruff format` / `mypy src/`）を全通過。
- 既存の公開挙動（sorted_view/finite_view/range_stat_index/time_range/is_monotonic の返り値・診断文言・LD-14 展開規約・重複名 `[idx]`・オフセット意味論）を保存する。
- GUI 変更は Layer A/B（CI）必須・Layer C（ローカル `--realgui`）で ①gate。
- src/ 構造変更（新規ファイル）はユーザー承認済み方針に従う。
