# 配列チャンネルの列展開を遅延化する設計（増分E）

> **位置づけ**: [遅延ロード設計](2026-07-24-lazy-load-signal-samples-design.md)（増分A・完了）の続き。
> A は「値」を遅延化した。本 spec は「**列展開そのもの**」を遅延化し、残る per-列 Python
> オブジェクト残渣を落とす。ユーザー決定により、増分A と**同一ブランチで一緒に出荷**する。
>
> **改訂履歴（v2）**: 初版に敵対的レビュー（6レンズ×独立検証・45 エージェント）を実施し
> **判定 NEEDS-CHANGES**（38 指摘 → 29 確定 / 9 refuted）。**Critical 2・Important 11・Minor 8**
> と**ユーザー決定 4 件**を反映済み。主な反転:
> ①鋳造列のキャッシュ寿命（`_invalidate_namespaced` 相乗り → **per-group 副テーブル**。相乗りは
> 2 ファイル目ロードごとに全プロット列をフル再読み＝**実測 0.73–1.18 s/列・10 列で 7–12 秒**の
> UI ブロックという純粋な回帰だった）②`parse_leaf` の '.' 分割 → **最長一致**（asammdf の
> フィールド名はチャンネル名そのもので '.' を含む・**quick_demo は 173 中 156 がドット付き**）
> ③フィルタ「149 ms は現行より速い」は**1 パス値の誤り**（production は 1 打鍵 3 パス＝約 450 ms）
> → **名前キャッシュ方式**へ ④メモリ目標 ~200 MB は GUI 側 87 MB の**二重計上**で到達不能
> → **~310 MB**（削減 ≈280 MB）⑤位置ベース selector は列読みコストの **9–12% しか直さない**
> → **チャンネル単位デコード済みキャッシュ**をスコープに追加。

## 背景 — なぜまだ重いのか（実測）

増分A で値は完全に shed された（realgui 実証: 1 本プロット後も未プロット 263,999 信号は
`is_materialized == False`）。にもかかわらず `prod_demo.mf4` の実 GUI 定常 RSS は **868 MB**。
残りの支配項は**値ではなくオブジェクト数**である。

`demo_data/prod_demo.mf4` の実測（ヘッドレス core・値は未展開）:

| 段階 | RSS |
|---|---|
| baseline | 87 MB |
| `Session.load` 後（264,004 信号・7.0 s） | 471 MB (+384) |
| `signal_map()` 後 | 532 MB (+61) |
| `group_signals()` 後 | **590 MB** |

内訳（tracemalloc・1 列あたり）: Signal シェル＋`LazyMdfValues`＋metadata dict = **572 B**、
namespaced ラッパー（2 系統キャッシュ）= **201 B**、`ChannelBrowserVM._prep` = **258 B**（計 68 MB）、
`_Node.leaves` = 計 19 MB。

**構造的な原因**: このファイルは**物理 4,324 チャンネル**しか無い。`Prod10_0000` は
shape (12000, 1000) の**1 本のチャンネル**である。LD-14 がロード時にこれを 1,000 本の
Signal へ展開するため、4,324 → **264,004 オブジェクト（61 倍）**になる。

**asammdf GUI の実測比較**（[調査記録](../../.superpowers/sdd/asammdf-gui-open-strategy.md)）:
asammdf はツリーに**物理チャンネル 1 行**しか作らず、`Name[i][j]` への展開は**プロットへ
ドロップした時だけ**行う（`mdi_area.py:1512-1570`）。同じ tree item を 264,009 件作ると
**+289 MB**、4,329 件なら **+4 MB** と実測されており、**残渣のうち ~285 MB はエントリ数
そのものに内在**する。

## 目的と到達目標（実測に基づく再設定）

**ロード時に列を展開しない。** ローダーは物理チャンネル 1 本につき Signal 1 個（＋列仕様）を
作り、`grp::Prod10_0000[7]` のような**列キーは要求時に鋳造**する。

**到達目標（レビュー訂正後）**: core 常駐 **590 MB → ~310 MB（削減 ≈280 MB）**。
初版の「~200 MB」は GUI 側 87 MB を core 側の削減に二重計上していた誤り。**主指標は
private commit / USS**（eager +281 MiB → E-3 +15 MiB）とする。mmap フロア ~205 MiB の削減は
本 spec の非スコープ（別 follow-up）。per-列オブジェクトは **264,004 → 4,324**。
ロード実測 7.0 s も短縮される（264k 個の Signal 構築・metadata dict・診断 fan-out が消える）。

