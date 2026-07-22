# 診断・読み値の整合性修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 診断ドックと読み値ペインの実バグ/不整合 6 件（B1-B6）のみを、現状の見た目・挙動契約を保存したまま修正する（D-2 不採用の代替）。

**Architecture:** 診断は view/VM の局所修正（counts 3-tuple・QButtonGroup 排他・tooltip・確認 DI）。シェブロンは rail の辺写像を逆写像で共有。読み値は rows_host＋QScrollArea 化を sizeHint override（条件付き予約）・mapFrom 座標写像・setAutoFillBackground 明示で「縦のみ有界化・他契約は全保存」。

**Tech Stack:** PySide6・pytest(-qt)・realgui（実 Win32 入力）。

**Spec:** [docs/superpowers/specs/2026-07-22-diag-readout-consistency-design.md](../specs/2026-07-22-diag-readout-consistency-design.md) — §2 の設計・§4 のテスト戦略・レビュー実測値が一次情報源。**文言は spec §2.2/§2.5 の逐語値＋文言 OS 規約（R-02/R-08/R-10）**。

## Global Constraints

- 「現状のまま」: 見た目・配置・列構成・幅挙動（非オーバーフロー時）を変えない。スコープ外の改善を足さない（YAGNI）。
- 読み値の幅契約: **非オーバーフロー時のヒント幅は現行と同値**（凍結 03/04 divider 一致が機械検証）・垂直スクロールバー予約は**縦オーバーフロー時のみ**加算・minimumSizeHint 高さ=「outer マージン＋時刻ヘッダ高＋行 3 行分」。
- B6 の行クリック検証は**実イベント経路のみ**（`activate_row()` 直呼び禁止）。
- B5 の既存 4 テスト（tests/gui/test_diagnostics_view.py:44/69/86/143）は**同一コミットで** `_confirm_fn` stub 追随（モーダル無期限ハング防止）。
- 品質ゲート: `uv run pytest`（headless full）・`uv run ruff check`・`uv run ruff format`・`uv run mypy src/` を各タスク末で同期実行。realgui はタスク内 scoped（作成分）＋Task 4 でフル。
- コミット末尾: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## Task 1: 診断ビュー（B1 カウンタ ℹ・B2 checkable 排他・B3 tooltip・B5 Clear 確認）

**Files:**
- Modify: `src/valisync/gui/viewmodels/diagnostics_vm.py`（counts 3-tuple）・`src/valisync/gui/views/diagnostics_view.py`・`src/valisync/gui/strings.py`
- Test: `tests/gui/test_diagnostics_vm.py`・`tests/gui/test_diagnostics_view.py`・`tests/gui/test_main_window.py:646`・新規 `tests/realgui/test_diagnostics_clear_realclick.py`

**Interfaces:**
- Produces: `DiagnosticsViewModel.counts() -> tuple[int, int, int]`（errors, warnings, infos）。`DiagnosticsView._confirm_fn: Callable[[int], bool]`（属性 DI — file_browser_view.py:112-139 と同型）。`strings.DIAG_EMPTY`/`DIAG_EMPTY_FILTERED_TMPL`/`DIAG_CLEAR_CONFIRM_TITLE`/`DIAG_CLEAR_CONFIRM_BODY_TMPL`/`DIAG_CLEAR_CONFIRM_YES`/`DIAG_CLEAR_CONFIRM_NO`。

- [ ] **Step 1（B1 RED→GREEN）**: tests/gui/test_diagnostics_vm.py:27 を `== (1, 2, 0)` へ・info 込みシードのケースを追加 → RED → `counts()` を 3-tuple 化 → GREEN。追随: tests/gui/test_main_window.py:646（`== (0, 0, 0)`）・tests/gui/test_diagnostics_view.py:75/84/87（「⛔ 0 / ⚠ 0 / ℹ 0」形式）＋ view のラベル f-string 更新。
- [ ] **Step 2（B2）**: strings 追加:

```python
DIAG_EMPTY = "診断はありません"
DIAG_EMPTY_FILTERED_TMPL = "{level}に該当する診断はありません（全 {n} 件）"
```

view: 3 ボタン `setCheckable(True)`＋`QButtonGroup(self)`（exclusive 既定）へ addButton・構築時 `_btn_all.setChecked(True)`。`set_filter(level)` の**先頭で対応ボタンを `setChecked(True)`**（真実源 `_filter` — spec §2.2）。`_rebuild` のプレースホルダを `_filter` 依存で `DIAG_EMPTY` / `DIAG_EMPTY_FILTERED_TMPL.format(level=表示ラベル, n=無フィルタ総数)` に。**diagnostics_view.py:9-11 docstring と :137-139 コメントの「spec §7 同一表示」記述を supersede 後の記述へ更新**（spec §2.2）。

