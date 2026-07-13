# FU-22 (B) ChannelBrowser 階層ツリー仮想化 設計 spec

## 背景と課題

大容量ファイル(prod 264k)を選択/切替すると ChannelBrowser が ~5s フリーズする(FU-22)。(A) 無条件 same-key re-fire は `set_active_file` 同一キーガードで解消済み(prod 5,230ms->0ms)。**本 spec は (B) = genuine なファイル選択/切替の真の 264k 構築コスト**を扱う。

### 真因(Phase 1 + 設計 spike で実測確定)
- 内訳計測(real widget tree・prod_demo 264k): VM の SignalItem 構築は 484ms のみ。支配コストは **QTreeView が 264k フル model reset に同期反応 ~2,750ms**(フラット model でも reset ごとに 264k 分の内部 `viewItems` を `doItemsLayout` で構築) + QSortFilterProxyModel(PC-20 sort) の 264k 再マップ ~1,550ms。
- ビュー種別 spike(各ビュー単独接続で 264k reset): QTreeView+proxy=4,414ms・QTableView+proxy=**18ms**・view 無し=6ms。QTreeView 自体が真因。

### データ形状(prod_demo・階層化の feasibility)
展開後リーフ 264,004 のうち **98.5%(260,000)が 260 個の配列変数(各 ~1,000 リーフ)の下**。distinct ベースチャンネルは **4,264**(スカラー 4,004 + 配列 260)。→ 配列を親ノードに畳んだ階層ツリーの top-level は 4,264 行。QTreeView+proxy の reset を 4,264 行で実測 = **67ms**(5,264 行で 82ms)。

## 選定アプローチ(ユーザー合意: Path B)

**遅延階層 QTreeView**: 配列変数を親ノード・要素を子ノードで遅延展開する。畳んだ状態で top-level 4,264 行のみ reset(~67ms) するため 5s フリーズを解消し、かつ**将来計画の配列ツリー表示を今実現**する(ユーザーのロードマップに合致・後の再作業なし)。

**却下した代替**:
- Path A(QTreeView->QTableView フラット・18ms): 最小・低リスクだがフラットのみ = 配列ツリー不可。ユーザーが配列ツリーを計画しており、後で作り直す無駄を避けるため却下。
- fetchMore incremental / 自作仮想スクロール: 総数既知ゆえ過剰(YAGNI)。畳んだ木で十分。

## アーキテクチャ

### 1. `SignalTreeModel`(新規・`QAbstractItemModel`・階層)
- **top-level** = ベースチャンネル 4,264。スカラーは子なしリーフ扱い、配列は親ノード。
- **子** = 配列要素(LD-14 命名 `Name[i]`/`Name[i][j]`/`Name.field` のリーフ)。
- **遅延 materialize**: `fetchMore`/`canFetchMore` は使わない(総数既知 = 過剰)。QTreeView は展開時に `hasChildren`->`rowCount`->`index` を呼ぶので、**子ノードは `rowCount(parentIndex)`/`index(row,col,parent)` の初回呼出で構築しキャッシュ**する。
- **node グラフはモデルが所有**(最重要): `class _Node: __slots__ = ("key", "base", "children", "parent", "row")`。top-level `list[_Node]` をモデルが保持し、親 `_Node.children` は初回 `rowCount` で `[_Node(...)]` を構築キャッシュ。`createIndex(row, col, node)` に渡す node は**必ずキャッシュ済み**(transient node を internalPointer に渡すと即ダングリング -> クラッシュ)。
- **メソッド**:
  - `index(row, col, parent)`: parent 無効 -> top-level[row]、有効 -> 親 node.children[row](初回 materialize)。
  - `parent(index)`: node.parent から親の (row, node) を復元し `createIndex`。
  - `hasChildren(index)`: 配列親 -> True、スカラー/リーフ -> False。
  - `rowCount(parent)`: 無効 -> len(top-level)、配列親 -> len(children)(初回 materialize)、リーフ -> 0。
  - `columnCount` = 2(Name, Unit)。`data`: リーフ -> orig 名/unit、親 -> `Base` 名(unit は増分⑤で集約)。
  - `flags`: リーフ/親とも ItemIsDragEnabled(親追加の意味論は増分④)。`mimeData`/`mimeTypes`: 既存 flat model と同一の namespaced key encode(親は全リーフ keys・増分④)。
- **リーフ SignalItem は展開時のみ遅延生成**(top-level 4,264 のみ eager)。-> **484ms VM 構築も自然消滅**(Path B の副次的勝利)。

### 2. `ChannelBrowserVM`(改修)
- active file ごとに **base -> [leaf signal_keys] のグルーピングを1回構築**(264k 走査だが top-level マップのみ = 現 `_ensure_prep` 152ms 相当)。ベース = LD-14 名の最初の `[`/`.` 以前。
- 既存の `signals`(flat SignalItem 列) は tree model が置換するため、tree 供給 API(`tree_structure()` or model が VM から直接読む)へ移行。FU-11 の precompute(lower 済みタプル)はフィルタ(増分②)で流用。
- active file 不変ガード(FU-22 A)・memo は維持。

