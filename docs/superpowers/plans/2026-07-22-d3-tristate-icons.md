# 増分D-3「三態トグル＋アイコン統一」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ドックトグルの三態化（UX-45）・診断レベルアイコンの Lucide 化＋warning/info トークン（UX-34 部分）・タブ✕/タイトルバーの統一（UX-34/UX-38 残余）。

**Architecture:** spec §2 の確定設計に逐語で従う — 三態は `not isHidden()` ポーリング＋`_sync_dock_action` 一本化・`triggered` 接続、アイコンは `icon(name, color, active_color, selected_color)` 拡張＋新トークン 2 種（非テキスト 3:1・コントラストヘルパ新設）、タブ✕は `tabsClosable(False)`＋完全自前。

**Tech Stack:** PySide6・pytest(-qt)・realgui・uv build（wheel テスト）。

**Spec:** [docs/superpowers/specs/2026-07-22-d3-tristate-icons-design.md](../specs/2026-07-22-d3-tristate-icons-design.md) — **§2 の設計要素は敵対的レビュー（32＋8 指摘・全て Qt 実測）で確定済み。一つも省けない**（各要素は「無いと壊れる」実測根拠つき）。

## Global Constraints

- 三態述語 = `not dock.isHidden()` ポーリング（visibilityChanged/dockLocationChanged のシグナル引数は判定使用禁止）・辺も `dockWidgetArea()` 再プローブ・sync は `_collapsed_docks` 変異後・action 生成＋配線は `_restore_state()` より前・handler は **triggered 接続（toggled 禁止）**。
- 新トークン: warning DARK #fab387 / LIGHT #b0741a・info DARK #7aa2f7 / LIGHT #1a5fb4（AA テストが 3:1 未達を検出したら暗色方向のみ微調整可）。
- タブ✕ hover は **close_hover トークン**（error 直消費禁止 — LIGHT で別の赤）。
- タブ✕クリックは**クリック時 index 解決**（事前 capture 禁止）・設置位置は SH_TabBar_CloseButtonPosition 解決位置。
- 追随 grep（tests/ 全域・サイト単位・機械一括置換禁止）: `toggleViewAction`・`✕|❐|⛔|⚠|ℹ`・`tabsClosable|tabCloseRequested|tabButton`。
- 品質ゲート各タスク末: uv run pytest -q・ruff check・ruff format・mypy src/（同期実行）。realgui は作成分 scoped＋Task 4 フル。
- コミット末尾: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## Task 1: 基盤 — トークン・コントラストヘルパ・SVG・icons 拡張・wheel テスト

**Files:**
- Modify: `src/valisync/gui/theme/tokens.py`（warning/info 2 トークン・DARK/LIGHT 両方）・`src/valisync/gui/theme/icons.py`（ICONS 11 追加・icon() 拡張）
- Create: `src/valisync/gui/theme/icons/lucide/` へ SVG 11 個（circle-x・triangle-alert・info・x・copy・panel-left・panel-left-close・panel-right・panel-right-close・panel-bottom・panel-bottom-close — 既存と同一 pin 版 unpkg・無改変）
- Test: `tests/gui/test_theme_tokens.py`（golden 2 面＋コントラスト＋総当たり）・`tests/gui/test_theme_icons.py`（set-lock 更新・着色モード）・新規 `tests/test_wheel_packaging.py`

**Interfaces:**
- Produces: `tokens.Colors.warning`/`.info`（両テーマ）・`icons.icon(name, color=None, active_color=None, selected_color=None)`・意味名 `diag_error/diag_warning/diag_info/close/float_dock/dock_panel_{left,right,bottom}{,_partial}`・テストヘルパ `contrast_ratio(c1: Color, c2: Color) -> float`（WCAG 相対輝度 — tests 側ヘルパ）。

