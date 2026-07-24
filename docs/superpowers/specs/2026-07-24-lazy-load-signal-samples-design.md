# 遅延ロード（lazy sample load）設計 — メモリ 2GB/ファイルとロード遅延の根治

> **改訂履歴**: 初版に対しアドバーサリアルレビュー（6レンズ×独立検証・Opus）を実施し
> Critical 1・Important 9・Minor 6 を反映（判定 NEEDS-CHANGES → 反映済み）。主な修正は
> ①遅延読みの変換保存（`raw=True` は生カウントで無言破損 → 単一チャンネル `select`）②namespaced
> ラッパーのソース共有（`values=sig.values` は全展開）③長さ検証の非展開化④共有ハンドルの
> スレッド安全⑤offset の遅延ソース共有⑥`SampleReadError` の集中 degrade⑦`get_master` コストの
> 正直化⑧テスト健全性・メモリ目標の現実化。

## 背景と目的

valisync は**ファイルを開いた瞬間に全信号のサンプルを圧縮解除してメモリへ eager 展開**している。実測（実ディスプレイ・本物の GUI プロセス・`prod_demo.mf4` = 1.3GB on-disk / 264k 信号 / 1 ファイル）:

| 項目 | 実測 |
|---|---|
| Qt＋ウィンドウ基盤 | 261 MB |
| ロード中ピーク RSS | 1,369 MB |
| 定常 RSS（1 ファイル） | 1,201 MB |
| ロード実時間 | 13.1s |
| うち values（native dtype） | 541 MB |

ユーザーのファイル（1GB on-disk・float64 主体等で展開後 ~2GB）では **1 ファイルにつき約 2GB**。コンペアモードは各ファイル独立に eager 展開するため約 2 倍。対して asammdf GUI は**遅延ロード**（オープン ~7MB・プロットした信号だけ展開）で 800MB に収まる。

**単一の根本原因**: 全ロードファイルの全信号を eager に圧縮解除・メモリ展開していること。メモリ 2GB/ファイル・ロード 13s・メモリ逼迫由来の全般的な遅さは、すべてこの単一原因から生じる（計測: 同一 VM 処理が 1 ファイル 676ms → 2 ファイル目 2917ms に劣化＝メモリ逼迫）。

**目的**: asammdf と同様、**オープン = メタデータ＋グループ master のみ**、実サンプルの**値**は**プロット/読み取り時にオンデマンド展開**する。

**達成できる現実的な水準（正直な目標・レビュー I9 反映）**: 遅延化が削るのは **values の working set（prod_demo で 541MB・ユーザー実ファイルで ~1.5GB）**。一方 **264k 個の Signal シェル＋メタデータ dict＋LazyMdfValues＋namespaced ラッパー＋SignalTreeModel** のオブジェクト残渣（実測ベースで概算 ~200–500MB/ファイル）と Qt 基盤（~260MB）は残る。したがって現実的な**定常フットプリントは 1 ファイルあたり ~500–700MB**（値をプロットしていない状態）で、**2GB/ファイルからの ~3–4 倍削減**・コンペア 2 ファイルで ~4GB → ~1.2GB。**asammdf の数十MB 級**に到達するには 264k オブジェクト自体の圧縮（コンパクトなチャンネルメタデータモデル）が別途必要で、これは本 spec の非スコープ（将来の増分候補・増分D の GUI モデル圧縮と一部関連）。数値目標は writing-plans で psutil 実測により peak/steady・1 ファイル/2 ファイルの**コミット値**として確定する。

## 探索で確定した実現性（消費者マップ）

