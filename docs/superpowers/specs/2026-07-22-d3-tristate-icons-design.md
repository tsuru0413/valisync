# 増分D-3「三態トグル＋アイコン統一」設計（UX-34/38 残余/45・カタログ推奨4 第3層）

- **出典**: UIUX 敵対的レビューカタログ推奨4 の第3層。ユーザー承認済みモックアップ（2026-07-22）が要件の一次表現。
- **スコープ調整（記録済み）**: シェブロン辺解決は PR #143 で先行完了。「Sync X を View メニューへ追加」（旧 UX-32 案）は計測 IA v3 決定で supersede — 含めない。**絵文字グリフ置換の defer（増分5）は本増分で解除**（D-3 着手承認がその解除 — design.md 決定履歴へ記録）。**UX-38 残余（タブ✕の 24px ヒット — PR #137 で増分D へ移管）を本増分が引き取る**。
- **レビュー履歴**: 敵対的 spec レビュー（4 レンズ・25 エージェント・全指摘 Qt 実測検証つき）32 件を反映済み。三態判定述語・info トークン衝突・タブ✕機構は初版が実測で崩れ本版で確定。

## 1. 修正一覧と対象カタログ行

| # | カタログ | 内容 |
|---|---|---|
| A | UX-45（＋UX-32 の三態部分） | ドックトグルの三態化（カスタム QAction・Qt toggleViewAction とのパリティ維持＋レール状態の可視化） |
| B | UX-34（核心・部分解消） | 診断レベルアイコンの Lucide 化＋ **warning/info トークン新設**（非テキスト 3:1 基準・選択セル対応） |
| C | UX-34（タブ✕/タイトルバー）＋UX-38 残余 | タブ✕の常駐赤排除（ニュートラル＋hover 赤・24px ヒット）・タイトルバー ✕/❐ の Lucide 化 |

## 2. 設計

### 2.1 新規トークン（`theme/tokens.py`）— 衝突総当たり・AA 基準確定済み

| トークン | DARK | LIGHT | 用途 |
|---|---|---|---|
| `warning` | `#fab387` | `#b0741a`（amber 保持で 3:1 台 — 実装時に AA テストで検証・微調整可） | 診断 warning の意味色 |
| `info` | `#7aa2f7` | `#1a5fb4` | 診断 info の意味色 |

- **AA 基準の確定**: warning/info は**アイコン（非テキスト UI 部品）用途 — WCAG 1.4.11 の 3:1** を、**chrome_base と chrome_window の双方**（診断テーブル面とカウンタ行面）に対して要求する。テキスト用途に転用する場合は 4.5:1 を別途要求。初版候補 LIGHT warning #df8e1d は実測 2.15:1 で不採用（4.5:1 を狙う darken は暗褐色化で amber 序列が壊れるため 3:1 基準を採る — レビュー実測に基づく設計判断）。
- **コントラスト計算ヘルパの新設**: repo に WCAG コントラスト計算は現存しない（過去の「AA 実測」はオフライン選定＋値ロックのみ — chrome_highlight_text が AA 未達のまま出荷されている実証あり）。**相対輝度→コントラスト比の純関数をテストヘルパとして新設**し、warning/info × {chrome_base, chrome_window} × 両テーマの ≥3:1 を assert するテストを常設する。
- **値衝突の総当たり点検（済）**: 初版 info 候補（DARK #89b4fa・LIGHT #1e66f5）は **chrome_highlight と両テーマ完全同値・LIGHT は busy_spinner とも同値**で不採用（UX-35 で解消した「選択色と別意味の同色」クラスの再導入になる）。確定値 #7aa2f7/#1a5fb4 は既存全トークンと非衝突（実装時に総当たりテストで再確認・同値が生じたら値分岐テスト必須の既存規約）。
- **golden 追随**: DARK スナップショット（fields 全反復）は追加で RED — golden 更新。**LIGHT スナップショットは明示リスト反復のため warning/info の追記を忘れると無音で素通し** — 両 golden への追記を実装手順に含める。

### 2.2 icons レジストリ拡張（`theme/icons.py`）