テスト（**三点結合** — spec §4）: シードを error 1・warning 2・info 3 の**判別可能構成**にし、各ボタン click 後に (1) `_filter` (2) `row_count()` が当該レベル件数 (3) 当該ボタン `isChecked()` を assert。＋ `set_filter("warning")` 直呼び→ `_btn_warn.isChecked()`。＋ 0 件文言（警告のみシード＋エラーフィルタ→「エラーに該当する診断はありません（全 1 件）」）。排他性単独 assert は書かない。
- [ ] **Step 3（B3）**: `_rebuild` のメッセージセルへ `item.setToolTip(e.message)`（`c == _MESSAGE_COLUMN` 分岐）。テスト: toolTip == 全文。
- [ ] **Step 4（B5）**: strings 追加:

```python
DIAG_CLEAR_CONFIRM_TITLE = "診断のクリア"
DIAG_CLEAR_CONFIRM_BODY_TMPL = "診断 {n} 件をクリアしますか？この操作は元に戻せません。"
DIAG_CLEAR_CONFIRM_YES = "クリア"
DIAG_CLEAR_CONFIRM_NO = "キャンセル"
```

view: `self._confirm_fn: Callable[[int], bool] = self._default_confirm`（明示 QMessageBox・Yes/No setText — file_browser の `_confirm_fn` 同型）。`clear_diagnostics()`: `n = len(self._vm.entries(None))`・`if n == 0: return`・`if not self._confirm_fn(n): return`・`self._vm.clear()`。

テスト: stub で 3 分岐（True→クリア/False→非実行/0 件→confirm 不呼出を Mock で assert）。**既存 4 サイト（:44/69/86/143）へ `view._confirm_fn = lambda n: True` を同一コミットで注入**。
- [ ] **Step 5（B5 realgui 新設）**: `tests/realgui/test_diagnostics_clear_realclick.py` — 実 OS クリックで クリアボタン→実ダイアログ→「クリア」ボタン実クリック→表が空＋プレースホルダ＋カウンタ 0/0/0。**test_readout_realclick.py の `_menu_hang_watchdog` と同型の Escape watchdog 併設**。`uv run pytest tests/realgui/test_diagnostics_clear_realclick.py --realgui -q` をローカル実行し pass。
- [ ] **Step 6**: ゲート（headless full・ruff・mypy）→ commit `fix(gui): 診断の実バグ修正 — カウンタℹ/フィルタ checkable 排他/全文 tooltip/Clear 確認 (B1-B3,B5)`

---

## Task 2: シェブロンの辺解決（B4）

**Files:**
- Modify: `src/valisync/gui/views/dock_collapse_rail.py`（写像追加）・`src/valisync/gui/views/collapsible_dock_title_bar.py`
- Test: `tests/gui/test_dock_collapse_rail.py`・`tests/gui/test_collapsible_dock_title_bar.py`（既存へ追記）

**Interfaces:**
- Produces: `dock_collapse_rail.collapse_chevron_for_area(area: Qt.DockWidgetArea) -> str | None`（Left→"chevron_left"・Right→"chevron_right"・Bottom→"chevron_down"・Top→"chevron_up"・その他 None）。`CollapsibleDockTitleBar.chevron_icon_name() -> str`（introspection）。

- [ ] **Step 1（写像 TDD）**: 純関数テスト（4 辺＋`NoDockWidgetArea`→None）→ RED → 実装（EXPAND_ICON の逆 dict＋`.get()`）→ GREEN。
- [ ] **Step 2（タイトルバー）**: 構築時 `main_window.dockWidgetArea(dock)` で解決し `self._chevron_name` 保持＋`setIcon(icons.icon(name))`。`dock.dockLocationChanged.connect(self._on_dock_area_changed)` — スロットは `collapse_chevron_for_area(area)` が **None なら早期 return（直前維持）**、変わったときのみ setIcon＋`_chevron_name` 更新。`chevron_icon_name()` 公開。
- [ ] **Step 3（Layer B）**: build_main_window で (a) 下端診断のタイトルバーが "chevron_down"・右ドックが "chevron_right"、(b) `main_window.addDockWidget(LeftDockWidgetArea, dock)` 移動→ "chevron_left" 追随、(c) `dock.setFloating(True)`→名前不変（直前維持）、(d) cacheKey は (b) の遷移で変化のみ assert（恒等比較はしない — icons.icon は毎回新規 QIcon）。
- [ ] **Step 4**: ゲート → commit `fix(gui): 折りたたみシェブロンをドック辺から解決 (B4/UX-44)`

---