1. **asammdf 8.8.22 は MDF4 を memory-mapped で開く** — 素の `MDF()` 構築は working set ~0（実測 0.0MB / 0.038s）。**ただしオープン=メタのみは値ブロックに限る話**で、後述のグループ master 読み（`get_master`）は録画 master だとデータブロックを解凍する（レビュー I7・§設計判断参照）。
2. **レンダーは O(プロット中) で O(loaded) ではない**（確定）— プロットしていない信号は値サンプルに触れない。
3. **全ロード信号の値サンプルを舐める消費者は無い**（確定）— カーソル/統計＝アクティブパネルのプロット中のみ、エクスポート＝ユーザー選択分のみ、プレビュー＝1 信号のみ。
4. メタデータ面で唯一「値」を触るのは `len(sig.timestamps)`（サンプル数）だが、本設計は **timestamps（master）を eager 保持**するため無変更で動く。
5. **オンデマンド値読みの正しいプリミティブ（レビュー C1 反映）**: `mdf.get(..., raw=True)` は**数値変換（factor/offset）を捨て生カウントを返す**ため使用禁止（VehSpd factor 0.01 が 100倍ずれる等・大半の CAN/XCP 信号が無言破損）。`mdf.get(raw=False)` も禁止（`get` に `ignore_value2text_conversions` が無く enum を文字列配列化 → `iufb` フィルタで無言消失）。**正: 現行 eager と同一意味論の単一チャンネル select** — `handle.mdf.select([(name, gi, ci)], raw=False, ignore_value2text_conversions=True, copy_master=False)[0].samples`（既存 `_SELECT_OPTIONS` を再利用）。名前→位置は `mdf.channels_db[name]`（`(gi,ci)` で曖昧化）、master は `mdf.get_master(gi)`、形状プローブは変換非依存ゆえ `raw=True` 可。

## アーキテクチャ

### 中核: 「master eager / values lazy」＋サンプルソース抽象

- `Signal.timestamps`（= グループ master）は**ロード時に読む**。master はグループ単位で共有で、非有限/非単調の**診断（LD-03）**・`is_monotonic`・**時間範囲**がこれに依存する。コストは§設計判断で正直に述べる（録画 master はデータブロック解凍を伴う）。
- `Signal.values` は**サンプルソース**の背後へ:
  - MDF → `LazyMdfValues(handle, name, gi, ci, selector, length)`（初回 `.array()` で上記の単一チャンネル `select` → 必要なら LD-14 展開で該当列抽出 → native dtype 凍結 → キャッシュ）
  - CSV / Derived → `EagerValues(array)`（配列直持ち・従来挙動・copy-if-writeable 保存）
- `sig.values` は初回アクセスで展開＋キャッシュするプロパティ。**値を「読む」消費者コードは無変更**（値を「構築時に渡す」箇所＝namespaced ラッパーは変更対象・レビュー I1）。

### 増分分割（依存順・すべて本 spec 内）

| 増分 | 内容 | 効果 |
|---|---|---|
| **A** | 遅延ロード core（サンプルソース抽象・ローダー master+メタのみ・MDF ハンドル保持＋ロック・values プロパティ化・検証遅延・**teardown の非展開ガード**） | メモリ/ロードの本丸 |
| **B** | ハンドル生存＋teardown 会計再定義（unload で MDF ハンドルを閉じる） | unload の正しさ・ファイルロック解放 |
| **C** | オフセット全体適用の O(loaded) dict 再構築を O(offset信号) 化 | 「オフセットをファイル全体に適用が遅い」を根治 |
| **D** | 264k 行チャンネル一覧の view 仮想化（QSortFilterProxyModel 撤去・遅延ツリー reset） | 「一覧操作が遅い」を根治 |

**A/B の結合（レビュー I3）**: teardown は現行 `sig.values.nbytes` を全信号で読むため、A の values プロパティ化だけを merge すると unload で全展開する回帰になる。よって **teardown の「非展開・is_materialized gate」ガードは増分A に含める**（A 単独で unload しても展開しないことを A の①gate で実証）。ハンドル close 自体と会計の再定義は増分B。

## 増分A — 遅延ロード core

### 新規ユニット