## ユーザー決定（確定）

1. **列の個別選択は維持する**（案B）。asammdf 完全パリティ（案A）は「ブラウザから単一列を
   選ぶ」経路自体が無い（`'Prod10_0000[5]' in mdf` は False）。ADAS の配列チャンネル
   （レーダー物体リスト等）では特定列だけ見る用途が主。
2. **1024 列超の制限を廃止**し、これらのチャンネルを表示する（`prod_demo` で今まで既定
   スキップされ**一覧に出ていなかった 60 本**が使えるようになる）。
3. **チャンネルブラウザは物理チャンネル 1 行へ平坦化する**。現行のツリーは**ドットでも
   分割**しており（`_BASE_RE = re.compile(r"[\[.]")`）、`quick_demo` では物理 173ch が
   ACC/AEB/LKA/Radar/Cam など **24 行**にまとまっている。平坦化により **24 → 173 行**
   （`prod_demo` は 4,324 行）となり「1 行＝1 物理チャンネル」が構造として明確になる。
   モジュール階層のまとまりは失われ、ピン留めされたテスト・凍結カタログの更新を伴う。
4. **件数表示は列数を ch 単位として現行パターンで出す**: 「**330,004 ch 中 1,100 ch を表示**」。
   フィルタのフィードバック（N 中 M）を維持し、単位は「ch」、数えるのは**展開列**。
5. **チャンネル単位のデコード済みサンプルキャッシュを本ブランチに含める**（後述 §列読みコスト）。
6. **配列/構造化チャンネルの列単位 warning は物理チャンネル 1 件へ集約**する
   （1-D チャンネルの診断は**現行と byte-identical を維持**）。

## 本 spec で確定する技術判断

- **フィルタは列名にマッチさせ、名前キャッシュを使う**。レビューで初版の根拠が崩れた:
  「149 ms」は**1 パスの値**で、production は **3 パス**走る（model reset＋header＋
  empty_state）ため実測は約 **450 ms**＝現行 170–213 ms より**遅い**。訂正後の選択:

  | 方式 | 1 適用（3 パス） | 追加メモリ |
  |---|---|---|
  | 物理チャンネル名のみ | ≈1 ms | 0 MB |
  | 列名・都度生成（初版の推奨・**却下**） | **≈450 ms** | 0 MB |
  | **列名・名前キャッシュ（採用）** | **≈130 ms** | **41.7 MB** |
  | （参考）現行実装 | 170–213 ms | — |

  件数が列基準（ユーザー決定 4）である以上、どの列が一致したかを知る必要があり、
  列名マッチが整合する。41.7 MB は削減する ~280 MB の約 15% で、現行より速くなる。
  キャッシュは**遅延生成**（初回フィルタ時 116 ms）し、`_invalidate_namespaced` ではなく
  グループ削除時に破棄する。

  > **2026-07-25 訂正（E-2 実装時・2 点）**
  >
  > 1. **「1 打鍵で 3 パス」は不正確** — フィルタは **200 ms シングルショット debounce**
  >    （`channel_browser_view.py:41`・`:107-110`・`:220-222`）の後に走るので、走るのは
  >    **打鍵ごとではなく入力停止ごと**。3 パス（`SignalTreeModel._on_vm_change` →
  >    `_rebuild` → `tree_groups()` ／ `_refresh_state` → `header_text()` → `shown_count()` ／
  >    同 → `empty_state()` → `shown_count()`）が走るのは**その 1 回**。上表の見出しは
  >    「1 打鍵」ではなく「1 適用」と読むこと。
  > 2. **E-2 は名前キャッシュを採らず 0 MB のフィルタメモを採用** — 3 パスはいずれも同じ
  >    `_prep` を同じフィルタ文字列で歩き、間に結果を変えるものが無い。よってフィルタ
  >    文字列をキーにしたメモ 1 個（`ChannelBrowserVM._filter_memo` = 生存行タプル＋int・
  >    prod 4,324 行＝数十 KB）で **3 パス → 1 パス** に畳める（`_matches` 呼び出し数の
  >    実測で 3.00 → 1.00 を確認）。**名前キャッシュは E-3 の条件付きへ移す** — 適用先は
  >    残る 1 パスの短縮だけになり、実測でメモ案が現行 170–213 ms を上回った場合にのみ
  >    採る。なお 41.7 MB は **330,004 列＝1024 ガード退役後**の値で、E-2 スケール
  >    （264,004 列）では比例で **≈33 MB**。E-3 で採る場合は m3 のライフサイクル要件
  >    （`group_key` ごと・`refresh()` で捨てない・LRU=2）を必ず適用すること。
