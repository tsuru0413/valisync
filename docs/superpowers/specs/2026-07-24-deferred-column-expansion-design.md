# 配列チャンネルの列展開を遅延化する設計（増分E）

> **位置づけ**: [遅延ロード設計](2026-07-24-lazy-load-signal-samples-design.md)（増分A・完了）の続き。
> A は「値」を遅延化した。本 spec は「**列展開そのもの**」を遅延化し、残る per-列 Python
> オブジェクト残渣を落とす。ユーザー決定により、増分A と**同一ブランチで一緒に出荷**する。

## 背景 — なぜまだ重いのか（実測）

増分A で値は完全に shed された（realgui 実証: 1本プロット後も未プロット 263,999 信号は
`is_materialized == False`）。にもかかわらず `prod_demo.mf4` の実 GUI 定常 RSS は **868 MB**。
残りの支配項は**値ではなくオブジェクト数**である。

`demo_data/prod_demo.mf4` の実測（ヘッドレス core・値は未展開）:

| 段階 | RSS |
|---|---|
| baseline | 87 MB |
| `Session.load` 後（264,004 信号・7.0 s） | 471 MB (+384) |
| `signal_map()` 後 | 532 MB (+61) |
| `group_signals()` 後 | **590 MB** |

内訳（tracemalloc・1 列あたり）:

| 要素 | コスト |
|---|---|
| Signal シェル＋`LazyMdfValues`＋metadata dict | 572 B/列 |
| namespaced ラッパー（2 系統キャッシュ） | 201 B/列 |
| `ChannelBrowserVM._prep` | 258 B/列（計 68 MB） |
| `_Node.leaves`（tree_groups の葉トリプル） | 計 19 MB |

**per-列オブジェクトに帰属するのは約 390 MB**（core ~300 MB＋GUI ~87 MB）。

**構造的な原因**: このファイルは**物理 4,324 チャンネル**しか無い。`Prod10_0000` は
shape (12000, 1000) の**1 本のチャンネル**である。LD-14 がロード時にこれを 1,000 本の
Signal へ展開するため、4,324 → **264,004 オブジェクト（61 倍）**になる。

**asammdf GUI の実測比較**（[調査記録](../../.superpowers/sdd/asammdf-gui-open-strategy.md)）:
asammdf はツリーに**物理チャンネル 1 行**（4,329 行）しか作らず、`Name[i][j]` への展開は
**プロットへドロップした時だけ**行う（`mdi_area.py:1512-1570`）。tree item は
`(group, index)+name` のみを持ち、単位/コメントはダブルクリック時に取得する。
同じ tree item を 264,009 件作ると **+289 MB**、4,329 件なら **+4 MB** と実測されており、
**我々の残渣のうち ~285 MB はエントリ数そのものに内在**する。

## 目的

**ロード時に列を展開しない。** ローダーは物理チャンネル 1 本につき Signal 1 個（＋列仕様）を
作り、`grp::Prod10_0000[7]` のような**列キーは要求時に解決して生成**する。ユーザーから見た
操作は現状維持（折りたたみ行 → 展開 → 列を個別に選択）。

**期待効果**: per-列オブジェクト **264,004 → 4,324**、**約 390 MB 削減**、
ロード実測 7.0 s の短縮（264k 個の Signal 構築・metadata dict・診断 fan-out が消える）。

## ユーザー決定（確定）

1. **列の個別選択は維持する**（案B）。asammdf 完全パリティ（案A）は「ブラウザから単一列を
   選ぶ」機能を失う（asammdf にはその経路が無い — `'Prod10_0000[5]' in mdf` は False）。
   ADAS の配列チャンネル（レーダー物体リスト等）では特定列だけ見る用途が主であり、
   パリティのために能力を削るのは誤ったトレードオフ。
2. **1024 列超の制限を廃止し、これらのチャンネルを表示する**。遅延化により
   「展開すると重い」という前提が消えるため、`EXPANSION_COLUMN_LIMIT` /
   `ExpansionDialog` / `ConfirmExpansion` を退役させる。`prod_demo` では今まで
   既定スキップされ**一覧に出ていなかった 60 本**が使えるようになる（列数 264,004 → 330,004）。