- `core/models/sample_source.py`:
  - `SampleSource` プロトコル: `.array() -> np.ndarray`（初回展開＋キャッシュ・read-only 凍結）／`is_materialized: bool`（テスト用 honest observable・mechanism のみを表す＝RSS プロキシではない）／`length: int`（**展開せず既知**のサンプル数）／`nbytes_if_materialized: int`（未展開なら 0・teardown 会計用）。
  - `EagerValues(array)` — 構築時に**現行 `__post_init__` と同一の凍結セマンティクス**（writeable なら `.copy()` してから `writeable=False`・read-only はそのまま共有＝呼び出し側の可変配列を in-place 凍結しない・レビュー M6）。`length = len(array)`・`is_materialized` 常時 True。
  - `LazyMdfValues(handle, name, gi, ci, selector, length)` — 初回 `.array()` で §探索 #5 の単一チャンネル `select` → `selector` があれば `_flatten` 後に該当リーフ列抽出 → native dtype（`iufb` 以外は load 時にスキップ済で到達しない）→ 凍結 → キャッシュ。`length` は shell 構築時に master 長（= チャンネルサンプル数）を渡す。失敗時は `SampleReadError`。**読み全体を `handle.lock` で直列化**（レビュー I4）。
- `core/loaders/mdf_handle.py`:
  - `MdfHandle` — 開いたままの `MDF` と `threading.Lock` を包む。`SignalGroup` が 1 個保持し、グループ内の全 `LazyMdfValues` が参照共有。`close()` は冪等（多重 close 安全）。**asammdf `MDF.select`/`get` は単一の共有 `self._file` を seek+read するためスレッド非安全** — グループ内の全遅延読みは `handle.lock` で直列化し、close は読み in-flight 中に走らない（同ロックで保護・native mmap アクセス違反回避）。

### ローダー変更（mdf_loader.py）

`mdf.select`（全チャンネルの値ブロック一括読み）を廃止し、グループごとに:

1. **1 レコードプローブ**（既存 `_scan_oversized` の probe を全チャンネルへ拡張・`raw=True` 可）で各チャンネルの形状＝LD-14 展開の列構造（リーフ名 + selector）を確定。値の全読みは発生しない。
2. `master = mdf.get_master(gi)`（float64・グループ共有・**同一性**）。finiteness 検証で LD-03 診断（master_bad → グループ全信号スキップ・従来どおり）、非単調/重複 diff で警告（従来どおり）。すべて master のみ。
3. 各リーフ列に `LazyMdfValues(handle, name, gi, ci, selector, length=len(master))` を持つ Signal シェルを構築（`timestamps=master` を identity 共有）。value_labels / conversion / unit / comment / source（bus_type）は従来どおりロード時にメタデータ抽出。
4. **成功経路のみ `mdf.close()` を省略**し `MdfHandle` に包んで `SignalGroup` へ所有権移譲。**エラー/キャンセル経路（`LoadCancelled` 再送出・broad except の `signal_group=None` return）では所有権移譲が起きないため、明示的に `MdfHandle`/`mdf` を close してから re-raise/return する**（決定的なハンドル/ロック解放・レビュー M3）。

LD-14 展開列の名前規約・重複名 `[idx]` 曖昧化・`name_deduplicated` メタは従来と同一。同一グループの複数チャンネルを一括展開する場面（マルチ選択ドラッグ）は、`get`/単一 select が**グループのデータブロックを毎回解凍**する（レビュー M4）ため、**まとめて単一 `select([...])` でバッチ**する最適化を許容（メモリ効果は不変・対話レイテンシのみ改善・単一/クロスグループは per-channel 経路）。

### Signal 変更（signal.py）

- `@dataclass(frozen=True)` → 同一の公開読み取り専用属性を持つ通常クラス。**確認済み（設計時 grep）**: Signal は dict キー・set・`==`・`dataclasses.replace` に不使用（value-equality/hash 非依存）。ただし**インスタンス不変性（書込保護）は維持する** — `__setattr__` を override して公開属性の変更を拒否し、内部（`*_cache`・`_values_source`）は `object.__setattr__` を使う。`tests/test_pbt_signal.py::test_instance_is_frozen`（現状 `FrozenInstanceError` 期待）は `AttributeError` 期待へ更新（レビュー M5・実装者が驚かぬよう明記）。
- `timestamps` は eager 配列属性のまま。`values` は `self._values_source.array()` を返す**プロパティ**。
- **構築時検証は values を一切展開しない**（レビュー I2）:
  - timestamps finiteness（master・従来どおり）。
  - **長さ不変条件は `len(self.timestamps) == self._values_source.length` で検証**（`len(self.values)` は展開を誘発するため禁止）。
  - values finiteness・凍結/コピーはソースの初回展開時（`finite_view` が既に非有限を除外）。