- **`Mat[0]` 衝突**（2 次元チャンネル `Mat` の第 0 列と、`Mat[0]` という名前の 1 次元チャンネル）は
  **最長一致＝実チャンネル優先**で決定し、ロード時に info 診断を 1 件出す。
- **「N 本に展開」info 診断はロード時に維持**（`_leaf_column_count(probe)` から件数を再取得）。
- **合成した列子ノードのソート順は現状維持**（辞書順）。数値順は別 follow-up。
- **1024 ガードの退役は E-3 へ前倒し**（削除のみ・E-3 の出口数値が 4,324 で揃う）。
  退役は **LD-08 dedup インデックスを動かしうる**（同名チャンネルの永続キー `W[0]`→`W[1]`）ため、
  意図的逸脱として記録しテストで固定する。
- **公開 API の意味縮小**: `Session.signals()` は**物理チャンネルのみ**を返す（列は `resolve`
  経由）。ここで列を返すと 390 MB を自ら再導入するため、縮小は不可避。
  > **2026-07-29 訂正（E-2/増分B 出荷時）**: 当初この項目は
  > `AppViewModel.signals()` / `Session.unified_timeline_signals()` も名指ししていたが、
  > **両者は本ブランチで削除済み**（commit `0847373`「死蔵の信号列挙 API を削除」—
  > `SignalTableModel`/`SignalItem` と併せて撤去）。**E-3 でこの 2 つを縮小しようとしないこと**
  > （存在しない）。残る縮小対象は `Session.signals()`（＋その委譲先
  > `SignalGroupManager.signals()`）だけで、これは既に「物理チャンネルのみ」を返す。
- **`signal_map()` は非対称 Mapping**（**列挙は物理のみ・`[]`/`get`/`in` は列も解決**）として
  出荷する。Mapping 不変条件からの**意図的逸脱**であり、`dict()`/`items()` での全キー列挙は
  330k 列を鋳造して 390 MB を再導入するため禁止する（型注釈とドキュメントで明示）。

## アーキテクチャ

### `ColumnSpec` — 列構造の宣言（**dtype 認識**）

物理チャンネル 1 本につき 1 個。`base_name` / 非サンプル軸の shape / 構造化フィールド木
（**実 dtype のフィールド名をドットを含んだまま保持**）/ `column_count` / `exploded` /
dedup インデックス / `name_deduplicated` / **各リーフの dtype.kind** を保持する。
ロード時の 1 レコードプローブから作る（値は読まない）。

**dtype 認識は必須**（レビュー Important）: 現行の非数値ゲートは**リーフ単位**
（`dtype.kind not in "iufb"` で 1 列ずつ skip＋warning）だが、`_flatten`/`_leaf_column_count` は
dtype 盲目である。`leaf_names` を「列キー空間の単一の真実」に据える以上、dtype 盲目な列挙を
test-lock すると**非数値フィールドが幽霊行になり LD-12 警告が消える**。ColumnSpec は
リーフごとの dtype.kind を持ち、`leaf_names` は**数値リーフのみ**を返す
（チャンネル単位の一括判定は禁止 — 構造化チャンネルはフィールドごとに dtype が異なりうる）。

### `column_names.py` — 命名文法の単一の真実

`leaf_names(base, spec)`（**ジェネレータ・数値リーフのみ**）／`leaf_count(spec)`／
`parse_leaf(display_key, physical_names, spec)`。現行は `_flatten` と `_leaf_column_count` が
同じ規則を**2 箇所で手写し**しており（共有コードも突合 assert も無い）、遅延化はこの乖離
ハザードを広げる。両者をこのモジュールの上に再実装し、**ジェネレータの順序が `_flatten` と
一致すること**をテストで固定する。

