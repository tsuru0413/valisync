# 計測 IA 刷新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v3 ユーザー決定どおりの計測 IA（共有 CursorState・Analyze/右クリック統一・Shift+クリック B 設置・Sync X 右クリック化・ステータスバー即値・readout 2 モード化）で UX-04/13/14/15/16/22部分/24部分/25/26/32/33/37/46/48 を解消する。

**Architecture:** タブ所有の共有 CursorState（オブジェクト共有＋property 委譲）を土台に、AnalysisActions 単一ファクトリで Analyze/右クリックを同一 QAction 化、MainWindow は statusTip 横取り＋左即値/右メッセージのステータスバーへ刷新。

**Tech Stack:** PySide6 / pyqtgraph / pytest(-qt)。Layer C は `--realgui`。

**Spec:** [2026-07-21-measurement-ia-design.md](../specs/2026-07-21-measurement-ia-design.md) — **§1 の確定事実（cache 非包含・statusTip 機構・data_explorer 別バー等）と §3 の test-lock 全数表が真実**。本プランは手順。

## Global Constraints

- CursorState の既定値は dataclass のみが持つ — **GraphPanelVM.__init__ は 4 フィールドへ書き込まない**（共有巻き戻し blocker）。
- 扇状配布は **notify のみ（`"cursor"`/`"delta"` タグ保存）・`_invalidate_cache` 禁止**（cursor は cache key 非包含 — 確定済み）。
- 共有 checkable QAction は **`triggered` 配線のみ**（`toggled` 禁止 — setChecked 同期の誤発火）。
- `set_cursor_b` は A 未設置 no-op・暗黙 delta・**notify `"delta"` 単発**（既存 lock 維持）。
- showMessage 廃止は **main_window 限定**（data_explorer_view.py:126 は現状維持 allowlist）。**statusTip は `MainWindow.event()` 横取り**で右ラベルへ。
- Shift+クリックは **ZONE_PLOT 全域で最優先**（曲線ヒット・カーソル線 10px より先）。
- 色はトークンのみ（新設 `chrome_cursor_a`/`chrome_cursor_b` — DARK は cursor_a/b 同値別役割=値分岐テスト必須・LIGHT は AA 実測選定）。
- 品質ゲート毎コミット。テストは**同期実行**（run_in_background 禁止）。コメント WHY 日本語。

---

### Task 1: CursorState 共有化＋set_cursor_b 対称化（VM）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（CursorState dataclass 追加・`__init__` の 4 代入撤去・property 化・set_cursor_b ガード＋暗黙 delta）
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Produces: `CursorState` dataclass・`GraphPanelVM(session, cursor_state: CursorState | None = None)`・4 フィールドの property（API 名不変）。

- [ ] **Step 1（RED）**:

```python
def test_cursor_state_shared_object(vm_pair_sharing_state):
    vm1, vm2, state = vm_pair_sharing_state  # 同一 CursorState を注入した 2 VM
    vm1.set_cursor(3.0)
    assert vm2.cursor_t == 3.0              # 配布でなく共有 (spec §2.1)


def test_injected_state_survives_construction():
    # blocker 反映: __init__ の既定値代入が共有状態を巻き戻さない
    state = CursorState(cursor_t=7.5, cursor_t_b=9.0, delta_enabled=True,
                        interp_method=InterpolationMethod.NEAREST)
    vm = GraphPanelVM(_make_session(), cursor_state=state)
    assert (vm.cursor_t, vm.cursor_t_b, vm.delta_enabled, vm.interp_method) == (
        7.5, 9.0, True, InterpolationMethod.NEAREST)


def test_set_cursor_b_noop_without_a(basic_vm):
    basic_vm.set_cursor_b(5.0)
    assert basic_vm.cursor_t_b is None and basic_vm.delta_enabled is False


def test_set_cursor_b_implies_delta(basic_vm):
    basic_vm.set_cursor(3.0)
    basic_vm.set_cursor_b(5.0)
    assert basic_vm.delta_enabled is True   # half-set 廃止 (UX-13/46)
```