- [ ] **Step 1（トークン TDD）**: コントラストヘルパ（純関数）を tests ヘルパとして新設し、`warning/info × {chrome_base, chrome_window} × 両テーマ ≥ 3.0` の常設テスト → RED → tokens 追加 → GREEN。**同値総当たりテスト**（新 2 トークン × 既存全トークン・両テーマ — 同値ゼロを assert）。DARK golden（fields 全反復 — RED→更新）＋ **LIGHT golden へ明示追記**（リスト反復のため追記漏れは無音 — spec §2.1）。
- [ ] **Step 2（SVG vendor）**: 既存 lucide/ の pin 版と同一ソースから 11 個取得・無改変配置。currentColor 規約テスト（glob 自動被覆）green を確認。
- [ ] **Step 3（icons 拡張 TDD）**: `icon()` の color/active_color/selected_color — 各モード（Normal/Active/Selected）の pixmap サンプルピクセルが指定色になるテスト → 実装（既存 Normal/Disabled ループへモード追加・None 時は現行互換）。ICONS へ意味名 11+（set-lock テスト tests/gui/test_theme_icons.py:47-56 を同時更新）。
- [ ] **Step 4（wheel テスト新設）**: `uv build --wheel` → zipfile で新規 SVG 11 個＋既存 4 個の同梱を assert（増分5 の editable-install false-green の恒久防波堤。ビルド時間が問題なら `@pytest.mark.slow` 等の既存慣行に従う — なければ素で常設）。
- [ ] **Step 5**: ゲート → commit `feat(theme): warning/info トークン (3:1 検証つき)＋Lucide 11 SVG＋icon() モード着色拡張＋wheel テスト (D-3 Task1)`

---

## Task 2: A — ドックトグルの三態化

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（カスタム QAction 生成・_sync_dock_action・2 面置換・TextBesideIcon）
- Test: `tests/gui/test_main_window.py` 系（状態機械 Layer B 新設）・toggleViewAction 4 ファイル振り分け（下記）

**Interfaces:**
- Consumes: Task 1 の `dock_panel_*` 意味名。
- Produces: `MainWindow._dock_actions: dict[str, QAction]`（objectName キー — テスト掴み点）・`_sync_dock_action(dock)`。

- [ ] **Step 1（写像純ロジック TDD）**: `(is_hidden: bool, collapsed: bool, edge) → (checked, icon 名)` の全域表テスト（3 状態 × 3 辺）→ 実装（純関数 — main_window 内 or 分離）。
- [ ] **Step 2（QAction＋sync）**: spec §2.3 逐語 — カスタム checkable QAction（text=strings.DOCK_*・2 面共有）・`_sync_dock_action`（isHidden/collapsed/dockWidgetArea 再プローブ・トリガ 3 種接続・変異後呼出・生成＋配線を `_restore_state()` より前・構築完了時に無条件 sync×3）・triggered handler（checked 無視・再プローブ遷移: 非表示→show()+raise_()／展開→hide()／レール→_expand_dock()）・ツールバー 3 ボタンのみ `ToolButtonTextBesideIcon`。toggleViewAction は 2 面から撤去。
- [ ] **Step 3（Layer B 状態機械 — spec §3 の全遷移逐語）**: 基本 5 遷移・**tabify（背面化→両 action 展開/checked 維持・背面クリック→hide）**・**showMinimized/showNormal で不変**・**pre-show restoreState（非表示保存→unchecked 収束）**・**起動時 collapse 復元（dockCollapsed 保存→構築直後 checked＋partial）**・**_reset_layout 後 3 action 展開復帰**・float 往復（不変→再ドックで edge 追随）・辺移動（addDockWidget(Left)→アイコン追随）・外部 show()→checked 追随・2 面参照一致。アイコン検証は保持名 introspection。
- [ ] **Step 4（toggleViewAction 振り分け — spec §3 逐語）**: tests/realgui/test_shell_chrome_flow.py:70・test_dock_onscreen_after_toggle.py:131 → `_dock_actions` 経由の widgetForAction へ移行／tests/gui/test_shell_chrome.py:55-67 → 掲載 assert をカスタム action へ書換（同一 action 検証の意図更新）／tests/gui/test_main_window.py の trigger 系 → **外部 show() 経路として存置**。
- [ ] **Step 5**: ゲート → commit `feat(gui): ドックトグルを三態カスタム QAction 化 (isHidden ポーリング・tabify パリティ) (D-3 Task2/UX-45)`

---

## Task 3: B＋C — 診断アイコン・カウンタ・タイトルバー・タブ✕

**Files:**
- Modify: `src/valisync/gui/views/diagnostics_view.py`（レベルセル setIcon・カウンタ HBox）・`collapsible_dock_title_bar.py`（✕/❐ アイコン化・iconSize 16）・`graph_area_view.py`（tabsClosable(False)＋自前✕）
- Test: 追随（下記 grep）＋Layer B 新設