**`parse_leaf` は文字列を '.' で split しない**（レビュー Critical 2）。asammdf のフィールド名は
**チャンネル名そのもの**であり '.' を合法に含む（`mdf_v4.py:8066` は配列チャンネル第 0
フィールド名＝親チャンネル名、`:8112/8151` REF_AXIS は参照チャンネルのフルネーム）。
実書き出し→読み戻しで再現済み: チャンネル `Radar.ObjList` → `dtype.names ==
('Radar.ObjList', 'Radar.ObjList.dx')` → リーフ `Radar.ObjList.Radar.ObjList.dx[0]`。
右から剥がすと残余が 3 段に見えるが実フィールドは 1 個であり**解決不能＝列が開けない**。
**`quick_demo` は 173 中 156 チャンネル名がドット付き＝ADAS では既定**である。

逆変換は**既知集合への最長一致**で行う:
(a) 表示キーの最長プレフィクスを**物理表示名集合**（trie）へ最長一致させ base を確定
（最長優先＝`Mat[0]` 衝突時の実チャンネル優先と同規則）、
(b) 残余は base の ColumnSpec が持つ**実 dtype フィールド名集合**（ドットを含んだまま）へ
各段最長一致で消費し、`[i]` トークンのみ機械的に剥がす、
(c) 候補が複数、または残余を消費し切れない場合は**解決失敗**（診断＋degrade）。
**黙って別の列を返してはならない。**

### 解決器（resolver）と遅延解決 Mapping — 設計の要

`SignalGroupManager.resolve(key)` / `Session.resolve_signal(key)` が列 Signal を鋳造する
（共有 master・`LazyMdfValues(handle, base_name, gi, ci, length, selector)`・metadata 継承
〔`name_deduplicated` と `exploded` の value_labels 抑止を含む〕）。

**`signal_map()` は遅延解決 Mapping を返す。** これが本設計の要で、`graph_panel_vm.py` の
約 20 箇所の `sig_map.get(entry.signal_key)`（描画・オートフィット・軸ラベル・カーソル/凡例/
Δ読み値・矢印キー移動）を**無改造**にする。これをやらないと全箇所が「空カーブ・診断なし・
単位空欄・count=0」で**静かに壊れる**。

#### 鋳造した列 Signal のライフサイクル（**Critical 1 の反転**）

鋳造列は**グループキーごとの独立した副テーブル** `_resolved_by_key: dict[str, dict[str, Signal]]`
に保持する。**`_invalidate_namespaced()` のライフサイクルに相乗りさせない** —
`add()` では一切触らず、`remove(key)` のときだけ当該 key のサブテーブルを切り離す
（whole-session の `_namespaced_list`/`_namespaced_map`/`_namespaced_by_key` のみ従来どおり無効化）。

相乗りが不可な理由（実測）: `add()` → `_invalidate_namespaced()` → `Session.load` の "loaded"
→ `GraphAreaVM._on_app_change` → `refresh()` → `_invalidate_cache()` → `render_data()` の
`sig_map.get` → `sorted_view()` → 新インスタンスの `LazyMdfValues.array()`（`_cache=None`）という
鎖が実在し、**2 ファイル目のロードごとにプロット中の全列がフルチャンネル再読み**になる
（`Prod10_0000` (12000,1000) で cold 1.18 s / warm 0.73–0.83 s・**10 列で 7–12 秒の UI ブロック**）。
現行は 0 秒であり**純粋な回帰**、しかも増分E が想定する 2 ファイル比較ワークフローそのもの。
E-4 の位置ベース selector では緩和できない（`mdf.select()` が無条件に全チャンネルを読むため）。

**鋳造した列 Signal は副テーブルが保持する canonical origin** であり、寿命はグループの寿命に
等しい（`signal_map()`/`resolve()` は同一キーに**同一オブジェクト**を返す＝identity 安定）。
したがって origin 自身がキャッシュ保持者であり `_sorted_view_delegate` は不要。delegate は
従来どおり「timestamps/values の配列オブジェクトが元 Signal と同一」の場合のみ付ける規則を
維持し、`apply_offset` 由来の別配列 Signal には絶対に付けない。

`remove(key)` は副テーブルを **pop して呼び出し元へ返す**（`RemovalResult.removed_columns`
新設 → MainWindow が `removed_group` と併せて `TeardownService.enqueue`）。`remove()` の内側で
捨てると会計対象が消えるため不可。enqueue は O(1)（list 参照の受け渡し）。