- `is_monotonic` は**timestamps のみで計算**（レビュー M1）: `len(timestamps) < 2 or bool(np.all(np.diff(timestamps) > 0))`（現行の `sorted_view()[0] is timestamps` 恒等と等価）でブールをキャッシュ。`time_range()` と同じく master のみを読み値展開を誘発しない。
- `sorted_view` / `finite_view` / `range_stat_index` のキャッシュ連鎖はロジック無変更（`self.values` アクセスが展開を誘発）。**「racing harmless」コメントは更新** — 計算は冪等だが I/O は `handle.lock` に依存して初回展開が win-once であることを明記（レビュー I4）。
- **namespaced ラッパー（signal_group_manager.py・変更対象に追加・レビュー I1）**: ラッパーは**元 Signal の `_values_source` を参照共有**する専用構築経路（例 `Signal.with_name(name, base)` または `values_source=` キーワード）で作る。**`values=sig.values` は禁止**（構築引数の評価で全展開する）。master は identity 共有。`_ensure_namespaced`/`signal_map()`/`signals()`/`group_signals()` は O(names)・メタデータのみを保つ。「消費者コード無変更」は**値を読む消費者に限る**（値を構築時に渡す namespaced は変更）。

### apply_offset（synchronizer.py・レビュー I5）

offset 適用は**timestamps だけシフトし values は不変**。新 Signal は**元 Signal の遅延 `_values_source` を参照共有**する（`EagerValues(.array())` にしない）。これにより `TimeSynchronizer` の「純計算・I/O 無し」契約を保ち、`_signal_map`/auto-fit/カーソル経路から `SampleReadError` を排除し、**全体オフセット（scope=group）でも未プロット信号を展開しない**（offset 信号は実際にプロットされた時のみ共有ソース経由で展開）。offset Signal は delegate を付けない（従来ルール）。

### エラー処理（レビュー I6・集中 degrade）

遅延ゆえ**値アクセスが I/O 失敗し得る**（ネットワークドライブ等）。`LazyMdfValues.array()` 失敗時は `SampleReadError` を送出。**初回展開のトリガは render/readout/export に限らない** — `_auto_fit_ranges`（add_signal/add_signal_to_axis・move_entry_to_new_axis・remove_axis・reset_axis_y/reset_y/reset_x）、カーソル step（`step_cursor`→`_reference_timestamps`）、core 計算（formula engine・`session._require_min_samples` の微分/積分）から起こり得る。よって:
- **GUI: Qt スロット横断の集中例外ガード**で `SampleReadError` を捕捉し、診断 1 件（`信号 'X' のサンプル読み取りに失敗しました`）＋当該カーブを空/degrade（エントリポイントに依らず・アプリは落とさない）。
- **core 計算**: `SampleReadError` を既存の派生信号生成エラー UI（`>=2 samples` の `ValueError` と同経路）で surface。
- **消費者マップの区別**: 「materialize トリガ点（広い）」と「全信号 sample-sweep 点（狭い＝実質無し）」を分けて記す。

## 増分B — ハンドル生存＋teardown 会計再定義

- `unload_file` → `remove_group` の後、グループ保持の `MdfHandle.close()`（mmap 解放・ファイルロック解除・`handle.lock` 保護下）。
- **teardown 会計（増分A で非展開ガード・B で再定義）**: `pending_bytes`/`_drain` は **`sig.values` を未展開信号で決して読まない**。常に `timestamps.nbytes`（eager master）＋`values.nbytes`（`is_materialized` の時のみ）＋Signal 上に載る派生キャッシュ（`_sorted_view_cache`〔float64 昇格で native の最大8倍〕・`_finite_view_cache`・`_range_stat_index_cache` のブロック配列）を `getattr` ガードで計上（zero-copy エイリアス/native==float64 no-copy は array id で dedupe）。**float64 昇格キャッシュは Signal 側に載る**ためソースのみ会計では過少 pacing になる点を明記。
- 順序: unload 通知で plotted 信号を prune（既存 `prune_missing_signals`）→ その後ハンドル close。close 後の遅延アクセスは `handle.lock` 下で「閉鎖済み」を検知し `SampleReadError` で degrade。
- 追い出しなし方針（ユーザー決定）ゆえ materialized 配列は unload まで生存（長時間セッションで plotted-ever の materialized 集合が単調増加し得る＝メモリは「ピークを遅らせる」だけになる場面がある）ことを許容。