- [ ] **Step 1（診断）**: レベルセル `icons.icon("diag_*", color=c.{error,warning,info}, selected_color=c.chrome_highlight_text)`・unknown level は "?" テキスト存置。カウンタを 3 ペア HBox（アイコン 16px pixmap＋数値ラベル）。**グリフ追随 4 サイト**: tests/gui/test_diagnostics_view.py:89/99/102＋tests/realgui/test_diagnostics_clear_realclick.py:195（数値部の assert へ書換 — アイコンは pixmap 化で文言から消える）。
- [ ] **Step 2（タイトルバー）**: ✕/❐ → icon("close")/icon("float_dock")・iconSize 16px・24px ヒット維持。test_hit_targets.py 既存 2 本の幾何前提（minimumSizeHint<24 由来の導出）を確認・追随。
- [ ] **Step 3（タブ✕）**: spec §2.5 逐語 — setTabsClosable(False)・自前 QToolButton（autoRaise・icon("close", color=..., active_color=c.close_hover)・24px ヒット・SH_TabBar_CloseButtonPosition 位置）・クリック時 index 解決→tabCloseRequested.emit・単一タブ非設置（旧 setTabButton(0,pos,None) 撤去）・_rebuild 設置。**close_hover 誤配線ガード**（error と値分岐するテーマで active pixmap が close_hover 側 — test_theme_qss の既存パターン）。
- [ ] **Step 4（Layer B）**: 複数タブで先頭を閉じた後の 2 番目✕クリックが正しいタブを閉じる・rebuild N 回後のボタン数不変・単一タブ非表示規則・選択セル上の診断アイコンが Selected モード色。**grep 追随**: `tabsClosable|tabCloseRequested|tabButton`（tests/gui/test_graph_area_tab_ui.py:56-93 — emit 直叩き系は存置・位置/有無 assert は自前ボタン前提へ書換）＋`✕|❐`。
- [ ] **Step 5**: ゲート → commit `feat(gui): 診断/タイトルバー/タブ✕のアイコン統一 (Selected/Active モード・close_hover・24px) (D-3 Task3/UX-34,38)`

---

## Task 4: 凍結・①ゲート・docs

- [x] **Step 1**: realgui フル（4 バッチ可）＋新規実機確認: ツールバー三態（3 状態を実際に作る）・File/Channel 区別・診断 3 アイコン＋amber 序列・**選択行上の視認**・**タブ✕ hover 赤（実マウス小刻みスイープ）**・タイトルバー。証拠スクショ保存。— 4バッチ 95/95 pass。実機発見: float/close/タブ✕ の icon-only 化で自然高さが chevron 同型の 24px 境界に達し既存拡張ヒット式が境界外に落ちる実バグを `tests/realgui/test_hit_targets.py` の共有ヘルパ修正で解消（old_h の具体値 assert は環境依存〔51ファイル一括実行のみ 23px 観測〕のため削除し実クリック効果検証へ）。51ファイル一括実行のみで再現し D-3 と無関係と確認した既存2件のフレーク（chevron 測定・expansion dialog wheel）はスコープ外記録のみ。証拠は `design_export/evidence_d3/`。
- [x] **Step 2**: 凍結前後比較（両テーマ）— 想定差分: ツールバー（アイコン＋TextBesideIcon 幅変化）・診断レベル列/カウンタ・タブ✕・タイトルバー。**診断ドック外の非想定差分ゼロは diff 目視**・プロット viewport crop 機械一致 → 昇格 → 決定性 exit 0。— 両テーマとも診断ドック外/プロット面の非想定差分ゼロを diff 目視確認・`--crop-meta` 完全一致・昇格後決定性 exit 0 実証済み。
- [x] **Step 3**: docs — design.md 決定履歴（グリフ置換 defer 解除・三態クリック挙動/triggered/tabify パリティ・3:1 基準・close_hover 消費）／カタログ: **UX-45 解消・UX-38 解消・UX-34 部分解消（ステータスバー残余は通知再設計へ移管）・audit-findings-catalog の SH-04 注記更新**／CLAUDE.md 行。— 全て反映済み（float_dock=copy グリフの可読性は DONE_WITH_CONCERNS として design.md に記録）。
- [x] **Step 4**: 最終ゲート → commit → PR（DesignSync はマージ後コントローラ）。

## Self-Review 済み確認事項

- spec §2 の全設計要素がタスクステップに 1:1 で現れる（述語/順序/triggered/close_hover/Selected/Active/index 解決/tabsClosable(False)/iconSize/3:1 ヘルパ/wheel/golden 2 面）。
- 追随対象の全数（toggleViewAction 4 ファイル・グリフ 4 サイト・タブ UI 1 ファイル・hit_targets 2 本）はレビュー実測の行番号で列挙済み。
- 型整合: `_dock_actions`/`_sync_dock_action`/`icon()` 拡張/`contrast_ratio` を Interfaces に明記。