#### 解決器の 3 値契約（**Important**）

`resolve(key)` は次を区別する:
(a) 解決成功 → Signal、
(b) group_key 未ロード → **正当な不在**（診断なし・Mapping は None）、
(c) group_key はロード済みなのに列キーが解決不能 → **異常**。

(c) では増分A の `_report_read_error` と同型の「1 キー 1 回」診断を `_diagnostic_sink` へ落とす
（`level="error"`・`signal_name`＝表示名・`refresh()` で報告済みマーク解除）。Mapping 自体は
従来どおり None を返し degrade を保つ（約 20 サイト無改造の前提を壊さない）。判定は文字列
解析でなく group_key のロード状態＋ColumnSpec との突合で行う。

これが無いと 9 サイト（unit=""・skip・空 RenderCurve・value=None・DeltaReading None 等）が
**無言で degrade** し、`prune_missing_signals` はグループ所属だけで判定するため
**永久にプロットされ・永久に空で・永久に無診断のカーブ**が残る。

### 列読みコスト（**ユーザー決定 5・スコープ追加**）

現行 `LazyMdfValues.array()` はチャンネル全体を select して再 flatten し 1 列を取る。
同一チャンネルの k 列をプロットすると **k 回のフルチャンネル読み**（実測 **333–386 ms/列**）。
位置ベース selector は flatten 分（**9–12%**）しか削らない — 支配項は `mdf.select()` 自身。

**チャンネル単位のデコード済みサンプル共有キャッシュを導入する**: 同一チャンネルの複数列は
**1 回の select ＋ k スライス**で満たす（実測 **5 列 2,105 ms → 448 ms**）。キャッシュは
デコード済み 2-D 配列 1 本をチャンネル単位で保持し、**寿命は明示設計**する（プロット中の
チャンネルに限定・グループ削除で破棄・teardown 会計に載せる）。位置ベース selector も
併せて採用する（キャッシュ命中時のスライスが名前引きより安いため）。

これは**新たに解禁する 60 本の広幅チャンネルの実用性に直結**する（全て 385 ms/列の重い
グループに属する）。

## 増分分割（各段階で独立に green・危険な反転は最後）

| 増分 | 内容 | 出口 |
|---|---|---|
| **E-0 準備** | 命名文法を `column_names.py` へ抽出（順序突合テスト・**dtype 認識**）／`_signal_map` の offset overlay を O(offset信号) 化（遅延 Mapping の前提・単体で perf 改善）／死蔵コード整理 | 挙動不変・RSS 不変 |
| **E-1 解決器** | `ColumnSpec`＋`resolve()`（**3 値契約**）＋遅延解決 `signal_map()`＋**per-group 副テーブル**（**ローダーはまだ展開する**） | 約 20 の呼出点が無改造で通る・sabotage で鋳造 Signal の等価性と**キャッシュ生存**を証明 |
| **E-2 ブラウザ** | `_ensure_prep` を物理チャンネル単位に／**ツリーを物理チャンネル 1 行へ平坦化**／`SignalTreeModel._materialize` が子を合成／**件数「330,004 ch 中 N ch を表示」**／**列名フィルタ＋名前キャッシュ** | **RSS −約 87 MB**・リビルドコスト 264k+正規表現 → 4.3k・UX 変更（平坦化・件数）を realgui で確認 |
| **E-3 反転** | ローダーが物理チャンネル 1 本につき Signal 1 個を発行。**1024 ガード退役**を同増分で実施。同乗必須: `ExportCsvDialog`（KeyError 根治＋遅延ツリー＋**2-D 親 Signal を受理しない**）・`reference_overlay`（展開規則の認識・**2-D 親を除外**）・`SignalPreviewVM`（線形走査 → 解決器）・`source_info.n_channels`／**診断 fan-out の集約** | **メモリ勝利が着地**（core 590 MB → ~310 MB・オブジェクト 264,004 → 4,324・USS +281 MiB → +15 MiB）。実 GUI psutil 再計測必須 |
| **E-4 後始末** | **チャンネル単位サンプルキャッシュ**＋位置ベース selector／解決器キャッシュと列キャッシュを teardown 会計へ／衝突診断／公開 API 縮小の明文化 | 対話コスト（5 列 2,105→448 ms）とリソース会計の整理 |