- **新規 vendored Lucide SVG（11 個・既存と同一 pin 版・無改変）**: `circle-x`・`triangle-alert`・`info`・`x`・`copy`・`panel-left`・`panel-left-close`・`panel-right`・`panel-right-close`・`panel-bottom`・`panel-bottom-close`。
- **意味名**: `diag_error`/`diag_warning`/`diag_info`・`close`・`float_dock`・`dock_panel_{left,right,bottom}`・`dock_panel_{left,right,bottom}_partial`。
- **`icon(name, color=None, active_color=None, selected_color=None)` へ拡張**:
  - `color=None`: 現行どおり Normal=chrome_text/Disabled=chrome_disabled_text（既存呼出は無変更互換）。
  - `color` 指定: Normal=指定色。**`selected_color` 指定時は QIcon.Mode.Selected へ着色ピクスマップを併載**（診断アイコンは selected_color=chrome_highlight_text — 選択セル上で error/warning/info が 1.0〜1.2:1 の不可視になる実測退行の根治）。
  - **`active_color` 指定時は QIcon.Mode.Active へ併載**（タブ✕の hover 赤 — QSS はピクスマップ色を変えられないため。autoRaise QToolButton の hover は Active モードで描画される）。
- **wheel 検証**: 「既存の wheel テストが担保」は**誤り — wheel/package-data テストは現存しない**。pyproject の `icons/**/*.svg` 再帰 glob が新規 SVG を被覆するが、**本増分で wheel テストを新設**（`uv build --wheel` → zipfile で新規 SVG 11 個の同梱 assert・増分5 の false-green の恒久防波堤）。
- SVG currentColor 規約テストは glob で自動被覆（既存）。

### 2.3 A — ドックトグルの三態化

**構造**: `toggleViewAction()` の掲載（View メニュー・ツールバーの 2 面×3 ドック）を、ドックごと 1 個の**カスタム checkable QAction（2 面共有）**へ置換。text は `strings.DOCK_*` 定数（非ニーモニクス — G-46 決定どおり）。**ツールバー側の 3 ボタンは `ToolButtonTextBesideIcon`**（File/Channel は同一辺=右で三態アイコンが同一になるため、テキスト無しでは区別不能 — 実測で確認済みの退行を回避。モックアップともテキスト併記で一致）。

**可視述語（レビュー Critical の確定）**: 「可視」= **`not dock.isHidden()` を sync 時にポーリング**。**`visibilityChanged` のシグナル引数は判定に使用禁止**（tabify 背面・ウィンドウ最小化で False が来るが dock は非 hidden — 引数導出はタブ裏を「非表示」と嘘表示し、restoreState のフラッピング発火で毎起動誤状態に落ちる。実測済み）。tabify 背面は**展開扱い**（Qt toggleViewAction とパリティ・isHidden 基準で自然に成立）。

| 状態 | 判定 | checked | アイコン |
|---|---|---|---|
| 展開 | `not isHidden()` かつ `objectName not in _collapsed_docks` | True | `dock_panel_{edge}` |
| レール | `objectName in _collapsed_docks` | True | `dock_panel_{edge}_partial` |
| 非表示 | `isHidden()` かつ 非 collapse | False | `dock_panel_{edge}`（unchecked の視覚） |

- **同期**: 単一の `_sync_dock_action(dock)` が上表を再プローブして checked/アイコンを設定（状態は常に導出値 — 並行状態を作らない）。**辺も `main_window.dockWidgetArea(dock)` の再プローブで導出**（実測: フロート中・非表示中も実領域を返し NoDockWidgetArea を返さない — シグナル引数の「直前維持」分岐は不要・並行状態ゼロを貫徹）。トリガ: `visibilityChanged`（**引数は無視し再プローブの合図のみ**）・`_collapse_dock`/`_expand_dock`（**`_collapsed_docks` 変異後＝関数末尾**で呼ぶ — hide()/show() 先行のため変異前だと stale）・`dockLocationChanged`（引数不使用・再プローブの合図のみ）。`topLevelChanged` はトリガに**含めない**（フロートは checked/アイコン不変で観測可能な効果がなく、配線 sabotage を検出できる assert が定義不能 — レビュー指摘によりトリガ一覧から削除）。
- **初期化順序**: action 生成＋sync 配線は **`_restore_state()` より前**（既存 L240 コメントと同じ制約 — restoreState は visibilityChanged をフラッピング発火し最終状態で収束させる必要）・構築完了時に全ドックへ無条件 `_sync_dock_action` を 1 回。
- **クリック挙動**: handler は **`triggered` へ接続（`toggled` 禁止** — toggled はプログラム的 setChecked でも発火し、`_sync_dock_action` の setChecked と handler が無限振動する。計測 IA「triggered のみ」・[[gui_qactiongroup_exclusive_radio_menu]] と同じ確立規約）。checkable QAction は**クリックで checked が自動反転してから handler が走る** — handler は checked 値を無視し、**クリック前の実状態（再プローブ）から遷移を決めて最後に `_sync_dock_action` で上書き**する: 非表示→**`show()`＋`raise_()`**（plain show() は tabify 背面を前面化しない — 実測。既存 `_on_load_error` と同型）／展開→`hide()`／レール→`_expand_dock()`。
- toggleViewAction はどこにも掲載しない（QDockWidget 組込み action 自体は生存 — 既存の「外部 show() 経路」テストは有効なまま）。