既存 `test_set_cursor_b_notifies_delta`（`"delta"` 単発契約）は**無変更で green 維持**が要件。

- [ ] **Step 2（GREEN）**: dataclass＋`self._cursor_state = cursor_state or CursorState()`・
  4 property（getter/setter とも `_cursor_state` へ委譲 — setter は既存フィールド直書き箇所
  〔`self.cursor_t = ...` を grep〕がある場合そのまま動く互換を保つ）・`set_cursor_b` 先頭に
  `if self.cursor_t is None: return`＋`self._cursor_state.delta_enabled = True`（notify は従来の
  `"delta"` 1 回のまま）。
- [ ] **Step 3**: focused → full `uv run pytest -q` → gates → Commit `feat(gui): タブ共有 CursorState と set_cursor_b 対称化 (UX-13/15/16 土台・spec §2.1)`

### Task 2: タブ注入＋"delta" ルーティング＋area 通知（GraphAreaVM）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_area_vm.py`（`_Tab.cursor_state` 追加・パネル生成 2 箇所へ注入・`_on_panel_change` の `"delta"` 分岐・配布=同タグ notify＋area `_notify("cursor")`・`propagate_cursor` の状態 push 撤去）
- Test: `tests/gui/test_graph_area_vm.py`／`tests/gui/test_graph_area_cursor.py`

**Interfaces:**
- Consumes: Task 1。Produces: タブ内共有の成立（add_panel 継承）・area レベル `"cursor"` 通知。

- [ ] **Step 1（RED — blocker 対応の値保存テストを含む）**:

```python
def test_add_panel_preserves_tab_cursor_state(area_with_signals):
    area = area_with_signals
    p0 = area.panels(0)[0]
    p0.set_cursor(3.0); p0.set_cursor_b(5.0)
    area.add_panel(0)
    p1 = area.panels(0)[1]
    # 巻き戻し禁止 (blocker): 既存値が不変で新パネルから同値が読める
    assert (p0.cursor_t, p0.cursor_t_b, p0.delta_enabled) == (3.0, 5.0, True)
    assert (p1.cursor_t, p1.cursor_t_b, p1.delta_enabled) == (3.0, 5.0, True)


def test_tabs_have_independent_cursor_state(area_with_signals):
    area = area_with_signals
    area.add_tab()
    area.panels(0)[0].set_cursor(3.0)
    assert area.panels(1)[0].cursor_t is None


def test_delta_change_notifies_siblings_and_area(area_two_panels):
    area, p0, p1 = area_two_panels
    p0.set_cursor(3.0)
    seen = []
    p1.subscribe(lambda vm, tag: seen.append(tag))
    area_seen = []
    area.subscribe(lambda vm, tag: area_seen.append(tag))
    p0.toggle_delta(True)
    assert "delta" in seen        # タグ保存の扇状配布 (spec §2.1)
    assert "cursor" in area_seen  # area レベル通知 (§2.4 の即値が購読)
```

- [ ] **Step 2（GREEN）**: `_Tab` に `cursor_state: CursorState = field(default_factory=CursorState)`・
  パネル生成（初期タブ/add_panel/add_tab の全生成点を grep）で `cursor_state=tab.cursor_state`
  注入・`_on_panel_change` に `elif change in ("cursor", "delta"):` 分岐 —
  `_propagating` ガード内でタブ内他パネルへ **同タグ `_notify` のみ**配布（**`_invalidate_cache`
  禁止** — Global Constraints）し、最後に `self._notify("cursor")`。`propagate_cursor` の
  `panel.set_cursor(t)` push は撤去（メソッド自体は互換のため同タグ notify 配布へ縮退）。
- [ ] **Step 3**: full＋gates → Commit `feat(gui): CursorState のタブ注入と delta ルーティング (spec §2.1)`

### Task 3: AnalysisActions＋Analyze メニュー＋空白メニュー共有化＋文言統一