E-3 は一時的に幅閾値を高く置いて着地 → prod_demo で広幅を検証 → 閾値を 1 に下げて二重経路を
**同増分内で削除**する安全弁を許容する（**閾値は出荷しない**）。

## 保存すべき契約（違反＝サイレント破壊）

- **LD-14 リーフ名の文法**（`Name.field` / `Name[i]` / `Name[i][j]` / `Name.field[i]`・構造化を
  ndim より先に判定）。これらの文字列は**永続キー**であり、変更は全保存の無言リネームになる。
- **キー生成と逆変換の全単射**: 任意の物理チャンネルについて `parse_leaf` は
  `leaf_names(base, spec)` の全出力を復元できる（dedup `[idx]` と展開 `[i]` の区別を含む）。
- **`_flatten` の返却順序**。
- **二重名の契約**: 表示名は dedup 済み名から、selector は**生チャンネル名**から導く。
- **LD-08 dedup の合成順序**（`Mat[0]` + `[7]` → `Mat[0][7]`）。
- **`metadata['name_deduplicated']`** は `name_total[base] > 1` からのみ設定し、鋳造列へ継承。
- **`exploded` 述語とその帰結**（配列成分は value_labels も conversion_info も持たない・LD-07）。
- **グループ master ndarray の identity 共有**（`source_info` の `id(s.timestamps)` dedup が依存）。
- **`len(timestamps) == source.length` 不変条件**と `SampleSource` プロトコル。
- **非数値リーフで Signal を作らない**（リーフ単位判定・チャンネル単位の一括判定は禁止）。
- **1-D チャンネルの診断メッセージと `signal_name` は byte-identical**（配列/構造化チャンネルの
  列単位 warning の集約は**意図的 supersede**・ユーザー決定 6）。
- **`LoadCancelled` の伝播**とエラー経路の `handle.close()`。
- **キー文字列だけの層はキー文字列だけのまま**（`display_names.py` 等）。

### 意図的逸脱（記録）

- 配列/構造化チャンネルの列単位 warning を物理チャンネル 1 件へ集約（ユーザー決定 6）。
- `Session.signals()` の意味を物理チャンネルのみへ縮小（`AppViewModel.signals()` /
  `Session.unified_timeline_signals()` は縮小ではなく**削除**で決着した — commit `0847373`・
  上の「公開 API の意味縮小」の訂正注を参照）。
- `signal_map()` の非対称 Mapping（列挙は物理のみ・ルックアップは列も解決）。
- 1024 ガード退役に伴う LD-08 dedup インデックスのずれ（`W[0]`→`W[1]`）。
- ツリーのモジュール階層廃止（ドット分割 → 物理チャンネル 1 行・ユーザー決定 3）。
- 件数表示の単位が「展開列を ch と数える」形へ（ユーザー決定 4・design.md の表記規約 R-07 と
  対訳表 G-42 の改訂を伴う）。
- **CSV/Derived は `physical_channel` metadata を持たない**ため 1 列＝1 物理チャンネルとして
  扱われ、CSV ヘッダーの `Arr[0]`/`Arr[1]` は**親行にならず個別の行になる**（MDF の 2 次元
  チャンネルだけが親＋子に畳まれる）。ユーザー可視の挙動変更だが、CSV の `Arr[0]` は
  ローダーが展開した列ではなく**そう名付けられた 1 本のチャンネル**なので、名前の形だけを
  根拠に畳むと実体を偽ることになる（文字列解析ではなく metadata でグループ化する
  ユーザー決定 3 の帰結）。

## 壊れる消費者（重大順）

1. `SignalGroupManager._ensure_namespaced` / `signal_map()` — 中枢。遅延 Mapping 化で吸収。
2. `ChannelBrowserVM._ensure_prep` / `tree_groups` / `_base_of`（**`[` だけでなく `.` でも切る**）。
3. `ExportCsvDialog` — **唯一のハード失敗**（`self._sig_by_key[k]` が素の KeyError）。実 Signal
   オブジェクトを受理時に必要とし、`__init__` で 264k 個の QTreeWidgetItem を同期構築している。
   **2-D 親 Signal を受理してはならない**（96 MB/本の float64 キャッシュを生む）。
