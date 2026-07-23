# 雑メモ解消（ドック/メニュー UX）設計

> **出典**: ユーザー雑メモ（デスクトップ `valisync雑メモ.txt`）由来の実装可能 3 項目。
> UIUX 敵対的レビュー catalog（UX/UXG）とは別系統のユーザー直接要望。
> メモリ削減（雑メモ 07/12・native dtype で 10GB→1.36GB 解消済み・真の遅延ロードは将来課題）は本増分から除外。
> ブランチ `feature/memo-ux-cleanup`。
>
> **改訂履歴**: 初版を 6 レンズ敵対的レビュー（34 findings・19 confirmed）で検証し I1（#15 位置ベース）＋Minor 9 を反映
> （#17 機構を候補 A に確定＋ガードレール・縦積み時プロット非拡大の訂正・#14 最小幅の床はタイトルバー・未選択分岐 strings 化・
> カタログ viewport 断定の条件化・テスト assert のハードニング）。

## Goal

ブラウザドック/メニューの 3 つの UX 改善:
- **#14**: チャンネルブラウザのヘッダーから選択中ファイル名表示を廃止し（件数のみ残す）、最小ドック幅を下げる。
- **#15**: チャンネルブラウザの右クリックメニューに「信号プロパティを表示」を追加（ダブルクリックと同じプレビュー窓）。
- **#17**: ドックをチェベロンで折りたたんだとき、折りたたみレールが「プロットと開いているドックの間」でなく**画面端**に来るようにする。

## ユーザー決定（確定）

1. #14: ファイル名廃止後は**件数のみ残す**。どのファイルかは右上ファイルブラウザの選択で判別。
2. #17: 折りたたみレールを**開いているドックより外側（画面端側）**へ。順序 プロット｜開いているドック｜レール〔画面端〕。
3. #17 の現状挙動をユーザー承認済み（再現スクショ提示・2026-07-23）— 片方折りたたみでレールが中央側に挟まる。

## §1 #14: ヘッダーのファイル名廃止＋最小ドック幅

### 現状
`ChannelBrowserVM.header_text()`（[channel_browser_vm.py:187-197](../../../src/valisync/gui/viewmodels/channel_browser_vm.py)）:
未選択=`"ファイル未選択"`（**直書き・strings 非経由**・:191）／空=`"{name} — 0 信号"`（`S.CHANNEL_HEADER_EMPTY_TMPL`）／
通常=`"{name} — {total} 信号中 {shown} 件を表示"`（`S.CHANNEL_HEADER_COUNT_TMPL`・`strings.py:228-229`）。View 側
`ChannelBrowserView.header_label`（[channel_browser_view.py:109](../../../src/valisync/gui/views/channel_browser_view.py)・`QLabel`・**word-wrap 未設定**）が
`_refresh_state()`（:165）で表示。

### 変更
- `header_text()` の各テンプレから**ファイル名プレフィックス `"{name} — "` を除去**（通常=`"{total} 信号中 {shown} 件を表示"`・
  空=`"0 信号"` 等）。**未選択分岐 `"ファイル未選択"` も `S.CHANNEL_HEADER_NO_FILE` として strings.py 化**（D-1「文言 OS＝strings.py 単一の真実」
  の是正機会・現状ハードコードの非対称を解消）。ファイル名除去で stale 化する `header_text` docstring（:188「which file, how many shown」）も更新。
- `header_label` に **`setWordWrap(True)`** を追加（長カウントで最小幅が張り付かない保険）。
- 文言変更は `strings.py` の該当定数改訂＋**対訳表（docs/design.md 表記規約 G 番号）該当行を更新**。

### 最小幅の床（Minor — 期待値管理）
`channel_dock` に明示 `setMinimumWidth` は無いが、**最小幅の律速はヘッダーでなく `CollapsibleDockTitleBar`**
（[collapsible_dock_title_bar.py:51-85](../../../src/valisync/gui/views/collapsible_dock_title_bar.py)・nowrap タイトル QLabel＋float/close 2 ボタン・~181px）。
ヘッダー除去＋word-wrap で最小幅は 375→~181px（**約半分**）まで下がるが、それ以上はタイトルバー律速。
さらに細くするならタイトルラベル省略/stretch 廃止も対象だが**本増分スコープ外**（follow-up）。受け入れは「縮小方向」の相対で判定。

### どのファイルかの判別
右上ファイルブラウザの選択ハイライトに一本化（既存挙動）。ファイル名を別面へ出す配線は追加しない。

## §2 #15: 右クリックに「信号プロパティを表示」