**Files:**
- Create: `src/valisync/gui/views/analysis_actions.py`（ファクトリ）
- Modify: `src/valisync/gui/views/main_window.py`（Analyze メニュー掲載・`_active_pvm_call` 配送）・`src/valisync/gui/views/graph_panel_view.py`（build_context_menu の共有 QAction 化・注入口・文言統一〔カーソル線メニュー含む〕）・`src/valisync/gui/views/graph_area_view.py`（panel_factory 注入経路）
- Test: `tests/gui/test_context_menus.py`／`tests/gui/test_main_window.py`／`tests/gui/test_graph_panel_cursor.py`（文言追随）

**Interfaces:**
- Produces: `build_analysis_actions(parent, dispatch) -> AnalysisActions`（QAction 群 dataclass:
  cursor_a / cursor_b / clear_cursors / interp_actions / step_hint）。`dispatch` は
  「対象 GraphPanelVM を返す callable」（Analyze=アクティブパネル・コンテキスト=自パネル）。

- [ ] **Step 1（RED）**: (a) Analyze メニューに 4 項目＋情報行が並ぶ・(b) **aboutToShow の
  setChecked 同期だけでは `toggle_main_cursor`/`toggle_delta` が呼ばれない**（スパイ VM で 0 回
  assert — 誤発火ガード）・(c) 空白メニューとメニューバーが同一 QAction（`is` 比較）・
  (d) 文言「カーソル A」「カーソル B（Δ）」「カーソル A を消す」等（grep 追随: spec §3 表）。
- [ ] **Step 2（GREEN）**: ファクトリは QAction を **triggered 配線のみ**で生成（checkable の
  `setChecked` はどのハンドラも起動しない）。MainWindow: `_analysis_actions =
  build_analysis_actions(self, self._active_panel_vm)`・Analyze `aboutToShow` で
  checked/enabled 同期。GraphPanelView: コンストラクタ `analysis_actions=None` 注入（未注入時は
  同一ファクトリでローカル生成 — bare ハーネス互換）・build_context_menu の
  「メインカーソル/サブカーソル」ブロックを共有 QAction `addAction` へ置換（build 時に同期）。
  文言統一は spec §3 の grep 全数（カーソル線メニュー「サブカーソルを消す」→「カーソル B（Δ）を
  消す」含む）。
- [ ] **Step 3**: full＋gates → Commit `feat(gui): Analyze メニュー実装と解析 QAction 共有化 (UX-04/24/37)`

### Task 4: Shift+クリック B 設置（view press 分岐）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（ZONE_PLOT press の先頭に Shift 分岐）
- Test: `tests/gui/test_graph_panel_cursor.py`（Layer B）

- [ ] **Step 1（RED — Layer B）**: sendEvent で Shift+press → (a) A 設置済なら `cursor_t_b` が
  クリック時刻に＋delta True・(b) A 未設置なら `cursor_t` 設置（B は None のまま）・
  (c) **曲線上座標でも**設置（press 候補に奪われない）・(d) **A 線 10px 内でも**設置
  （線ドラッグに奪われない）・(e) 非 Shift の既存挙動（活性化/解除）不変。
- [ ] **Step 2（GREEN）**: ZONE_PLOT の press ハンドラ先頭（曲線ヒット・カーソル線ヒット判定より
  **前**）に `if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:` 分岐 — シーン座標→時刻変換
  （既存の線ドラッグと同じ変換を再利用）→ `vm.set_cursor_b(t)` or `vm.set_cursor(t)`・accept。
- [ ] **Step 3**: full＋gates → Commit `feat(gui): Shift+クリックでカーソル B 直接設置 (UX-13)`

### Task 5: Sync X 右クリック化＋corner コンテナ化

