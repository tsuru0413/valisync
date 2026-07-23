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

- [ ] **Step 1（スパイク — 候補 A の実現可能性を realgui 実機実証）**: レールを各辺の**最外ドック**（`QDockWidget`・`splitDockWidget` で最外全高）へ移す最小プロトタイプを組み、**片方折りたたみで実 OS レールが開ドックの外側（`rail.left() >= openDock.right()`・非重なり）**に来ることを realgui スクショ＋矩形実測で確認。**成立しなければ BLOCKED でコントローラへ即エスカレーション**（緩和 B はユーザー再承認が要るため実装者は独断で進めない）。
- [ ] **Step 2（honest-RED）**: 現状（レールが中央側 col2）で「非重なり境界」assert が RED になることを実証（機構変更前）。
- [ ] **Step 3（実装 — 候補 A＋ガードレール）**: レール最外ドック化を本実装。ガードレール全て:
  - レールドック `setFeatures(NoDockWidgetFeatures)`（非移動/非クローズ/非フロート）＋薄いレール見た目（タイトルバー無し）。
  - `objectName` 安定＋既存 `saveState` blob 互換（旧 state 復元の互換/移行）。
  - `dockLocationChanged` で最外順序を能動是正（removeDockWidget＋再 split）。
  - `restoreState` 後に順序＋`setCorner`＋`_apply_default_dock_ratio` を再適用（レールが 3 番目の参加者になる 1:4/corner 干渉を調整）。
  - 空時 `setVisible(False)`（ゼロ幅）。
- [ ] **Step 4（Layer C — T-C1/T-C1b/T-C2）**:
  - T-C1: 片方折りたたみでレール非重なり外側（`rail.left() >= openDock.right()`・`widgetAt(レール中心)` がレール）・File/Channel 両対称。
  - T-C1b: 開ドックを実 OS D&D でレール外へ→最外再アサート。順序を崩した save→restore 後にレール最外復元。
  - T-C2: 両方折りたたみ（09 相当）レール画面端・全展開レールゼロ幅が無回帰。collapse→expand 後 `dock.width()/height()` が `_expanded_extent` と両側数 px 一致。
- [ ] **Step 5（既存テスト移行）**: `test_collapsible_docks_realclick.py` の `central.width` reclaim assert（単独折りたたみで無効）をレール矩形 x 比較へ置換・内部ハンドル（`_central_with_rails`/`_collapse_rails[area]`/`rail._tabs`）直参照を機構に合わせ移行。既存 collapse 系全数無回帰。
- [ ] **Step 6（ゲート＋commit）**: green → `feat(gui): 折りたたみレールを画面端(開ドックの外側)へ — レール最外ドック化 (#17)`

---

## Task 4: realgui フル＋凍結カタログ＋docs＋最終ゲート

**Files:**
- Modify: `scripts/capture_ui_screenshots.py`（#14 ヘッダー差分・#17 の 10_collapse_one 追加判断）
- Modify: `docs/design.md`・`CLAUDE.md`
- Verify: `design_export/screenshots_catalog_{dark,light}`

- [ ] **Step 1（realgui フル）**: `uv run pytest tests/realgui/ --realgui -q`（timeout 600000・バッチ可）。既知フレークは単体で切り分け。
- [ ] **Step 2（凍結カタログ）**: 撮影 → `compare_screenshots.py`（両テーマ・`--crop-meta`）。**#14 の右ドック列幅 pin 要因を実測**（タイトルバー/ツリー律速ならプロット viewport 不変で T-B1 担保／ヘッダー律速なら 02-05 再ベースライン）。**#17 の 09_collapsed** はレール機構でプロット viewport 右端が動くか実測（動けば 09 も再ベースライン）。**新規 `10_collapse_one`**（片方折りたたみ）を追加してレール画面端配置を凍結被覆。per-state 差分限定を確認 → 昇格 → 決定性 exit 0。
- [ ] **Step 3（docs）**: docs/design.md 決定履歴（#14/#15/#17・#17 は候補 A 機構＋縦積みプロット非拡大の訂正・敵対的レビュー要点）。CLAUDE.md の 横断 行へ雑メモ解消完了サマリ。カタログ（UX/UXG 別系統ゆえ該当なければ記載不要）。
- [ ] **Step 4（プランのチェックボックス更新）**: 消化済みへ。
- [ ] **Step 5（最終ゲート＋commit）**: `uv run pytest -q`・ruff・mypy green → `feat(gui): 雑メモ解消 realgui ①ゲート＋凍結検証＋docs`

## Self-Review 済み確認事項

- spec §1-§7 の全要素がタスクに 1:1（#14 header/word-wrap/未選択strings・#15 位置ベース/sabotage・#17 候補A スパイク/ガードレール/非重なり/extent/既存移行・realgui/カタログ/docs）。
- I1（#15 位置ベース）= Task 2 Step3/4。Minor 反映: #17 候補A確定（Task 3）・縦積みプロット非拡大（Global＋Task 3 T-C2）・#14 床タイトルバー（Task 1 Step5）・未選択strings（Task 1）・非重なり境界/extent両側（Task 3 Step4）・既存テスト移行（Task 3 Step5）・カタログ viewport 条件化（Task 4 Step2）。
- 型整合: `header_text`/`CHANNEL_HEADER_NO_FILE`/`ACTION_SHOW_SIGNAL_PROPERTIES`/`preview_requested.emit(hit_key)`/レール最外ドック。
- #17 は BLOCKED 経路を明示（候補 A 不成立時はコントローラ経由でユーザー再承認）。