## 増分C — オフセット全体適用の O(loaded) 解消

`GraphPanelVM._signal_map` の offset overlay（offset 有効時に base map 全体 264k を走査して dict 再構築）を、**base map を参照のまま offset を持つ信号だけ上書き挿入**する O(offset信号) へ再構築。値展開は I5 により offset 信号を実際にプロットした時のみ。dict 全走査（O(loaded) CPU）を解消。

## 増分D — 264k 行チャンネル一覧の view 仮想化

reset freeze の原因は VM 構築（264k で ~675ms のみ）でなく **QTreeView reset（~2750ms）＋QSortFilterProxyModel remap（~1550ms）**（memory `gui_large_model_reset_freeze_is_view_proxy_not_vm_build` 既測）。

- **QSortFilterProxyModel を撤去**（遅延ツリー上の proxy は reset で全親 rowCount を probe → 全子 materialize を強制＝memory `gui_qsortfilterproxy_over_lazy_tree_forces_full_materialization`）。ソート/フィルタを **VM 側**（`ChannelBrowserVM` の memoized prep・model index 直接解決）へ。選択/D&D は源 index 直接に。
- `SignalTreeModel` の遅延性を reset 経路でも保つ。reset コストを top-level（base group ~4264）に限定。
- `setSortingEnabled(True)` の stale 既定インジケータ発火（memory `gui_setsortingenabled_fires_stale_default_indicator`）を `header().setSortIndicator(-1)` 前置で是正。
- 本増分は最も独立性が高く重いため、writing-plans でさらに細分し得る。

## 設計判断（確定事項）

- **メモリ上限方針＝上限なし**（ユーザー決定）: プロットした信号の materialized キャッシュは unload まで保持。追い出し/LRU は実装しない。未プロット信号は値展開されないため、オープン時のメモリ問題は根治される。
- **MDF ハンドルは開いたまま保持**: mmap ゆえ値の WS ~0。多数ファイル同時ロード時の OS ハンドル/アドレス空間コストは許容（unload で確実に閉じる）。
- **既知の制限（ファイルロック・レビュー M2）**: mmap＋ファイルハンドルを保持するため、**64-bit Windows で対象ファイルはセッション中ロックされ、上書き/切詰め/リネーム/移動/削除が全てブロック**される（asammdf GUI 自身も同様のセッション長 mmap）。これは「安全機能」ではなく**アーキの受容トレードオフ**。緩和は増分B の `unload_file` がハンドルを閉じてロック解除する（ユーザーは上書き/アーカイブ前に unload）。copy-to-temp は却下案（ディスク倍増・mmap WS~0 の利点喪失）。将来「ファイルを解放」導線は YAGNI。
- **CSV は eager 維持**・**Derived / 数式信号は lazy 対象外**（再読み元なし・`EagerValues`）。
- **float64 昇格は当面許容**（初回 `sorted_view` で materialized 信号のみ一時倍化・native-dtype 描画高速路は非スコープ）。
- **master eager のコスト（正直化・レビュー I7）**: `get_master(gi)` は**録画（非仮想）master だとデータブロックを解凍**する（CANape XCP/CAN ラスタ・デモは録画 master）。よってオープンは「値の 264k 展開/float64/flatten/Signal 構築（13s の主因）」を省く一方、**各グループのデータブロックを 1 回は解凍/ページイン**する。オープン後の master 常駐は **Σ(virtual_groups の master バイト)**（prod_demo で ~6MB だが高レート kHz ラスタでは数百MB に達し得る）。writing-plans で**新ローダーの `get_master` ループの実測（wall/RSS・prod_demo 録画 master）**を取り「ほぼ即時」を裏取りしてから記す。master 遅延化の発動条件は「病的に巨大」でなく **Σ(master バイト) が常駐目標を超える**具体条件（将来増分・現時点 YAGNI）。