**Files:**
- Modify: `src/valisync/gui/views/graph_area_view.py`（sync_checkbox 撤去・sync getter/setter を panel_factory 経由で注入・corner コンテナ〔+ と読み値トグル〕）・`src/valisync/gui/views/graph_panel_view.py`（空白メニューに「X軸同期（タブ内全パネル）」checkable・注入 callback・未注入時は項目非表示）
- Test: `tests/gui/test_x_sync.py`（メニュー経由へ書換え）・`tests/gui/test_graph_area_tab_ui.py`（cornerWidget → findChild）

- [ ] **Step 1（RED）**: (a) 空白メニューに「X軸同期（タブ内全パネル）」checked=現状態・triggered で
  toggle・(b) `sync_checkbox` 属性が存在しない・(c) cornerWidget コンテナに `new_tab_button` と
  読み値トグルが `findChild` で見つかる。
- [ ] **Step 2（GREEN）**: 実装＋spec §3 の test 追随（test_x_sync 系・tab_ui objectName）。
- [ ] **Step 3**: full＋gates → Commit `feat(gui): Sync X を右クリックへ移設・タブ行整理 (v3 決定4/5)`

### Task 6: ステータスバー刷新（statusTip 横取り・即値・新トークン）

**Files:**
- Modify: `src/valisync/gui/theme/tokens.py`（`chrome_cursor_a`/`chrome_cursor_b` 新設 — DARK=cursor_a/b 同値・LIGHT=AA 実測選定）・`src/valisync/gui/theme/qss.py`（status 即値の色付け生成関数）・`src/valisync/gui/views/main_window.py`（`event()` 横取り・`set_status_message(text, timeout_ms=0)`・左即値ウィジェット・showMessage 7 箇所置換・graph_area_vm 購読で即値更新）
- Test: `tests/gui/test_theme_tokens.py`（golden＋値分岐 2 組）・`tests/gui/test_main_window.py`・`tests/gui/test_theme_export.py`（トークン数）

- [ ] **Step 1（RED）**: (a) `set_status_message("x")` → 右ラベル text・timeout_ms=100 で自動
  クリア・(b) **QStatusTipEvent を sendEvent → 左即値ラベルが `isVisible` のまま＋右ラベルに tip**
  （blocker 対応ガード）・(c) カーソル設置で左即値 `A 3.000 s` 表示・タブ切替で入替・未設置で
  空文字・(d) 新トークン golden＋値分岐（chrome_cursor_a↔cursor_a・chrome_cursor_b↔cursor_b）。
- [ ] **Step 2（GREEN）**: spec §2.4 のとおり（`event()` で `QEvent.Type.StatusTip` を消費し
  `set_status_message(tip)`・既定処理へ通さない／右=addPermanentWidget／左=addWidget 3 ラベル／
  graph_area_vm 購読 1 本で `"cursor"/"active"/"tabs"/"panels"` 時にアクティブタブ CursorState を
  pull）。showMessage 置換は main_window の 7 箇所のみ（**data_explorer は触らない**）。
  currentMessage 依存テストの追随（spec §3・allowlist 明記）。
- [ ] **Step 3**: full＋gates → Commit `feat(gui): ステータスバー刷新 (左=計測即値/右=メッセージ・statusTip 横取り・v3 決定2)`