### 3. proxy / フィルタ / sort（実装後の実測で改訂 — 下記「実装後の実測知見」参照）
- **proxy は撤去し model を tree に直結する**（改訂）。当初は「proxy = accept-all + sort 専用（現行踏襲）」で sort をレベル内に成立させる計画だったが、**prod 264k 実測で QSortFilterProxyModel が reset マッピング時に全 array 親の rowCount/hasChildren を source 転送し `_materialize` を呼ぶ = 260k 子ノードを eager 構築（遅延・省メモリを完全破壊）＋~456ms コスト**と判明。plain proxy（recursiveFilteringEnabled OFF・dynamicSortFilter OFF でも）は遅延ツリーと根本非互換。→ **proxy 撤去（増分①）**。
- **フィルタは VM 側**（proxy 無しでも不変）。VM の `tree_groups()` がフィルタ済み構造を返し model が rebuild。`setRecursiveFilteringEnabled` は元より不採用（全子 materialize 強制）。**増分② の実測で確定（下記「増分② フィルタ実測」）**: A（階層保持）+ debounce + filter=`fl in leaf名`。
- **sort は VM-side（増分③）**。proxy 撤去に伴い PC-20 sort は SignalTreeModel が `_top` グループ + 各親の children をソートする VM-side 方式へ移行（増分③）。増分①では sort を一時停止（PC-20 sort テストは filter 同様 skip）。

### 4. realgui 掴み点(grab-point)（proxy 撤去に伴い改訂）
- proxy 撤去後は tree の model が SignalTreeModel 直結のため、掴み点は **model index 直接**: top-level = `model.index(row, 0)`、子 = `model.index(childRow, 0, parentIndex)`（親を展開してから）。`proxy.index`/`mapToSource`/`mapFromSource` は不要。
- スカラー信号は top-level リーフ = 従来どおり `model.index(row, 0)` で掴める（既存 realgui は無回帰）。array 子のドラッグは親展開 + `model.index(childRow, 0, parentIndex)`。

### 5. D&D / 追加の意味論(増分④)
- 親ノード追加/D&D = 全リーフ signal_keys。**大配列(> 閾値・既定 50)は確認ダイアログ**(DI 注入)で事故防止。リーフは単一。
- **batch add API 必須**: 現 `GraphPanelVM.add_signal_to_axis`(graph_panel_vm.py:236)は呼ぶたび `_auto_fit_ranges()`(全 plotted 走査)+`_invalidate_cache()`+`_notify("signals")`(=render)。drop handler(graph_panel_view.py)は per-key ループ。-> 親(1,000 リーフ)追加を per-key で回すと **1,000 render + O(n^2) auto-fit = 別の秒単位フリーズ**。`add_signals(keys, axis_index)`(全 append 後に auto_fit/invalidate/notify を **1 回**)を新設し、drop handler と親追加の両方をそれ経由に。確認後の 1,000 追加自体が batch O(n) 1-render でないと確認の意味がない(1,000 曲線 paint は plot 側の一般コスト = 閾値/確認が唯一のガード)。

## 増分計画(各 shippable・merge 前にパリティ必須)

| 増分 | 内容 | ship 判定 |
|---|---|---|
| **① コア** | `SignalTreeModel` + VM ツリーグルーピング + view を階層モデルへ + 展開/折畳 + **リーフ選択/D&D/追加パリティ** + grab-point 親スレッド化 + **proxy 撤去（model 直結・遅延保持）** + **header/empty count-only（264k SignalItem build 撤去）** | **5s フリーズ解消 → ~400ms（実測・11x）・遅延保持（materialized 0）**。①単体で主症状解消 = 最小 shippable コア |
| ② フィルタ | VM 側・filter=`fl in leaf名`・**A（階層保持）+ debounce**（実測確定・下記） | 検索パリティ復旧 |
| ③ sort（VM-side） | SignalTreeModel が `_top`/children をソート（proxy 撤去済のため VM-side・元「proxy 親ごと子ソート」から改訂） | ソートパリティ復旧 |
| ④ 親 D&D/追加 | `add_signals` batch API + 大配列確認ダイアログ | 親操作 + 再フリーズ防止 |
| ⑤ 磨き(defer 可) | 親 `Base (N)` 表示・unit 集約・遅延リッチツールチップ(PC-19 相当) | 表示品質 |

主症状は①で解消。②③④はパリティ回帰の復旧(独立増分だが merge 前必須)。⑤は defer 可。

## 実装後の実測知見（2026-07-13・systematic-debugging）

Path B 実装（Task 1-4）後の prod 264k 実測で、設計の2つの楽観的仮定が誤りと判明:

1. **QSortFilterProxyModel は遅延ツリーと根本非互換**。当初「proxy = accept-all + sort（増分③まで保持）」としたが、proxy は reset マッピング時に全 array 親の rowCount/hasChildren を source へ転送し `_materialize` を呼ぶ = **260 配列 × ~1000 = 260,000 子ノードを eager 構築**（decisive: bare tree=materialized 0 / tree+proxy=materialized 260・child 260,000）。→ ~456ms コスト + 遅延/省メモリの完全破壊。`dynamicSortFilter=False`/`recursiveFilteringEnabled=False` でも変わらず。**→ proxy 撤去（増分①）・sort は VM-side（増分③）へ改訂**。
2. **「484ms VM 構築消滅」は誤り**。model 以外に view の `header_text()`（`len(self.signals)`）/`empty_state()`（`if not self.signals`）も `signals` の consumer で、genuine switch ごとに 264k SignalItem を構築（~263ms）。**→ header/empty を count-only 化（`_prep` 長ベース）で撤去（増分①）**。

実測（prod 264k・offscreen・genuine switch）: OLD flat QTreeView+proxy = 5,027ms → 実装済み①（tree+proxy+leak）= ~1,281ms（4x・但し遅延破壊）→ **推奨修正（no proxy + count-only）= ~397-450ms（11x・遅延保持 materialized 0）**。VM floor: prep 139ms + grouping 153ms（264k `_base_of` regex）+ bare tree reset ~80ms。増分① 最終統合実測（実 cbview）= **451ms（11.1x）**。

## 増分② フィルタ実測（2026-07-14・prod 264k）

階層保持フィルタ（マッチしたリーフを base で再グルーピング）を prod で実測し設計確定:
- scan+group（`_prep` 264k 走査）= match 数に依らず **~170-213ms**（O(264k) スキャンが支配）。end-to-end set_filter->tree reset（実 view）= **220-260ms/打鍵**。
- **A（階層保持）を採用**（B フラット表示は却下）: 広いフィルタ（"prod10"=180,000 leaves）で B はフラット 180k 行 reset ＝元のフリーズ再来。A は top-level を ≤4,264（"prod10" で 180）に畳むため広くても reset 安価。
- **debounce（~200ms・singleShot QTimer）** で per-keystroke 250ms のタイプ遅延を解消（scan は入力停止後 1 回）。
- **filter = `fl in leaf_orig.lower()`**（`fl in base` は冗長 — LD-14 で base は leaf orig の接頭辞ゆえ `fl in base ⟹ fl in leaf`）。ユーザー選択の「リーフ+親名マッチ」は接頭辞で自動充足、`shown_count`（同 `fl in lo`）とも整合。
- **増分② 実装後の統合実測（実 cbview・prod 264k）**: set_filter 適用 = prod10 210ms/top180・narrow 71ms/top1・no-match 76ms・空復帰（全 4,264）282ms。全 one-shot でフリーズ閾値以下。debounce で per-keystroke ブロック無し。**増分② 完了。**

## テスト設計(gui-test-plan: 入力経路直結の view 変更 = クロスカット)

- **Layer A(`SignalTreeModel`)**: `index/parent` 往復不変(`m.parent(m.index(r,0,p)) == p`)・`hasChildren`(配列 True/スカラー False)・lazy materialize(展開前は children 未構築)・rowCount(top-level/子/リーフ)・data(リーフ名/unit)。QAbstractItemModel はバグ面が広いため往復・遅延を厳密に。
- **Layer B(VM + model + proxy 統合)**: ベースグルーピングの正しさ・リーフ選択が源 signal_key を解決(`proxy.index` 親スレッド + `mapToSource`)・親選択が全リーフ keys を解決・`mimeData` が壊れない・active file 切替で model reset が数十ms(中規模 N で閾値未満)。
- **realgui クラスタ全実行**(gui-verify クロスカット): 展開/折畳・リーフ D&D・複数選択・Enter/ダブルクリック追加・右クリックメニュー・(増分②以降)フィルタ/ソート・(増分④)親 D&D + 確認ダイアログ + batch add。掴み点は親スレッド化で境界再監査(3 realgui ファイル)。
- **prod 実測記録**(perf は実測・Layer A は behavioral): ① file 選択 5,000ms -> ~500ms 以下(reset ~67ms)・② フィルタ非フリーズ・④ 親 1,000 追加が batch で O(n) 1-render。

## YAGNI で除外

- fetchMore/canFetchMore(総数既知)、自作仮想スクロール。
- `recursiveFilteringEnabled`(遅延を殺す)。
- 増分⑤(親表示磨き・unit 集約・リッチツールチップ)は主症状に非必須 = defer 可。
- 親追加の「全要素を1曲線に集約」等の高度可視化(別要望)。

## Global 制約

- core(session.py/Signal/VM の非 Qt 部) は Qt 非依存維持。`SignalTreeModel` は gui/adapters。
- 品質ゲート: pytest/ruff check/ruff format --check/mypy 全通過。
- Python コメント/文字列に全角約物 `()：+=` 禁止(RUF001/002/003)。ASCII を使う(矢印 `->`/`→`・`・` は可)。
