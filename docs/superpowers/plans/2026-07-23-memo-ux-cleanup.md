# 雑メモ解消（ドック/メニュー UX）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** #14 チャンネルブラウザのヘッダーからファイル名を廃止し最小幅を下げる／#15 右クリックに「信号プロパティを表示」／#17 折りたたみレールを画面端（開ドックの外側）へ。

**Architecture:** [spec](../specs/2026-07-23-memo-ux-cleanup-design.md) §1-§7 に逐語で従う。#14/#15 は局所改修。#17 は**候補 A（レール最外ドック化）**でレールを QMainWindow の最外ドックへ移し、ガードレール（非移動/非クローズ・D&D 最外再アサート・restoreState 再適用・空時ゼロ幅）で最外不変を保つ。機構はスパイク（realgui 実機実証）で確定してから実装する。

**Tech Stack:** PySide6・pyqtgraph・pytest(-qt)・realgui。

**Spec:** [docs/superpowers/specs/2026-07-23-memo-ux-cleanup-design.md](../specs/2026-07-23-memo-ux-cleanup-design.md) — **6 レンズ敵対的レビュー 19 confirmed（I1＋Minor 9）反映済み**。

## Global Constraints

- **#14**: `header_text()` からファイル名プレフィックス除去（件数のみ）・未選択分岐も strings.py 化・`header_label.setWordWrap(True)`。最小幅の床はタイトルバー ~181px（それ以上の縮小は follow-up・スコープ外）。
- **#15**: 右クリック項目は**位置ベース**（`indexAt(pos)` の hit leaf）でダブルクリックと同型。選択ベース（`selected_signal_keys`）は使わない。右クリック位置が leaf のときのみ有効。
- **#17 機構 = 候補 A のみ**（レール最外ドック化）。候補 B/C は不採用（B は緩和版でユーザー再承認時のみ）。ガードレール: レールドックは非移動/非クローズ/非フロート・objectName 安定＋saveState 互換・`dockLocationChanged` で最外順序を能動是正・restoreState 後に順序/`setCorner`/1:4 再適用・空時ゼロ幅隠蔽。
- **#17 プロット幅**: 縦積みゆえ片方折りたたみでプロット幅不変（レール x のみ移動）・両方で全幅。既存 `central.width` reclaim assert は単独折りたたみで無効→レール矩形 x 比較へ置換。
- 文言は strings.py 集約（D-1 表記規約 R-01..13）＋対訳表更新。恒真テストなし。
- 品質ゲート各タスク末: `uv run pytest -q`・`uv run ruff check`・`uv run ruff format`・`uv run mypy src/`（同期実行）。
- コミット末尾: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## Task 1: #14 ヘッダーのファイル名廃止＋最小幅

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`（`header_text` からファイル名除去・未選択分岐 strings 化・docstring 更新）
- Modify: `src/valisync/gui/views/channel_browser_view.py`（`header_label.setWordWrap(True)`）
- Modify: `src/valisync/gui/strings.py`（`CHANNEL_HEADER_COUNT_TMPL`/`CHANNEL_HEADER_EMPTY_TMPL` 改訂・`CHANNEL_HEADER_NO_FILE` 新設）
- Test: `tests/gui/test_channel_browser_vm*.py`・`tests/gui/test_channel_browser_view*.py`

- [ ] **Step 1（TDD）**: `header_text()` が (a) 通常でファイル名を含まず「{total} 信号中 {shown} 件を表示」(b) 空で「0 信号」(c) 未選択で `S.CHANNEL_HEADER_NO_FILE`（strings 経由）を返すテスト。
- [ ] **Step 2（RED）**: FAIL（現状ファイル名込み・未選択直書き）。
- [ ] **Step 3（実装）**: `strings.py` の該当テンプレからファイル名除去・`CHANNEL_HEADER_NO_FILE` 追加。`header_text()` を改訂（未選択も strings 経由）・docstring「which file, how many shown」を更新。`channel_browser_view.py` の `header_label` に `setWordWrap(True)`。対訳表（docs/design.md 表記規約）該当行更新。
- [ ] **Step 4（GREEN）**: Step 1 PASS。
- [ ] **Step 5（最小幅 Layer B）**: `channel_dock.minimumSizeHint().width()` がファイル名込み想定より小さい方向（相対比較・絶対 px 非依存・床はタイトルバー ~181px をコメント明記）。word-wrap でヘッダーが2行化してレイアウト破綻しないこと。
- [ ] **Step 6（ゲート＋commit）**: green → `feat(gui): チャンネルブラウザ ヘッダーのファイル名廃止＋最小幅縮小 (#14)`

---

## Task 2: #15 右クリックに「信号プロパティを表示」（位置ベース）

**Files:**
- Modify: `src/valisync/gui/views/channel_browser_view.py`（`build_context_menu`/`_show_context_menu` に位置ベースのプレビュー項目）
- Modify: `src/valisync/gui/strings.py`（`ACTION_SHOW_SIGNAL_PROPERTIES`）
- Test: `tests/gui/test_channel_browser_view*.py`

- [ ] **Step 1（TDD）**: leaf 位置で右クリック→「信号プロパティを表示」有効・triggered で `preview_requested` が**その位置の行のキー**で発火（signal spy）。parent 位置/空白で無効（非表示 or disabled）。
- [ ] **Step 2（RED）**: FAIL（項目未実装）。
- [ ] **Step 3（実装）**: `build_context_menu` を `pos`（または hit index）を受ける形にし、`indexAt(pos)` の `model.signal_key_at` が leaf キーのとき「信号プロパティを表示」を追加。`triggered` で `self.preview_requested.emit(hit_key)`（ダブルクリック `_emit_preview` と同型）。`_show_context_menu` から pos を渡す配線。`strings.py` へ `ACTION_SHOW_SIGNAL_PROPERTIES`。「アクティブパネルへ追加」は無回帰維持。
- [ ] **Step 4（GREEN＋sabotage）**: Step 1 PASS。**sabotage 2 種を実証**: (1) `selected_signal_keys()` 選択ベース実装 → 別行選択中に非選択 leaf を右クリックで既存選択行がプレビューされ RED。(2) parent+leaf 同時選択で有効化する実装 → RED。改変を戻して GREEN。
- [ ] **Step 5（ゲート＋commit）**: green → `feat(gui): チャンネルブラウザ右クリックに「信号プロパティを表示」(#15)`

---

## Task 3: #17 折りたたみレールを画面端へ（候補 A・スパイク→実装）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（`_collapse_dock`/`_expand_dock`・レールドック生成/配線・ガードレール）
- Modify（機構次第）: `src/valisync/gui/views/central_with_rails.py`・`src/valisync/gui/views/dock_collapse_rail.py`
- Test: `tests/realgui/test_collapsible_docks_realclick.py`（既存移行）＋新規 realgui

**Interfaces:**
- Consumes: 既存 `DockCollapseRail`・`_collapsed`（dockCollapsed 永続）・`_apply_dock_corners`・`_apply_default_dock_ratio`。

- [x] **Step 1（スパイク — 候補 A の実現可能性を realgui 実機実証）**: **GREEN で確定**（BLOCKED でない）。実機スパイクで機構を確定: Right/Bottom は `addDockWidget(area, rail, orientation)` の append が「最外の全高/全幅ドック」を作る（既存 File/Channel カラムがあっても append 先は最外）。Left は append が内側着地のため rail-first の rebuild で最外化。片方折りたたみで `rail.left(1112) >= channel.right(1107)`（gap=5・非重なり）を矩形実測＋スクショで確認。
- [x] **Step 2（honest-RED）**: 現状（レールが中央側 col2）で `rail.left(850) >= channel.right(1139)` が **False（gap=-289）= RED** を機構変更前に実証。
- [x] **Step 3（実装 — 候補 A＋ガードレール）**: レール最外ドック化を本実装（`CentralWithRails` 廃止・`central_with_rails.py` 削除）。ガードレール全て:
  - レールドック `setFeatures(NoDockWidgetFeatures)`＋`setTitleBarWidget(QWidget())`（薄い見た目）＋`setAllowedAreas(自辺)`。
  - `objectName` 安定（`collapse_rail_{left,right,bottom}`）＋`saveState`/`restoreState` 互換（旧 blob 復元後に正規化）。
  - `dockLocationChanged`→`_reassert_rails_after_move`→singleShot `_reassert_rail_now`→`_place_rail_outermost`（removeDockWidget＋再配置・可視保持）で最外順序を能動是正。
  - `restoreState`/`_reset_layout` 後に `_normalize_rail_placement`（順序＋可視）＋`_apply_dock_corners`＋`_apply_default_dock_ratio`（reset 経路）を再適用。show 後の pre-show 罠は `_reconcile_rails_after_show` で是正。
  - 空時 `rail_dock.setVisible(False)`（ゼロ幅）。
- [x] **Step 4（Layer C — T-C1/T-C1b/T-C2）**: 新規 realgui 7 本 pass（実機スクショ＋矩形実測）:
  - T-C1: 片方折りたたみで `rail.left() >= openDock.right()`（gap=5）・`widgetAt(レール中心)` がレール・File/Channel 両対称。
  - T-C1b: 順序破れ（`splitDockWidget(rail, channel, H)` が実 `dockLocationChanged` 発火）→最外再アサート。save→restore 後にレール最外復元。
  - T-C2: 両方折りたたみでレール画面端＋プロット全幅化・全展開レールゼロ幅・extent 復元（許容=レール実測幅+14px＝レールがドックとしてカラム幅を奪う分を吸収）。
- [x] **Step 5（既存テスト移行）**: `central.width` reclaim assert を `centralWidget().width()`＋レール矩形 x 比較へ置換・`_central_with_rails`/`_collapse_rails[area]`/`rail._tabs`/`_rail_docks` 直参照を機構へ移行。`test_main_window_central.py` の central 判定も `centralWidget() is central_stack` へ戻す。既存 collapse 系全数無回帰（gui 105・full 1734 pass）。
- [x] **Step 6（ゲート＋commit）**: green → `feat(gui): 折りたたみレールを画面端(開ドックの外側)へ — レール最外ドック化 (#17)`

---

## Task 4: realgui フル＋凍結カタログ＋docs＋最終ゲート

**Files:**
- Modify: `scripts/capture_ui_screenshots.py`（#14 ヘッダー差分・#17 の 10_collapse_one 追加判断）
- Modify: `docs/design.md`・`CLAUDE.md`
- Verify: `design_export/screenshots_catalog_{dark,light}`

- [x] **Step 1（realgui フル）**: `uv run pytest tests/realgui/ --realgui -q`（timeout 600000・バッチ可）。既知フレークは単体で切り分け。**101 passed, 3 failed（フル一括実行）→ 3件とも単体では pass**（`test_hit_targets.py::test_chevron_already_meets_24px_height`・`test_hit_targets.py::test_tab_close_button_extended_hit_removes_tab`・`test_expansion_dialog_realinput.py::test_bottom_checkbox_reachable_by_real_wheel_then_ok` — D-3/E-0+E-2/F-0 で既に記録済みの「51ファイル一括実行でのみ発生する実行順依存フォント計量ドリフト」クラスタと同一・本タスクと無関係と確認）。
- [x] **Step 2（凍結カタログ）**: merge-base（本ブランチ分岐直前の main tip・一時 `git worktree` で撮影しノイズ排除）と本ブランチを比較。**#14 の列幅 pin 要因はツリー（`tree.sizeHint()=256px`）と実測確定**（現行コード/旧テンプレ文言/旧コード忠実再現の3条件すべてで `channel_dock.width()=258px` 同一 → `--crop-meta` 完全一致＝T-B1 の担保どおり viewport 非実証・通常比較はヘッダーテキスト領域限定の差分のみ）。**#17 の 09_collapsed は viewport 実測で変化**（`{w:912,h:772}→{w:908,h:768}`・各辺 -4px）→ 再ベースライン。**新規 `10_collapse_one`**（`window._collapse_dock(window.channel_dock)` のみ）を `capture_ui_screenshots.py` に追加しレール画面端配置を凍結被覆（目視でレール=画面右端・開いている File ドックがその内側を確認）。per-state 差分が想定内に限定されることを確認 → `screenshots_catalog_{dark,light}` を昇格 → 再撮影 compare 決定性 exit 0（両テーマ・通常/`--crop-meta` とも）。
- [x] **Step 3（docs）**: docs/design.md 決定履歴に 2026-07-24 エントリ追加（#14/#15/#17・#17 は候補 A 機構＋実測に基づく §3/§6 の訂正・follow-up `task_bd63c2f2` 言及）。spec 自体も §3/§5/§6 を Task 4 実測で再訂正（「片方でプロット幅不変」→「レール幅ぶん ~24px 縮む」・両方畳みも ~4px 縮む）。CLAUDE.md に新規行「横断 / 雑メモ解消」を追加（完了サマリ・spec ポインタ）。カタログ（UX/UXG）は別系統のため記載なし。
- [x] **Step 4（プランのチェックボックス更新）**: 本ファイルを消化済みへ更新（このコミット）。
- [x] **Step 5（最終ゲート＋commit）**: `uv run pytest -q`（1737 passed, 104 skipped）・`ruff check`（All checks passed）・`ruff format --check`（278 files already formatted）・`mypy src/`（Success, 85 files）green → commit。

## Self-Review 済み確認事項

- spec §1-§7 の全要素がタスクに 1:1（#14 header/word-wrap/未選択strings・#15 位置ベース/sabotage・#17 候補A スパイク/ガードレール/非重なり/extent/既存移行・realgui/カタログ/docs）。
- I1（#15 位置ベース）= Task 2 Step3/4。Minor 反映: #17 候補A確定（Task 3）・縦積みプロット非拡大（Global＋Task 3 T-C2）・#14 床タイトルバー（Task 1 Step5）・未選択strings（Task 1）・非重なり境界/extent両側（Task 3 Step4）・既存テスト移行（Task 3 Step5）・カタログ viewport 条件化（Task 4 Step2）。
- 型整合: `header_text`/`CHANNEL_HEADER_NO_FILE`/`ACTION_SHOW_SIGNAL_PROPERTIES`/`preview_requested.emit(hit_key)`/レール最外ドック。
- #17 は BLOCKED 経路を明示（候補 A 不成立時はコントローラ経由でユーザー再承認）。