## Task 3: 読み値ペインの縦スクロール（B6）

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`
- Test: `tests/gui/test_cursor_readout.py`（追記）・`tests/realgui/test_readout_scroll_realclick.py`（新規）・既存 realgui 3 本の確認/追随

**Interfaces:**
- Consumes: spec §2.6 の確定設計（逐語）。
- Produces: `CursorReadout._rows_host: QWidget`・`CursorReadout._scroll: QScrollArea`（テスト掴み点）。

- [ ] **Step 1（現行契約の対照値を記録）**: 変更前に `uv run python` で現行の `sizeHint().width()`/`minimumSizeHint()`（凡例/計測両モード・3 行シード）を採取しテスト定数の根拠としてコミットメッセージ/テストコメントに記録。
- [ ] **Step 2（構造変更）**: spec §2.6 どおり —
  - `_rows_host = QWidget()`・`_grid`/`_placeholder`/stretch を rows_host の VBox へ（placeholder は stretch 前）。
  - `_scroll = QScrollArea()`（widgetResizable=True・水平 AlwaysOff・垂直 AsNeeded・NoFrame）→ `setWidget(_rows_host)` → **直後に** `_scroll.viewport().setAutoFillBackground(False)`・`_rows_host.setAutoFillBackground(False)`（順序制約コメント必須 — setWidget が True へ強制する Qt 仕様）。QSS 断片は追加しない。
  - `sizeHint()`/`minimumSizeHint()` override: 幅 = outer マージン込み `max(ヘッダ, _rows_host のヒント)`＋**縦オーバーフロー時のみ** `PM_ScrollBarExtent`。`minimumSizeHint` 高さ = outer マージン＋ヘッダ高＋行 3 行分。`sizeHint` 高さ = 内容ベース（rows_host＋ヘッダ合成）。
  - `mousePressEvent`: `pos = self._rows_host.mapFrom(self, pos)` 写像後に `_row_at`。
- [ ] **Step 3（Layer A — spec §4 逐語）**:
  - **ヒント同値**: 非オーバーフロー時（3 行）の `sizeHint().width()`/`minimumSizeHint().width()` が Step 1 の現行値と一致。
  - **高さ有界**: 25 行シードで `minimumSizeHint().height()` が 3 行相当の定数（行数非比例 — 現行は ≈16px/行で比例することを対照コメントに記録）。
  - **実イベント行クリック**: ラベルの `mapTo(readout)` 中心へ合成 QMouseEvent → 正しい entry_id が `row_activated` で emit。非スクロールと `verticalScrollBar().setValue()` 後の両方。`activate_row` 直呼びはこの検証に使わない。
  - **幅契約**: QSplitter 構成で `setSizes` により内容幅未満を要求→クランプされる。
  - **値分岐透過**: `surface_readout_panel` を分岐させたテーマでペイン面ピクセル（grab）がトークン値に追随（既存の値分岐パターン・同値盲点対策）。
- [ ] **Step 4（realgui）**: 既存 3 本をローカル scoped 実行（`test_readout_pane_realclick.py`〔行セル実クリック — 写像後も正解 entry_id〕・`test_readout_realclick.py`〔中心右クリック×2 — viewport 経由 contextMenuEvent〕）→ pass 確認（fail なら原因調査・写像/伝播の修正）。新設 `test_readout_scroll_realclick.py`: 実表示で 20 行超をシード→ウィンドウを縦縮小→ (a) 診断ドックの高さが維持（圧潰しない実測） (b) 読み値に垂直スクロールバー出現 (c) スクロール後の可視行を実 OS クリック→正しい曲線ハイライト。
- [ ] **Step 5**: ゲート → commit `fix(gui): 読み値ペインの縦スクロール化 — 縦のみ有界・幅契約/行クリック/透過を保存 (B6/UXG-17)`

---

## Task 4: 凍結・①ゲート・docs

- [ ] **Step 1**: realgui フル（4 バッチ可）pass。
- [ ] **Step 2**: 撮影前後比較（両テーマ）— 想定差分の照合表（spec §4）: 診断ドック内（カウンタ ℹ・「すべて」checked 枠=全状態×両テーマ・下端シェブロン >→v）のみ。**読み値・プロット viewport・divider はピクセル一致**（viewport crop 機械一致含む）。想定外差分は原因特定（意図的なら目視承認を記録）。
- [ ] **Step 3**: ベースライン昇格→再撮影 exit 0→エクスポート再生成→DesignSync 再同期。
- [ ] **Step 4**: docs — design.md 決定履歴（D-2 不採用・feedback-errors spec §7 supersede・6 修正・UXG-17 列見出し共スクロール逸脱・オーバーフロー時 +extent 例外）／カタログ解消マーク（UX-07/31/44・UXG-12/17 解消／UX-06・UXG-27 解消＋残項目の意図的不採用注記／UX-53 部分）／CLAUDE.md 行更新。
- [ ] **Step 5**: 最終ゲート → commit → PR。

## Self-Review 済み確認事項

- spec §1 の 6 修正すべてにタスクあり（B1-B3,B5=T1・B4=T2・B6=T3）。§2 の設計要素（mapFrom・条件付き予約・setAutoFillBackground×2・chevron_icon_name・_confirm_fn・set_filter 同期）は全てステップに現れる。
- 既存テスト追随の全数（B1 の 5 assert・B5 の 4 サイト）はレビュー実測の行番号で列挙済み。
- 型整合: `counts()` 3-tuple・`collapse_chevron_for_area -> str | None`・`_confirm_fn: Callable[[int], bool]` を Interfaces に明記。