### 現状
`ChannelBrowserView.build_context_menu()`（[channel_browser_view.py:286-294](../../../src/valisync/gui/views/channel_browser_view.py)）は
「アクティブパネルへ追加」（`S.ACTION_ADD_TO_ACTIVE_PANEL`・**複数選択前提**）1 項目のみ。信号ダブルクリック→プレビュー窓は
`doubleClicked`→`_emit_preview(index)`（**クリック index 基準**）→`preview_requested.emit(key)`（:141,278-282,61）→
MainWindow `preview_requested.connect(signal_preview_window.show_signal)`（[main_window.py:433-435](../../../src/valisync/gui/views/main_window.py)）で
単一 `SignalPreviewWindow`（プレビュー＋プロパティ）を開く。**右クリックは選択を変えない**（`_show_context_menu`・:301-305）。

### 変更（I1 — 位置ベースに確定）
- `build_context_menu()` に **「信号プロパティを表示」**（`S.ACTION_SHOW_SIGNAL_PROPERTIES` 新設・`strings.py`）を追加。
- **右クリックした行（位置ベース）を対象**にする — `tree.indexAt(pos)` の hit index の leaf キー（`model.signal_key_at`）を使い、
  **ダブルクリック（`_emit_preview`）と同型**にする。`selected_signal_keys()`（選択ベース）は使わない
  （右クリックが選択を変えないため、選択ベースだと右クリック行でなく**既存選択行**がプレビューされる／parent+leaf 同時選択で
  `selected_signal_keys()` が parent を None 除外し len==1 となり誤有効化する、の 2 バグを構造回避）。
- **有効化条件**: 右クリック位置が leaf（`signal_key_at(indexAt(pos))` が None でない）のときのみ有効。parent ノード上/空白では非表示 or disabled。
- `triggered` で `self.preview_requested.emit(hit_key)` → 既存 MainWindow 配線でダブルクリックと同一窓（新規窓/経路なし）。
- `build_context_menu` は現状 `pos` を受け取っているか要確認（`_show_context_menu` から pos 経由で index 解決できるよう配線）。
- 「アクティブパネルへ追加」（複数選択前提）は無回帰維持。

## §3 #17: 折りたたみレールを画面端へ

### 現状（根本原因・再現で確定）
折りたたみは `_collapse_dock`（[main_window.py:983-1013](../../../src/valisync/gui/views/main_window.py)）が `dock.hide()`＋`rail.add_tab`。
レール `DockCollapseRail` は `CentralWithRails`（[central_with_rails.py:14-39](../../../src/valisync/gui/views/central_with_rails.py)）が
**中央ウィジェットの縁**（右ドックなら col2=中央の右端）に据える。QMainWindow の右ドック領域は中央ウィジェットの**外側**にあるため、
右ドック領域に**開いているドックが残っている**と折りたたみレールがプロットと開ドックの間に挟まる（両方折りたたむと右ドック領域が
空になりレールが画面端＝09_collapsed が正）。片方だけ折りたたむと中央側に残るのが不整合（再現スクショで確定）。

### 望ましい挙動（確定・縦積み訂正込み）
- 折りたたみレールは**常に画面端側**（開いているドックより外側）。順序: プロット｜開いているドック｜レール〔画面端〕。
- **プロット幅の訂正（Minor 反映）**: File/Channel は同一右カラムに Vertical split で**縦積み**（[main_window.py:214,217](../../../src/valisync/gui/views/main_window.py)）。
  片方折りたたみでは**兄弟がカラム幅を保持しプロット幅は変わらず、移るのはレールの x 位置のみ**（実測 initial 860→片方畳み 860→
  両方畳み 1120）。**プロット全幅化は辺が完全に空になったとき（両方折りたたみ）のみ**＝既存の縦積み仕様どおりで、ユーザーの
  「画面端に縮める」意図（レールを画面端へ）は満たす。
- 両方折りたたみ（09_collapsed）・全展開の見た目は無回帰に保つ。上下端（診断・BottomDockWidgetArea）でも各辺の画面端側という原則を一貫。

### 機構: 候補 A（レール最外ドック化）に確定
レビューで候補 B/C は不適格と判明したため機構を **A に絞る**:
- **候補 C（CentralWithRails 被包拡大）= 実現不能**: QMainWindow のドック領域は私有 `QMainWindowLayout` が中央ウィジェットの
  外側に配置し、`setCentralWidget` は中央矩形しか制御できず外部ラップの public API が無い。**スパイク対象から除外**。
- **候補 B（窓縁絶対配置オーバーレイ）= 不適格**: レイアウト空間を予約できず full-width の開ドックを内側へ押せない
  （遮蔽で開ドックの外縁ヒット判定を奪うか面積ゼロで浮くかの二択）＋z-order 沈下の false-green 罠
  （[[gui_overlay_sibling_zorder_sinks_behind_later_children]]）。要件を「占有幅ゼロ・遮蔽許容」へ緩めた別物として
  **ユーザー再承認が要る次善候補**に留め、既定では採らない。