### Task 7: 時刻書式＋readout ヘッダ新書式

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`（ヘッダ「A 100.035 s ・ B 149.865 s（線形）」・`.3f`）・`src/valisync/gui/views/graph_panel_view.py`（時刻ダイアログ初期値 `.3f`）
- Test: `tests/gui/test_cursor_readout.py`（`test_header_markers_and_pane_use_tokens` の新書式追随 — A/B ラベルの cursor 色 assert 維持）

- [ ] **Step 1（RED→GREEN）**: 書式純関数＋ヘッダ組立の変更。サブ ms Δt の 0.000 丸めは意図的
  制限（spec §2.5）— テストは丸め挙動を lock。
- [ ] **Step 2**: full＋gates → Commit `feat(gui): カーソル時刻を固定小数3桁へ・readout ヘッダ新書式 (UX-14/48)`

### Task 8: readout 2 モード化（凡例/計測/収納・min/max 2 列）

**Files:**
- Modify: `src/valisync/gui/views/cursor_readout.py`（凡例モード・min/max 独立 2 列＋「（全区間）」・TSV 追随・`readout_stowed`）・`src/valisync/gui/views/graph_area_view.py`（信号ゼロ収納・凡例/計測切替の配線）
- Test: `tests/gui/test_cursor_readout.py`・`tests/gui/test_graph_area_view.py`

- [ ] **Step 1（RED）**: (a) カーソル未設置＋信号あり → 凡例行（スウォッチ＋名前＋[unit]・列
  ヘッダなし）・(b) 設置 → 計測モード（min/max 2 列・右揃え・ヘッダ「（全区間）」）・(c) 信号ゼロ →
  `readout_stowed is True`＋ペイン非表示（トグル状態は True のまま）・(d) TSV 列分離。
  spec-B 案b の反転（プレースホルダ assert → 凡例 assert）は**意図的 supersede をテスト docstring
  に記録**。
- [ ] **Step 2（GREEN）**: 実装＋`show_placeholder` 3 経路置換＋`readout_visible()`/`isVisible`
  assert の追随（spec §3 — realgui `test_global_cursor.py:290` は Task 9 で）。
- [ ] **Step 3**: full＋gates → Commit `feat(gui): 読み値ペイン 2 モード化 (凡例/計測/収納・UX-22/25/26/33)`

### Task 9: realgui — 新設 3 本＋既存追随

**Files:**
- Create: `tests/realgui/test_analyze_menu_realclick.py`（Analyze→カーソル A 実クリック→線消滅）・`tests/realgui/test_shift_click_cursor_b.py`（Shift+実クリック B 設置 — 同座標 Shift なし対照＋実装 sabotage RED・曲線上 1 ケース）・`tests/realgui/test_x_sync_menu_realclick.py`（右クリック「X軸同期」ON→2 パネル実ズーム追随）
- Modify: 既存 realgui の文言/構成追随（`test_grid_realclick.py`・`test_graph_panel_menu_realclick.py` のメニュー列挙・`test_tab_ui_flow.py` の new_tab_button 矩形・`test_global_cursor.py` の readout 状態 assert）

- [ ] **Step 1**: 新設 3 本を既存ヘルパ（`_realgui_input`・`_open_menu_click_item`）で実装。
  honest RED: Shift テストは「同座標 Shift なしで B 非設置」対照＋Shift 分岐を一時無効化する
  sabotage で不発を 1 度実証（revert 後 git diff clean）。
- [ ] **Step 2**: `uv run pytest --realgui tests/realgui/ -v` **フル** → 全 PASS（文言・corner・
  readout 追随の fallout をここで全数検出し spec §3 に従い追随）。
- [ ] **Step 3**: headless full＋gates → Commit `test(realgui): 計測 IA の実OS検証 3 本＋既存追随 (①ゲート)`

### Task 10: 凍結 per-state 突合・ベースライン昇格・決定履歴

- [ ] **Step 1**: full gates → dark/light `--catalog` 撮影 → **spec §2.7 の per-state 表と突合**
  （01=ステータスバーのみ・02=凡例モード等・03-05/09=Δ 表示化＋即値非空 — 表外差分=回帰調査）。
- [ ] **Step 2**: ベースライン昇格（in-place 再撮影＋compare exit 0 で決定性実証）＋
  `export_design_tokens` 両テーマ（新トークン 2 個反映）。
- [ ] **Step 3**: docs/design.md 決定履歴（v3 IA・supersede 2 件〔spec-B 案b・UX-32 View 案〕・
  新トークン・凍結更新）＋カタログ解消マークは PR 反映時。Commit → 最終レビュー（fable）→ PR。

## 実施順序と依存

Task 1 → 2（VM 土台）→ 3 → 4 → 5（メニュー/入力）→ 6（ステータスバー — 2 の area 通知に依存）→
7 → 8（readout）→ 9（realgui・実ディスプレイ）→ 10。PR は 1 本。