4. `reference_overlay` — 空白でなく**誤答**を出す（`target_by_bare` が物理名しか持たない）。
   **2-D 親を重ね対象から除外**する。
5. `SignalPreviewVM._signal` と `ChannelBrowserVM._signal_by_key`/`tooltip_for`（双子・線形走査）。
6. `GraphPanelVM._signal_map` の offset overlay（E-0 で先に解消）。
7. `TeardownService` — 鋳造列と列キャッシュは `SignalGroup.signals` の外に居る。
8. **表示件数の意味**（`source_info.n_channels`・FileBrowser ツールチップ・ブラウザヘッダ）。

## テスト方針（増分A の「保証にならない保証」を繰り返さない）

- **demo-gate 依存の禁止**: `demo_data/*.mf4` は gitignore されており CI で存在しない。
  主要不変条件は**非 demo-gate のテスト**で守る。
- **ドット付きフィールド名の round-trip 固定（Critical 2 の要）**: asammdf で**実書き出し→実
  読み戻し**した配列チャンネル（例 `name='Radar.ObjList'`, dtype
  `[('Radar.ObjList','<u1',(4,)),('Radar.ObjList.dx','<f8',(4,))]`）を fixture に持ち、
  `leaf_names` の全リーフについて `parse_leaf` が厳密に復元することを assert。
  **手書きの合成 dtype 名では再現しない**ため必ず asammdf 往復で作る。両 demo ファイルとも
  構造化チャンネル 0 本であり、この不変条件を一切被覆しない。
- **鋳造キャッシュの生存（Critical 1 の要・非 demo-gate）**: 小さな合成 2-D mf4 を 2 本使い、
  (a) 列を resolve → materialize → **無関係な 2 本目を load** → 同一キーが**同一オブジェクト**を
  返し `is_materialized` が True のまま、(b) 2 本目を `remove_group` しても同上、(c) 自グループの
  remove で副テーブルから消える、(d) **`LazyMdfValues.array()` のスパイ呼び出し回数が増えない**
  （**これが一次 assert** — `is_materialized` は再 mint 後の再 materialize で True に戻るため
  単独では不十分）。sabotage: 副テーブルのクリアを `_invalidate_namespaced()` に相乗りさせると
  RED になることを実証する。
- **全数ラウンドトリップ**: eager 展開が生む全キーに対し `resolve(key) is not None` かつ値・
  master identity・metadata が一致（`Name.field`/`Name[i]`/`Name[i][j]`/`Name.field[i]`/
  LD-08 dedup/`Mat[0]` 衝突/非数値混在 を含む）。**E-1/E-2 で eager 実装が同居している間に固定**する
  （E-3 後は独立オラクルが失われるため）。
- **解決器ミスの診断化**: `parse_leaf` に 1 文字の非対称を入れる／`Mat[0]` 衝突キーを引く の
  2 つで RED になることを sabotage で実証。
- **realgui ①ゲートの恒真化対策**: E-3 後は「未展開」オラクルが自明に真になる。**鋳造を
  観測できる非鋳造 introspection API**（例: 副テーブルのキー集合と mint 回数カウンタ）を
  設け、「親を展開 → 列をプロット → **その列だけ**が鋳造される」を assert する。
- **メモリ**: E-2/E-3 の各出口で psutil 実測（core・実 GUI）。**主指標は USS**。
- **1-D 診断の byte-identical**: 集約が 1-D チャンネルの文言・件数・`signal_name` を変えない。

## 非スコープ

- 親（物理チャンネル）のドラッグ＝全列プロット（純粋な追加機能・YAGNI）。
- 合成子ノードの数値ソート順（別 follow-up）。
- mmap フロア ~205 MiB の削減（別 follow-up）。
- 264k → 4.3k 後に残る Qt/VM コストのさらなる圧縮（増分D の view 仮想化）。
- CSV / Derived 信号（配列展開の概念が無い）。

## グローバル制約

- 品質ゲート全通過（`pytest` / `ruff check` / `ruff format --check` / `mypy src/`）。
- GUI 変更は Layer A/B（CI）必須・Layer C（`--realgui`）で ①ゲート。
- 実装は増分A と同じブランチ `feature/lazy-load-samples` 上（ユーザー決定: 一緒に出荷）。