## テスト方針（レビュー I8/I9 反映・実経路駆動）

perf/メモリ変更ゆえ実測ベース。GUI 増分（C/D）は writing-plans 時に `/gui-test-plan` で E2E 受け入れを設計。

- **A・遅延の決定的 honest observable（実消費者経路を駆動）**: 実 mf4 をロード後、**`session.signals()` / `signal_map()` / `group_signals(key)` を呼んでから**全未プロット信号の `SampleSource.is_materialized == False` を assert（namespaced の `values=sig.values` 回帰／プロット前展開を封じる）。`sig.values`/`sorted_view()` アクセスで `True` に遷移＋キャッシュ。**`is_materialized` は mechanism のみを表す観測（RSS プロキシではない）と明記**。
- **ソース同一性（I8）**: グループの namespaced ラッパーで `wrapper._values_source is origin._values_source` を assert。ラッパー経由（`wrapper.values` と `wrapper.sorted_view()` 双方）で**共有ソースが 1 回だけ展開・二重コピー無し**を assert。
- **teardown 非展開（I3）**: 未展開グループを `TeardownService` に enqueue して `_drain` を回し、**どのソースも materialized に遷移しない**を assert（会計は is_materialized ガード）。
- **変換保存（C1）**: 変換付きチャンネルが lazy と現行 eager で**同一のスケール済み値**を返す。enum/value2text チャンネルは**数値の生コード＋value_labels 保持**を返す。
- **スレッド安全（I4）**: 1 ハンドルを共有する信号に対し 2 スレッドから `array()`/`sorted_view()` を叩き、直列化（再入で失敗する monkeypatched `select`）で単一 get シーケンスを assert。
- **同一性/診断**: master が group 内で identity 共有・`is_monotonic` が lazy 展開後も安定（かつ値を展開しない）・LD-03 が master eager でロード時に emit・LD-14 展開列が正値。
- **エラー**: `select` 失敗注入 → `SampleReadError` → 集中 degrade（render・auto-fit・cursor-step・formula の各トリガ）で診断＋非クラッシュ。
- **B**: unload で `MdfHandle` が閉じる（ファイルロック解除）・多重 unload 冪等。
- **C**: overlay 構築が offset 信号のみ触れる（走査件数 assert）。
- **D**: proxy 撤去・VM ソート/フィルタ等価性・reset freeze 低減は**実ディスプレイ（Layer C / ローカル計測）**で。`setSortIndicator(-1)` 前置の stale sort 抑止を TDD。
- **実 RSS（I9・非 CI だが merge 必須成果物）**: 本セッションで確立した psutil peak/steady 法を writing-plans の受け入れに**必須アーティファクト化**し、**1 ファイル/2 ファイル比較の peak/steady コミット値**をプランに記録。
- **回帰**: 既存全テスト通過（サンプルソース抽象が既存 Signal 挙動を完全保存）。
- **①gate realgui**: 実 GUI で実 mf4 をロード → 信号をプロット → オンデマンド展開が e2e で動く＋**プロット後も未プロット信号は未展開**（memory `gui_perf_e2e_repro_must_drive_real_load_path`）。

## 非スコープ（Non-goals）

- CSV の遅延化（eager 維持）。
- materialized キャッシュの追い出し/LRU（上限なし方針）。
- native-dtype 描画高速路（float64 昇格の除去）。
- master 自体の遅延化（現時点 YAGNI・発動条件は§設計判断）。
- **264k Signal シェル/メタデータ dict 自体の圧縮**（数十MB 級への到達に必要だが本 spec 対象外・将来増分候補）。

## グローバル制約

- 既存の品質ゲート（`uv run pytest` / `ruff check` / `ruff format` / `mypy src/`）を全通過。
- **既存の公開挙動を完全保存**（sorted_view/finite_view/range_stat_index/time_range/is_monotonic の返り値・**数値変換適用済みの値**・診断文言・LD-14 展開規約・重複名 `[idx]`・オフセット意味論・インスタンス書込保護）。
- GUI 変更は Layer A/B（CI）必須・Layer C（ローカル `--realgui`）で ①gate。
- src/ 構造変更（新規ファイル）はユーザー承認済み方針に従う。
