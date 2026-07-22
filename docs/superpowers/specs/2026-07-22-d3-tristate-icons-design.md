# 増分D-3「三態トグル＋アイコン統一」設計（UX-34/45・カタログ推奨4 第3層）

- **出典**: UIUX 敵対的レビューカタログ推奨4 の第3層。ユーザー承認済みモックアップ（2026-07-22・A 三態トグル/B 診断アイコン Lucide 化＋amber 序列/C タブ✕・タイトルバー統一）が要件の一次表現。
- **スコープ調整（記録済み）**: シェブロン辺解決（旧 D-3 案の一部）は PR #143 で先行完了。「Sync X を View メニューへ追加」（旧 UX-32 案）は計測 IA v3 決定で supersede 済み — 含めない。**絵文字グリフ置換の defer（増分5 で記録）は本増分で解除**（ユーザーの D-3 着手承認がその解除に当たる — docs/design.md 決定履歴へ記録）。
- **前提基盤**: `theme/icons.py`（意味名レジストリ・currentColor 規約・HiDPI・pyproject package-data）・B4 の辺解決パターン（`dockLocationChanged` 追随）・増分C の collapse 状態機械（`_collapsed_docks`・`_collapse_dock`/`_expand_dock`・visibilityChanged 委譲）。

## 1. 修正一覧と対象カタログ行

| # | カタログ | 内容 |
|---|---|---|
| A | UX-45（＋UX-32 の三態部分） | ドックトグルの三態化 — 現状 toggleViewAction はレール折りたたみ中を「非表示」と同見た目にする嘘の 2 態。カスタム QAction で 展開/レール/非表示 を正直に表示＋panel 系アイコンでツールバー様式統一 |
| B | UX-34（核心） | 診断レベルアイコンの Lucide 化（circle-x/triangle-alert/info）＋ **warning/info トークン新設**で error > warning > info の視覚序列回復・絵文字フォント依存の描画揺れ解消 |
| C | UX-34（タブ✕/タイトルバー） | タブ閉じる✕の常駐赤排除（ニュートラル＋hover 赤）・タイトルバー ✕/❐ の Lucide 化 |

## 2. 設計

### 2.1 新規トークン（`theme/tokens.py`）

| トークン | DARK | LIGHT | 用途 |
|---|---|---|---|
| `warning` | `#fab387`（Catppuccin peach） | `#df8e1d`（Latte yellow 系 — **AA 実測で確定**・不足なら darken） | 診断 warning の意味色。error（#f38ba8/#c0392b）との序列: error > warning |
| `info` | `#89b4fa`（Catppuccin blue） | `#1e66f5`（Latte blue — AA 実測） | 診断 info の意味色 |

- **値衝突の点検**: `warning` DARK #fab387 は `accent_active`（#f59e0b）・signal_palette[1]（#E69F00）と**別値**（意味分離維持）。同値衝突が生じた場合は値分岐テスト必須（既存規約）。LIGHT 値はサーフェス上 AA 実測（増分0 の手順）で確定し spec 追記でなく実装テストに埋める。
- エクスポート（tokens.css/json・カード）へ自動反映 — DesignSync 再同期は増分末尾。

### 2.2 icons レジストリ拡張（`theme/icons.py`）

- **新規 vendored Lucide SVG（11 個・既存と同一 pin 版・無改変・ISC は LICENSES.md 記載済み）**: `circle-x`・`triangle-alert`・`info`・`x`・`copy`・`panel-left`・`panel-left-close`・`panel-right`・`panel-right-close`・`panel-bottom`・`panel-bottom-close`。
- **意味名追加**: `diag_error`/`diag_warning`/`diag_info`・`close`（x）・`float_dock`（copy）・`dock_panel_{left,right,bottom}`・`dock_panel_{left,right,bottom}_partial`（-close 変種）。
- **`icon(name, color=None)` へ拡張**: `color: Color | None` — None は現行どおり Normal=chrome_text/Disabled=chrome_disabled_text。指定時は Normal=指定色（Disabled は同色 — 診断アイコンに Disabled 用途なし）。既存呼出は無変更で互換。
- SVG currentColor 規約テストは glob で新規ファイルを自動被覆（既存 `test_theme_icons.py`）。**pyproject package-data 経路は既存の wheel テストが担保**（増分5 の false-green 教訓 — 新規 SVG が wheel に入ることを確認）。

### 2.3 A — ドックトグルの三態化

**構造**: `toggleViewAction()` の掲載（View メニュー L281-283・ツールバー L345-347 の計 2 面×3 ドック）を、MainWindow が作る**カスタム checkable QAction（ドックごとに 1 個・2 面共有）**へ置換する。text は `strings.DOCK_*` 定数（ニーモニクス非付与 — G-46 の既存決定どおり）。