- **候補 A（レール最外ドック化）= 採用**: 各辺の最外側に常駐する薄い「レールドック」（`QDockWidget`）を `splitDockWidget`
  で最外へ全高配置し、折りたたみタブをそこへ集約。QMainWindow のドック体系内で完結し既存 saveState/restoreState/D&D/setCorner と共存。

### 候補 A の不変条件維持機構（設計要件・スパイクで実機実証）
Qt は「最外であり続ける」ことを保証しない（`setDockOrder` 相当 API 無し）ため、A 採用には次のガードレールを設計に含める:
1. **レールドックは非移動/非クローズ/非フロート**（`setFeatures(NoDockWidgetFeatures)` 等）＋タイトルバー無し（薄いレール見た目）。
2. **objectName 安定＋既存 saveState blob 互換**（新規常駐ドックが blob 形状を変えるため、旧 state 復元時の互換/移行を確認）。
3. **`dockLocationChanged` で最外順序を再アサート**（ユーザーが開ドックをレール外側へ D&D したら removeDockWidget＋再 split で最外へ戻す＝
  **D&D 順序破れは能動是正**を既定とする）。
4. **restoreState 後に順序＋`setCorner`＋`_apply_default_dock_ratio`（1:4）を再適用**（レールドックが 3 番目の参加者になるため
  1:4（[main_window.py:922-924](../../../src/valisync/gui/views/main_window.py)・2 ドック前提）と BottomRight→Right corner に干渉しないよう調整・
  [[gui_restorestate_resets_dock_corner_config]] と同型）。
- **空時ゼロ幅隠蔽**（レールにタブが無ければ `setVisible(False)` で 0 幅・現行 DockCollapseRail と同型）。
- スパイクは以下を**実 OS で実証**して A を確定: (a) 既定レイアウトから片方/両方折りたたみでレールが開ドックの外側（画面端）に来る、
  (b) 開ドックをレール外側へ D&D→最外順序が能動是正される、(c) 崩れた順序を save→restore 後にレールが最外へ戻る、
  (d) 両方折りたたみ（09）・全展開・折りたたみ永続復元が無回帰。A のガードレールが過度に脆いと判明した場合のみ緩和 B を
  ユーザー再承認の上で代替。

## §4 テスト（gui-test-plan 準拠）

### #14（Layer A/B）
- **T-A1**: `header_text()` がファイル名を含まない（通常/空/未選択の各分岐・未選択も strings 経由）。
- **T-B1**: `header_label.wordWrap()` True・表示にファイル名なし。`channel_dock.minimumSizeHint().width()` がファイル名込み時より
  **小さい方向**（相対比較・絶対 px は環境依存で避ける）。ただし床はタイトルバー律速（~181px）である旨をテストコメントに明記。

### #15（Layer B）
- **T-B2**: leaf 上で右クリック→「信号プロパティを表示」有効・triggered で `preview_requested` が**その行のキー**で発火（signal spy）。
  parent ノード上/空白で右クリック→非表示 or disabled。**sabotage 2 種**: (1) 選択ベース実装（`selected_signal_keys`）→ 別行を
  選択中に非選択 leaf を右クリックすると既存選択行がプレビューされ RED。(2) parent+leaf 同時選択で有効化する実装 → RED。

### #17（Layer C・realgui ①ゲート — 最重要）
- **T-C1 片方折りたたみのレール位置（非重なり境界）**: 実 OS で 2 ドック開状態 → チェベロンで片方折りたたみ →
  **右領域: `rail.left() >= openDock.right()`（グローバル座標・非重なり）**、`widgetAt(レール中心)` が実際にレールを指す
  （実描画・z-order 沈下 false-green を排除）。File 折りたたみ/Channel 折りたたみ両対称。実ピクセルスクショ添付。
  **honest-RED**: 現状（レールが中央側）でこの assert が RED になることを機構変更前に実証。
- **T-C1b 候補 A 不変条件（最外維持）**: 開ドックを実 OS D&D でレール外側へ移動 → 最外順序が能動是正される。
  順序を崩した save→restore 後にレールが最外へ戻る（永続の順序/corner/1:4 再適用）。
- **T-C2 無回帰＋extent 復元**: 両方折りたたみ（09 相当）でレール画面端・プロット全幅／全展開でレールゼロ幅、が不変。
  collapse→expand 後に `dock.width()/height()` を捕捉 `_expanded_extent`（[main_window.py:980-981,997,1035](../../../src/valisync/gui/views/main_window.py)）と
  **両側数 px 以内で一致**（既存 `expanded_width >= initial_width - 40` の下限スロップはレール幅ぶんの回帰を吸収するため、
  両側許容 or レール幅明示控除へ改める）。