## 推奨（ユーザー確認待ち・spec 内の既定値）

3. **件数表示は両方併記**「4,324 ch（330,004 列）」。遅延展開後は**ツリーの行数＝物理
   チャンネル数**になるため、表示数と行数が一致する。列数のみだと 4,324 行しか無いのに
   330,004 と出るズレが目立つ。フィルタ時も安価（一致した物理チャンネルの列数を合計するだけ）。
4. **フィルタは列名にもマッチさせる（キャッシュ無し）**。実測（4,324 物理 ch / 330,004 列）:

   | 方式 | キー入力ごと | 追加メモリ |
   |---|---|---|
   | 物理チャンネル名のみ | 0.4 ms | 0 MB |
   | **列名も検索・都度生成（採用）** | **149 ms** | **0 MB** |
   | 列名も検索・名前だけキャッシュ | 39–46 ms | 41.7 MB（初回 116 ms） |
   | （参考）現行実装 | 170–213 ms | — |

   列名検索を維持しても**現行より速い**。将来もっと速くしたければ名前キャッシュを後から
   足せる（差し替え可能・設計に影響しない）。

## 技術判断（本 spec で確定）

- **selector は位置ベース**にする。現行 `LazyMdfValues.array()` はチャンネル全体を再 flatten
  して名前で 1 列を引くため、同一チャンネルの k 列をプロットすると **k 回のフル flatten**に
  なる。遅延展開はこれを対話コストとして可視化するため、selector を「リーフ名」から
  「軸ごとのインデックス列（＋構造化フィールド名）」へ変える。名前ベースの安全確認は
  ロード時のプローブで担保する。
- **`Mat[0]` 衝突**（2次元チャンネル `Mat` の第0列と、`Mat[0]` という名前の 1 次元チャンネル）は
  **親アンカー解決で実チャンネルを優先**し、ロード時に info 診断を 1 件出す。現行は無警告で
  未定義（`name_total` は物理名しか数えない）。
- **「N 本に展開」info 診断はロード時に維持**する（`_leaf_column_count(probe)` から件数を
  再取得。ロード時の展開インベントリが Diagnostics ドックに残る）。
- **合成した列子ノードのソート順は現状維持**（辞書順 `Name[10]` < `Name[2]`）。数値順の方が
  望ましいが、無関係な UX 変更を混ぜない（別途 follow-up）。

## アーキテクチャ

### `ColumnSpec` — 列構造の宣言

物理チャンネル 1 本につき 1 個。`base_name` / 非サンプル軸の shape / 構造化フィールド木 /
`column_count` / `exploded` 述語 / dedup インデックス / `name_deduplicated` を保持する。
ロード時の 1 レコードプローブから作る（値は読まない）。

### `column_names.py` — 命名文法の単一の真実

`leaf_names(base, spec)`（**ジェネレータ**）／`leaf_count(spec)`／
`parse_leaf(display_key, known_base)`（親アンカーの逆変換）。現行は `_flatten` と
`_leaf_column_count` が**同じ規則を 2 箇所で手写し**しており（共有コードも突合 assert も無い）、
遅延化はこの乖離ハザードを広げる。両者をこのモジュールの上に再実装し、
**ジェネレータの順序が `_flatten` と一致すること**をテストで固定する。

### 解決器（resolver）と遅延解決 Mapping — 設計の要

`SignalGroupManager.resolve(key)` / `Session.resolve_signal(key)`: マップに無いキーは
末尾の `[i]` / `.field` トークンを右から剥がし、既知の物理**表示名**に一致したところで
列 Signal を鋳造する（共有 master・`LazyMdfValues(handle, base_name, gi, ci, length, selector)`・
metadata 継承〔`name_deduplicated` と `exploded` の value_labels 抑止を含む〕）。
グループごとの副テーブルにキャッシュし、`_invalidate_namespaced()` で捨てる。