**状態機械**（増分C の集約状態機械へ相乗り — 新規の並行状態を作らない）:

| 状態 | 判定 | checked | アイコン |
|---|---|---|---|
| 展開 | dock 可視 かつ `objectName not in _collapsed_docks` | True | `dock_panel_{edge}` |
| レール | `objectName in _collapsed_docks` | True（一部見えている） | `dock_panel_{edge}_partial` |
| 非表示 | dock 非可視 かつ 非 collapse | False | `dock_panel_{edge}`（unchecked の視覚で区別） |

- **辺解決**: アイコンの `{edge}` は `dockWidgetArea(dock)` から解決し `dockLocationChanged` で追随（B4 と同型・Left/Right/Bottom。フロート中＝NoDockWidgetArea は直前維持）。フロートは「展開」扱い（可視・非 collapse）。
- **更新トリガ**: `visibilityChanged`・`_collapse_dock`/`_expand_dock`（状態機械の遷移点）・`dockLocationChanged`・`topLevelChanged`（フロート往復）。単一の `_sync_dock_action(dock)` に集約。
- **クリック挙動**: 非表示→展開（show — 既存 visibilityChanged 委譲で collapse 済みなら `_expand_dock` が走る）／展開→非表示（hide）／**レール→展開**（`_expand_dock` — 「見せて」の意図に一致・隠すには展開後にもう一度）。
- **既存経路との整合**: `_on_load_error` の `diagnostics_dock.show()` 等の外部 show()/hide() は visibilityChanged→`_sync_dock_action` で追随（アクション状態は常に導出値 — 二重真実を作らない）。View メニュー側も同一 QAction のため常時一致。
- toggleViewAction はどこにも掲載しない（windowTitle 由来 text の制約からも解放）。

### 2.4 B — 診断レベルアイコンの Lucide 化

- `diagnostics_view._rebuild` のレベルセル: 絵文字テキスト `_LEVEL_ICON` を **`QTableWidgetItem` の setIcon**（`icons.icon("diag_error", c.error)` 等・テキストは空）へ置換。列幅は ResizeToContents のまま。
- **カウンタ行**: 単一 QLabel「⛔ n / ⚠ n / ℹ n」→ アイコン QLabel（pixmap）＋数値 QLabel の 3 ペア HBox（既存の counts 更新経路は数値 setText のみに）。
- **ステータスバー誘導文・BusyOverlay 等の純テキスト内グリフ（⛔⚠ℹ）は据え置き**（文言テンプレート内の文字であり、ウィジェット化されていない面。将来の通知再設計まで — スコープ境界として記録）。タイトルバー ✕/❐ は C で置換。
- 診断の realgui/凍結への影響: レベル列の見た目変化（全カタログ状態）— 想定差分。

### 2.5 C — タブ✕・タイトルバーの統一

- **タイトルバー**（collapsible_dock_title_bar.py）: `_float_button.setText("❐")` → `setIcon(icons.icon("float_dock"))`・`_close_button.setText("✕")` → `setIcon(icons.icon("close"))`。24px 最小ヒット（UX-38）維持・ツールチップ不変。
- **タブ✕**: QTabWidget の既定 close ボタン（スタイル供給・常駐赤）を `setTabButton(側, QToolButton)` で置換 — `icons.icon("close")`＋QSS `:hover` で error 色強調（qss.py へ断片・トークンは既存 error 消費）。**全タブ生成経路**（_rebuild・タブ追加）で設置し、既存の「単一タブは close 非表示」（graph_area_view:327-335 の setTabButton(0, pos, None)）と共存。クリックで従来の tabCloseRequested 経路を発火（挙動不変）。
- 読み値トグル・「+」ボタン等は不変。

### 2.6 変更しないもの

- ドックの collapse/expand 機構そのもの（増分C）・レール・シェブロン（B4 済み）・QSettings キー（dockCollapsed 等）・objectName。
- ステータスバー/BusyOverlay/確認ダイアログ本文の純テキストグリフ（§2.4 の境界）。
- Sync X の導線（右クリックのみ — v3 決定）・読み値トグル。

## 3. テスト戦略（/gui-test-plan 分析）

- **Layer A**:
  - 新トークンの AA 実測（LIGHT warning/info vs 表示サーフェス — 増分0 の検証手順）・値衝突点検（同値が生じた場合のみ値分岐テスト）。
  - icons: 新意味名の全数存在・`icon(name, color)` の着色（pixmap サンプルピクセルが指定色）・currentColor 規約（既存 glob が自動被覆）。
  - **三態写像の純ロジック**: (可視, collapsed, edge) → (checked, icon 名) の全域表（3 状態 × 3 辺）。