### 2.4 B — 診断レベルアイコンの Lucide 化

- `diagnostics_view._rebuild` のレベルセル: `QTableWidgetItem` の setIcon（`icons.icon("diag_error", color=c.error, selected_color=c.chrome_highlight_text)` 等・テキスト空）。**unknown level の fallback は現行どおり "?" テキスト存置**（アイコンなし）。行高は実測で不変（icon 行 sizeHintForRow 19 < defaultSectionSize 30）。
- **カウンタ行**: 単一 QLabel → アイコン QLabel（pixmap 16px 級）＋数値 QLabel の 3 ペア HBox（更新は数値 setText のみ）。行高は QPushButton（~28px）支配で不変。
- **ステータスバー/BusyOverlay の純テキストグリフ（⛔⚠ℹ）は据え置き** — UX-34 は**部分解消**（残余=純テキスト面・将来の通知再設計へ移管）としてカタログへ明記。

### 2.5 C — タブ✕・タイトルバーの統一

- **タイトルバー**: `_float_button` → `setIcon(icons.icon("float_dock"))`・`_close_button` → `setIcon(icons.icon("close"))`。**iconSize は 16px 指定**（icon-only 化で minimumSizeHint が ~22px に落ち 24px 保証がフレーク圏に入るのを回避）・24px 最小ヒット・ツールチップ不変。**tests/realgui/test_hit_targets.py の既存 2 本（float/close）は幾何前提（minimumSizeHint<24 由来の拡張ヒット点導出）の追随を確認**。
- **タブ✕（機構をレビュー実測で確定）**:
  - **`setTabsClosable(False)`＋完全自前ボタン**へ変更（setTabsClosable(True) の既定ボタンは setTabButton 置換後も削除されず _rebuild ごとにタブバーへ隠れ蓄積する実測リークのため、既定ボタン生成自体を止める）。
  - 自前 QToolButton（autoRaise）: `icons.icon("close", color=..., active_color=c.close_hover)` — **hover 赤は QIcon.Mode.Active で実現**（QSS はピクスマップ色を変えられない — 実測）。**hover 色は `close_hover` トークンを消費**（readout ✕ hover と同一役割 — error 直消費は LIGHT で別の赤になり増分0 の役割写像に違反。既存の値分岐テスト体系〔test_theme_qss〕と同様に誤配線ガードを付ける）。
  - **クリック→`tabCloseRequested` は自動発火しない**（既定ボタンのみの内部接続 — 実測）— 自前 clicked を**クリック時 index 解決**（tabBar 上の自ボタン恒等走査・事前 capture 禁止）で `tabCloseRequested.emit` へ接続（既存の tabCloseRequested→remove_tab 配線は不変）。
  - **設置位置は style-hint 解決位置**（`SH_TabBar_CloseButtonPosition` — 実測 RightSide。既存 tests/gui/test_graph_area_tab_ui.py の位置 assert と整合）。
  - **24px 相当の当たり判定**（UX-38 残余の解消 — 視覚サイズは維持・test_hit_targets へタブ✕を追加）。
  - 全タブ生成経路（_rebuild）で設置・「単一タブは close 非表示」の既存規則は自前ボタンの非設置で実現（旧抑制コード setTabButton(0,pos,None) は撤去）。**Layer B に rebuild N 回後のボタン数不変ガード**（蓄積リークの回帰防止）。
  - **追随 grep へ `tabsClosable|tabCloseRequested|tabButton` を追加**（tests/gui/test_graph_area_tab_ui.py:56-93 は toggleViewAction/グリフ grep のどちらにも掛からない — emit 直叩き系は存置・位置/有無 assert は自前ボタン前提へ書換の振り分け）。
- 読み値トグル・「+」等は不変。