**`signal_map()` は遅延解決 Mapping を返す**。これが本設計の要で、`graph_panel_vm.py` の
約 20 箇所の `sig_map.get(entry.signal_key)`（描画・オートフィット・軸ラベル・カーソル/凡例/
Δ読み値・矢印キー移動）を**無改造**にする。これをやらないと全箇所が「空カーブ・診断なし・
単位空欄・count=0」で**静かに壊れる**。

## 増分分割（各段階で独立に green・危険な反転は最後）

| 増分 | 内容 | 出口 |
|---|---|---|
| **E-0 準備** | 命名文法を `column_names.py` へ抽出（順序突合テスト）／`_signal_map` の offset overlay を O(offset信号) 化（遅延 Mapping の前提・単体で perf 改善）／死蔵コード整理 | 挙動不変・RSS 不変 |
| **E-1 解決器** | `ColumnSpec`＋`resolve()`＋遅延解決 `signal_map()`（**ローダーはまだ展開する**） | 約 20 の呼出点が無改造で通ることを実証・sabotage で鋳造 Signal の等価性を証明 |
| **E-2 ブラウザ** | `_ensure_prep` を物理チャンネル単位に／`tree_groups()` が仕様を返す／`SignalTreeModel._materialize` が子を合成（**ローダーはまだ展開する**＝合成キーが実 Signal に当たるので単独検証可能） | **RSS −約 87 MB**・リビルドコスト 264k+正規表現 → 4.3k・件数/フィルタ/ソートの決定がここに着地 |
| **E-3 反転** | ローダーが物理チャンネル 1 本につき Signal 1 個を発行。同増分で必須の同乗: `ExportCsvDialog`（KeyError 根治＋遅延ツリー）・`reference_overlay`（展開規則の認識）・`SignalPreviewVM`（線形走査 → 解決器）・`source_info.n_channels`＋ヘッダ意味 | **メモリ勝利が着地**（core 590 MB → ~200 MB・オブジェクト 264,004 → 4,324・ロード短縮）。実 GUI psutil 再計測必須 |
| **E-4 後始末** | 1024 ガード退役（`EXPANSION_COLUMN_LIMIT`/`ExpansionDialog`/`ConfirmExpansion` の公開 API 3 面）／解決器キャッシュを teardown 会計へ／位置ベース selector で k 回 flatten を根治／衝突診断 | 公開 API とインタラクティブコストの整理 |

E-3 は**一時的に幅閾値（案C）を高く置いて着地 → prod_demo で広幅を検証 → 閾値を 1 に下げて
二重経路を同増分内で削除**という安全弁を許容する（**閾値は出荷しない**）。

## 保存すべき契約（違反＝サイレント破壊）

- **LD-14 リーフ名の文法**（`Name.field` / `Name[i]` / `Name[i][j]` / `Name.field[i]`・構造化を
  ndim より先に判定）。これらの文字列は**永続キー**であり、変更は全保存の無言リネームになる。
- **`_flatten` の返却順序**（`LazyMdfValues` の列解決と、ローダーの 2 回の flatten の位置対応が依存）。
- **二重名の契約**: 表示名は dedup 済み名から、selector は**生チャンネル名**から導く
  （`Mat[0][7]` → selector `Mat[7]`）。
- **LD-08 dedup の合成順序**: `[idx]` は物理チャンネル単位で先に付き、展開ブラケットはその
  内側に足される（`Mat[0]` + `[7]` → `Mat[0][7]`）。
- **`metadata['name_deduplicated']`**: `name_total[base] > 1` からのみ設定し、`[i]` の文字列
  パターンからは決して設定しない。鋳造した列 Signal へ**継承**する。
- **`exploded` 述語とその帰結**: 配列成分は `value_labels` も `conversion_info` も持たない（LD-07）。
- **グループ master ndarray の identity 共有**（`source_info` の `id(s.timestamps)` dedup と FU-18 が依存）。
- **`len(timestamps) == source.length` 不変条件**と `SampleSource` プロトコル（`is_materialized`
  の意味論は realgui ①ゲートと teardown 会計が依存）。