- **既存テストのハンドル依存監査**: 既存 collapse realgui（`test_collapsible_docks_realclick.py` の `central.width` reclaim assert・
  `_central_with_rails`/`_collapse_rails[area]`/`rail._tabs` 直参照）は候補 A の再構成で無効化しうる。**単独折りたたみの
  central.width 観測量は機構により無効（縦積みで幅不変）→ レール矩形 x 比較へ置換**し、内部ハンドル参照を洗い出して移行。

### ①証拠ゲート
`uv run pytest tests/realgui/ --realgui -q` フル＋T-C1/T-C1b/T-C2 のスクショ/矩形実測を merge 前に必須化。

## §5 凍結カタログ

- **#14**: チャンネルブラウザのヘッダーテキストが変わる。**右ドック列の幅を何が pin するか実測**して per-state 差分を確定:
  - 列幅がタイトルバー/ツリー律速（ヘッダー非律速）なら #14 の最小幅効果はカタログ非実証で **T-B1 が担保**（プロット viewport 不変）。
  - 列幅がヘッダー律速なら #14 で列縮小→中央プロットが広がり `--crop-meta` NG になりうる → 02-05 の**ベースライン再取得**を織り込む。
  - `setWordWrap(True)` は `heightForWidth` 依存 sizeHint 化で列幅算定を変えうる → 撮影で検証項目に含める。
- **#15**: 右クリックメニューは撮影対象外（静的差分なし）。
- **#17**: 09_collapsed の不変は**採用機構（A）がレール strip 幅・描画・プロット viewport 右端を現状とピクセル一致で保つ場合のみ**
  成立（A で最外ドック化するとレール位置/幅が変わり 09 のプロット viewport 右端が動く可能性 → 動くなら **09 も再ベースライン**）。
  片方折りたたみ状態はカタログに無いため、**新規状態 `10_collapse_one` を追加**してレール画面端配置を凍結被覆するのを推奨
  （realgui T-C1 を一次被覆とし、機構 B を将来採る場合は 10_collapse_one を必須化）。
- per-state 期待差分に限定を確認 → ベースライン昇格 → 再撮影 compare exit 0（両テーマ）＋決定性。

## §6 受け入れ基準

1. チャンネルブラウザのヘッダーにファイル名が出ない（件数のみ・未選択分岐も strings 経由）・最小ドック幅が縮小方向（床はタイトルバー ~181px）。
2. 右クリックに「信号プロパティを表示」（**右クリックした leaf 行**が対象・parent/空白で無効）・ダブルクリックと同じプレビュー窓が開く。
3. 片方折りたたみでレールが**開いているドックの外側（画面端）**に非重なりで来る（実 OS ピクセルで実証）。プロット幅は縦積み仕様どおり
   （片方では不変・両方で全幅）。
4. 候補 A の不変条件（D&D で最外是正・save/restore で最外復元・空時ゼロ幅）を実 OS 実証。両方折りたたみ（09）・全展開・
   折りたたみ永続が無回帰。
5. full suite green・realgui フル＋T-C1/T-C1b/T-C2・凍結 per-state 契約・決定性 exit 0。

## §7 敵対的レビューが攻撃すべき点（closure anchors）

- **#17 候補 A の最外不変**: D&D 順序破れの能動是正・restoreState 後の順序/corner/1:4 再適用・objectName saveState 互換・空時ゼロ幅が
  実 OS で成立するか（honest-RED→GREEN・T-C1b）。A が脆いなら緩和 B（ユーザー再承認）へ。
- **#17 レール位置の非重なり**: `rail.left() >= openDock.right()` ＋ `widgetAt` 実描画で「外側」を厳格実証（単一 x 比較の素通し・
  z-order 沈下 false-green を排除）。
- **#17 プロット幅の訂正整合**: 片方折りたたみでプロット幅不変・両方で全幅、が spec/テストで一貫（既存 central.width reclaim assert の
  無効化を移行済みか）。extent 復元の両側 assert。
- **#15 位置ベース**: 右クリック行（indexAt）が対象で選択ベースの stale/parent+leaf 誤有効化を回避（sabotage 2 種）。既存「追加」無回帰。
- **#14 最小幅の床**: ヘッダー除去＋word-wrap で最小幅が下がるが床はタイトルバー（~181px）— 期待値管理。word-wrap の高さ増でヘッダー
  2 行化・レイアウト波及がないか。未選択分岐 strings 化・docstring 更新。ファイル名喪失の判別性（ファイルブラウザ選択のみ）。
- **凍結カタログ**: #14 の列幅 pin 要因の実測・09 不変の条件性・10_collapse_one 追加。プロット viewport 断定の条件化。
- **文言**: strings.py 集約・対訳表更新・恒真テストなし。