### 2.6 変更しないもの

- collapse/expand 機構（増分C）・レール・シェブロン（B4）・QSettings キー・objectName。
- ステータスバー/BusyOverlay/ダイアログ本文の純テキストグリフ（§2.4 の境界）。
- Sync X 導線・読み値トグル。

## 3. テスト戦略（/gui-test-plan 分析）

- **Layer A**:
  - **コントラストヘルパ新設**＋warning/info × {chrome_base, chrome_window} × 両テーマ ≥3:1 の常設テスト（§2.1）。
  - 新トークン × 既存全トークンの**同値総当たりテスト**（同値が出たら値分岐テストへ昇格する構え）。
  - DARK/LIGHT 両 golden への warning/info 追記（LIGHT は明示リストのため**追記漏れが無音** — 必須手順）。
  - icons: 新意味名の全数存在・`color`/`active_color`/`selected_color` の各モード着色（pixmap サンプルピクセル）・currentColor 規約（自動被覆）・**wheel テスト新設**（uv build --wheel → zipfile で SVG 11 個）。
  - 三態写像の純ロジック（(isHidden, collapsed, edge) → (checked, icon 名) の全域表）。
- **Layer B（状態機械テスト — カタログの必須条件・実 MainWindow）**:
  - 基本遷移: show→hide→show・collapse→レール・レールから action クリック→展開・展開からクリック→非表示・非表示からクリック→展開（＋raise_ 確認）
  - **tabify 遷移（レビュー Critical の検出網）**: `tabifyDockWidget` で背面化→**両 action とも展開/checked 維持**・背面 action クリック→hide（パリティ挙動）
  - **最小化**: showMinimized/showNormal で checked 不変
  - **pre-show restoreState**: 非表示保存状態の復元→action unchecked に収束（フラッピング耐性）
  - **起動時 collapse 復元**: dockCollapsed 保存ありで再構築→構築直後（show 前）の action が checked＋partial アイコン（_apply_saved_collapse は show 前 — 増分C で startup-ordering バグ実績のある経路）
  - **_reset_layout**: 実行後に 3 action が展開/checked へ復帰
  - float 往復: setFloating(True)→checked/アイコン不変→再ドックで edge 追随（dockLocationChanged 経由）
  - 辺移動: addDockWidget(Left)→アイコン edge 追随・外部 show()（_on_load_error 相当）→checked 追随・View メニューとツールバーの参照一致
  - タブ✕: 複数タブで**先頭を閉じた後の 2 番目✕クリックが正しいタブを閉じる**（クリック時 index 解決の検証）・rebuild N 回後のボタン数不変・単一タブ非表示規則
  - アイコン名検証は introspection（保持名 — B4 パターン）・cacheKey 恒等比較禁止
- **Layer C（realgui・①ゲート）**:
  - 実機スクショ: ツールバー三態（3 状態を実際に作る）＋ **File/Channel の区別可否（TextBesideIcon）**・診断 3 アイコン＋amber 序列・**選択行上のアイコン視認**（Selected モード）・タブ✕ hover 赤（**実マウス小刻みスイープ** — [[gui_realgui_hover_needs_incremental_move]]）・タイトルバーアイコン
  - **掴み点追随（tests/ 全域・サイト単位）**: `toggleViewAction` grep は **src/＋tests/ 全域**（初版の src/ 限定は誤り）— realgui 2 本（test_shell_chrome_flow.py:70・test_dock_onscreen_after_toggle.py:131 の `widgetForAction(toggleViewAction())` → None 化で赤）はカスタム action への移行・test_shell_chrome.py:55-67 は掲載 assert の書換＋同一 action 検証の意図更新・**test_main_window.py の toggleViewAction trigger は「外部 show() 経路」の意図的使用で存置**。グリフ `✕|❐|⛔|⚠|ℹ` も tests/ 全域（**PR #143 で入ったばかりのカウンタ文言 assert「⛔ 0 / ⚠ 0 / ℹ 0」は計 4 サイト（tests/gui/test_diagnostics_view.py:89/99/102＋tests/realgui/test_diagnostics_clear_realclick.py:195 — realgui 分は CI 外で①ゲートまで潜伏）で確実に壊れる** — 同時追随）。icons の set-lock テスト（tests/gui/test_theme_icons.py:47-56 の set(ICONS) 完全一致）は新意味名追加で必然更新