- **Layer B（状態機械テスト — カタログの必須条件）**: 実 MainWindow で全遷移を駆動し action の checked/アイコン名を assert:
  - show→hide→show・collapse（タイトルバーシェブロン）→レール状態・レールから action クリック→展開・展開から action クリック→非表示・非表示から action クリック→展開
  - **float 往復**（setFloating(True)→展開扱い維持→再ドック）・**辺移動**（addDockWidget(Left)→アイコン edge 追随）・外部 show()（_on_load_error 相当）→checked 追随
  - View メニューとツールバーが同一 QAction（参照一致）
  - タブ✕: ニュートラルアイコン設置・クリックで tabCloseRequested 発火（挙動不変）・単一タブ非表示の既存規則共存
  - アイコン名の検証は **introspection**（設定した意味名の保持 — B4 の `chevron_icon_name()` パターン）で行い cacheKey 恒等比較はしない
- **Layer C（realgui・①ゲート）**:
  - 実機スクショ: ツールバー三態（展開/レール/非表示を実際に作って 3 態の見た目差）・診断テーブルの 3 アイコン＋amber 序列・タブ✕ hover 赤（実マウス hover — [[gui_realgui_hover_needs_incremental_move]]）・タイトルバーアイコン
  - 既存 realgui 掴み点の追随: `_toggle_button`/`_float_button`/`_close_button` は属性参照で非依存（実査済み）だが、**text() で ✕/❐ を参照するテストを tests/ 全域 grep** し追随
- **凍結検証**: ツールバー・診断レベル列/カウンタ・タブ바・タイトルバーの意図的差分（全カタログ状態×両テーマ）。プロット viewport crop 一致。ベースライン昇格＋DesignSync（icons overview カードへ新アイコン追加 — export の icons カードは自動反映）＋決定性 exit 0。

## 4. リスクと対策

| リスク | 対策 |
|---|---|
| 三態と既存 collapse 状態機械の二重真実 | action 状態は常に導出値（`_sync_dock_action` 一本化）・既存の visibilityChanged 委譲（L895-905）へ相乗りし新規の並行状態を作らない |
| toggleViewAction 廃止の見落とし経路（View メニュー/ツールバー以外の参照） | `toggleViewAction` を src/ 全域 grep し全数置換・Layer B で外部 show() 追随を検証 |
| 絵文字→アイコンでの realgui/テスト掴み点崩壊 | `✕\|❐\|⛔\|⚠\|ℹ` を tests/ 全域 grep（文言 OS の三本立てプロトコル準拠・机上でなくサイト単位確認） |
| wheel に新 SVG が入らない（増分5 の実証済み罠） | 既存の package-data テストが glob 被覆であることを確認・なければ新規 SVG を含む実 wheel テスト |
| LIGHT の warning/info が AA 未達 | 実測で値確定（darken 調整可）・確定値は tokens に埋め AA テスト常設 |
| タブ✕置換で closable 既定ボタンとの二重表示 | setTabButton は既定ボタンを置換する（Qt 仕様）— 単一タブ非表示規則との共存を Layer B で確認 |
| カウンタ行の HBox 化で診断ドックの高さ/凍結が想定外変化 | アイコンサイズを現行グリフ相当（16px 級）に・凍結比較で診断ドック内差分のみを照合 |

## 5. 実装増分（writing-plans への入力）

単一ブランチ `feature/d3-tristate-icons`・PR 1 本・凍結/①ゲートは末尾 1 回。

1. **基盤**: トークン 2 種（AA 実測込み）＋SVG 11 個 vendor＋icons 意味名/`color` 引数＋Layer A（写像・着色・規約・wheel）。
2. **A 三態トグル**: カスタム QAction・`_sync_dock_action`・クリック配線・2 面置換＋Layer B 状態機械テスト全遷移。
3. **B+C アイコン適用**: 診断テーブル/カウンタ・タイトルバー・タブ✕（hover 赤 QSS）＋掴み点 grep 追随＋Layer B。
4. **凍結・①ゲート・docs**: realgui フル＋実機スクショ・前後比較→昇格→DesignSync・design.md 決定履歴（グリフ置換 defer 解除・三態クリック挙動）・カタログ解消マーク（UX-34・UX-45・UX-32 残余の扱い）・CLAUDE.md。

## 6. 受け入れ基準

- レール折りたたみ中のドックがトグル上で「非表示」と区別できる（三態の実機視認）・クリック挙動が §2.3 のとおり・View メニューとツールバーが常時一致。
- 診断の warning が error/info と明確に区別できる序列（amber・実機視認）・絵文字フォント依存ゼロ（レベル列/カウンタ）。
- タブ✕が常駐赤でなく hover 時のみ強調・タイトルバー ✕/❐ が Lucide。
- 状態機械 Layer B 全遷移 green・品質ゲート＋realgui フル＋凍結（想定差分照合・viewport crop 一致・決定性）＋DesignSync 再同期。