- **非数値列で Signal を作らない**（`dtype.kind not in 'iufb'`）。構造化チャンネルはフィールド
  ごとに dtype が異なりうるため、チャンネル単位の一括判定にしてはならない。
- **診断メッセージ文字列と `signal_name`**（テストが固定している）。
- **`LoadCancelled` の伝播**とエラー経路の `handle.close()`。
- **キー文字列だけの層はキー文字列だけのまま**（`display_names.py` 等・遅延化に安全な境界）。
- **`_sorted_view_delegate` は配列オブジェクトが同一の場合のみ付ける**。鋳造した列 Signal には
  長寿命の origin が無いため付けない。

## 壊れる消費者（重大順）

1. `SignalGroupManager._ensure_namespaced` / `signal_map()` — 中枢。遅延 Mapping 化で吸収する。
2. `ChannelBrowserVM._ensure_prep` / `tree_groups` / `_base_of` — 全プロット可能キーの発生源。
   `_base_of` は現在 100% 文字列解析（最初の `[` で切る）。
3. `ExportCsvDialog` — **唯一のハード失敗**（`self._sig_by_key[k]` が素の KeyError）。
   実 Signal オブジェクトを受理時に必要とし、`__init__` で 264k 個の QTreeWidgetItem を同期構築している。
4. `reference_overlay` — 空白でなく**誤答**を出す（`target_by_bare` が物理名しか持たない）。
5. `SignalPreviewVM._signal` — `group_signals` の線形走査（現在 O(264k)）。
6. `GraphPanelVM._signal_map` の offset overlay — `base.items()` の全走査は遅延 Mapping と構造的に非互換（E-0 で先に解消）。
7. `TeardownService` — 鋳造された列 Signal は `SignalGroup.signals` の外に居るため会計・解放から漏れる。
8. **表示件数の意味が変わる** — `source_info.n_channels`（FileBrowser ツールチップ）とブラウザヘッダ。

## テスト方針

- **命名文法**: `leaf_names` ジェネレータの順序＝`_flatten` の順序（両実装の乖離を封じる）。
- **解決器の等価性**: 鋳造した列 Signal が eager 展開版と**同一の値・同一の master オブジェクト・
  同一の metadata**（`name_deduplicated` / value_labels 抑止を含む）を持つ。sabotage で証明する。
- **遅延の証明**: E-3 後、ロード直後の Signal 数＝物理チャンネル数（4,324）であること、
  列をプロットして初めて列 Signal が鋳造されることを実データで assert。
- **メモリ**: E-2/E-3 の各出口で psutil 実測（core・実 GUI）。増分A で確立した peak/steady 法。
- **realgui ①ゲート（E-2/E-3/E-4 で必須）**: 実 OS 入力で「親を展開 → 列をプロット → 列を
  プレビュー → 列をエクスポート」。既存の lazy-load realgui テストは新しい不変条件へ更新する。
- **CI で効くこと**: 増分A の最終レビューが捕捉した「demo-gate 頼みで CI 無被覆」を繰り返さない。
  主要不変条件は非 demo-gate のテストで守る。

## 非スコープ

- 親（物理チャンネル）のドラッグ＝全列プロット（純粋な追加機能・YAGNI・E-4 で任意）。
- 合成子ノードの数値ソート順（別 follow-up）。
- 264k → 4.3k 後に残る Qt/VM コストのさらなる圧縮（増分D の view 仮想化が扱う）。
- CSV / Derived 信号（配列展開の概念が無い）。

## グローバル制約

- 品質ゲート全通過（`pytest` / `ruff check` / `ruff format --check` / `mypy src/`）。
- GUI 変更は Layer A/B（CI）必須・Layer C（`--realgui`）で ①ゲート。
- 実装は増分A と同じブランチ `feature/lazy-load-samples` 上（ユーザー決定: 一緒に出荷）。