- **凍結検証**: 全カタログ状態×両テーマの意図的差分（ツールバー〔アイコン＋TextBesideIcon で幅変化〕・診断レベル列/カウンタ・タブ✕・タイトルバー）。**「診断ドック外の差分ゼロ」は diff 画像の目視で確認**（機械照合ツールは viewport crop のみ — 表現を正確化）・プロット viewport crop 一致・ベースライン昇格＋決定性＋DesignSync（icons overview カードに新アイコン自動反映）。

## 4. リスクと対策

| リスク | 対策 |
|---|---|
| 三態と既存状態機械の二重真実・判定揺れ | 述語 = not isHidden() ポーリング固定（シグナル引数禁止）・_sync_dock_action 一本化・集合変異後 sync・初期化順序制約（§2.3） |
| tabify/最小化/restoreState での嘘表示 | §2.3 述語＋§3 Layer B の tabify/最小化/pre-show restore 遷移テスト |
| toggleViewAction 参照の見落とし | **src/＋tests/ 全域 grep**・§3 の 4 ファイル振り分け（移行 3・存置 1）を実装プランに列挙 |
| info/warning の値衝突・AA 未達・選択セル不可視 | 総当たり点検済みの確定値＋コントラストヘルパ常設＋Selected モード着色（§2.1/§2.2） |
| タブ✕の既定ボタンリーク・発火無し・hover 機構 | setTabsClosable(False)＋自前（§2.5 で機構確定）・ボタン数不変ガード・Active モード着色 |
| wheel に新 SVG が入らない | wheel テスト**新設**（既存テストは存在しない — 初版の誤記を訂正） |
| 絵文字→アイコンの掴み点崩壊 | グリフ tests/ 全域 grep（カウンタ文言 assert 3 件は確定破壊 — 同時追随） |
| カウンタ HBox 化のレイアウト変化 | 16px 級・行高は QPushButton 支配で不変（実測）・凍結目視で照合 |

## 5. 実装増分（writing-plans への入力）

単一ブランチ `feature/d3-tristate-icons`・PR 1 本・凍結/①ゲートは末尾 1 回。

1. **基盤**: トークン 2 種＋コントラストヘルパ＋AA/総当たり/golden 追随テスト＋SVG 11 個 vendor＋icons 拡張（color/active_color/selected_color）＋wheel テスト新設。
2. **A 三態トグル**: カスタム QAction（TextBesideIcon）・`_sync_dock_action`（述語・順序・クリック挙動 §2.3 逐語）・2 面置換＋toggleViewAction テスト 4 ファイル振り分け＋Layer B 状態機械テスト全遷移（tabify/最小化/pre-show restore 含む）。
3. **B+C アイコン適用**: 診断テーブル（Selected 込み）/カウンタ HBox・タイトルバー・タブ✕（tabsClosable(False)＋自前・クリック時 index 解決・24px・hover Active）＋グリフ grep 追随＋Layer B（タブ閉じ・ボタン数・ヒット）。
4. **凍結・①ゲート・docs**: realgui フル＋実機スクショ（§3 Layer C の観点全数）・前後比較→昇格→DesignSync・design.md 決定履歴（グリフ置換 defer 解除・三態クリック挙動・tabify パリティ・3:1 基準）・カタログ（**UX-45 解消・UX-38 解消・UX-34 部分解消〔ステータスバー残余は通知再設計へ移管〕・audit-findings-catalog の SH-04 注記を機構変更〔tabsClosable(False)＋自前〕へ更新**）・CLAUDE.md。

## 6. 受け入れ基準

- レール折りたたみ中がトグル上で「非表示」と区別できる・tabify 背面/最小化/再起動復元で嘘表示しない（Qt toggleViewAction パリティ＋レール可視化）・File/Channel ボタンが区別できる・クリック挙動が §2.3 のとおり・2 面常時一致。
- 診断 warning が error/info と区別できる序列（amber・**選択行上でも視認** — 実機）・非テキスト 3:1 を両サーフェス×両テーマで機械検証・絵文字フォント依存ゼロ（レベル列/カウンタ）。
- タブ✕が常駐赤でなく hover 時のみ赤（実マウス）・24px ヒット・正しいタブを閉じる・ボタン蓄積なし・タイトルバー Lucide。
- 状態機械 Layer B 全遷移 green・品質ゲート＋realgui フル＋凍結（目視＋viewport crop＋決定性）＋DesignSync 再同期。
