# 比較モードのユーザー切り替え Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 比較モードの起動を「ファイル数 ≥ 2 の自動判定」から「Analyze メニューで明示的に切り替える transient フラグ」へ置換する。既定シングル・OFF で家系色凍結・1 ファイル完全従来互換。

**Architecture:** [spec](../specs/2026-07-23-comparison-mode-toggle-design.md) §1-§10 に逐語で従う。`AppViewModel` に transient フラグ `_comparison_enabled` を持ち、`is_comparison_mode() = _comparison_enabled and len(loaded)>=2` を唯一の述語とする。全 consumer（`file_hue_resolver`/バッジ/チップ/FileBrowserVM）はこの 1 述語を読むため追従は自動。トグルは MainWindow 所有の独立 checkable QAction。OFF 凍結は `reapply_auto_colors` の resolver-None 時 `continue`（既存色保持）から自然に導かれる。

**Tech Stack:** PySide6・pytest(-qt)・realgui。

**Spec:** [docs/superpowers/specs/2026-07-23-comparison-mode-toggle-design.md](../specs/2026-07-23-comparison-mode-toggle-design.md) — **8 レンズ敵対的レビュー 33 confirmed（全 Minor）を M1-M16 として反映済み。**

## Global Constraints

- **transient（非永続）**: `_comparison_enabled` は QSettings へ永続しない。`reference_file_key` と同じセッション内一時状態。再起動で既定シングルへ戻る（M1）。
- **述語の唯一性**: `is_comparison_mode() = self._comparison_enabled and len(self._loaded_keys) >= 2`。メニュー checkstate は生フラグ `comparison_enabled`、色/バッジ発火は `is_comparison_mode()`。この使い分けを取り違えない（M4/§10）。
- **OFF 凍結**: `reapply_auto_colors` の `hue is None` での `continue`（既存色保持・count-mod へ戻さない）が唯一の凍結機構。改変禁止（§4）。
- **QAction 配置**: 比較モードトグルは panel-scoped `AnalysisActions`/`sync_analysis_actions` に載せない。**MainWindow 所有の独立 checkable QAction**。checked/enabled は `_sync_analysis_actions` 内で app_vm を直読（M4）。
- **ニーモニクス非付与**: 兄弟葉項目（カーソル A/B・カーソルを消す）に合わせ `comparison_mode` にニーモニクスを付けない。`test_menu_mnemonics` の G-46 dict・対訳表は**変更しない**（M5）。
- **既存 E-2 テスト追随はサイト別**: 機械的 `set_comparison_mode(True)` 挿入禁止。テストの意図（比較挙動の検証 vs 単一挙動の検証）ごとに判断（M13）。
- **キー体系・数式・オフセット・D&D mime・色パレット・hue_variant 係数・同名重ねの同軸性**は不変。
- 品質ゲート各タスク末: `uv run pytest -q`・`uv run ruff check`・`uv run ruff format`・`uv run mypy src/`（同期実行）。
- コミット末尾: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## Task 1: フラグ中核＋GraphAreaVM 配線＋VM テストスイープ

**Files:**
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py`（`_comparison_enabled` 状態・`is_comparison_mode()` 述語置換・`set_comparison_mode()`・`comparison_enabled` プロパティ・`inspect()`/状態スナップショットへ露出・`register_loaded` docstring 更新）
- Modify: `src/valisync/gui/viewmodels/graph_area_vm.py`（`_on_app_change` に `"comparison_mode"` 分岐）
- Test: `tests/gui/test_app_viewmodel*.py`・`tests/gui/test_graph_area_vm*.py`・`tests/gui/test_graph_panel_vm.py`（既存 E-2 VM テストの追随）

**Interfaces:**
- Produces: `AppViewModel.set_comparison_mode(enabled: bool) -> None`（notify `"comparison_mode"`）・`AppViewModel.comparison_enabled: bool`（生フラグ property）・`is_comparison_mode()` は `_comparison_enabled and len>=2`。
- Consumes: 既存 `reapply_auto_colors()`・`file_hue_resolver()`・`_for_each_panel`。

- [ ] **Step 1（述語 TDD — 失敗テスト）**: `tests/gui/test_app_viewmodel_comparison_mode.py`（新規）に T-A1/T-A2 を書く。

```python
def test_comparison_predicate_gates_on_flag_and_count(app_vm_with_two_files):
    vm = app_vm_with_two_files  # 2 files loaded
    assert vm.is_comparison_mode() is False        # default OFF
    assert vm.comparison_enabled is False
    vm.set_comparison_mode(True)
    assert vm.comparison_enabled is True
    assert vm.is_comparison_mode() is True          # flag AND >=2

def test_comparison_predicate_false_with_single_file_even_when_enabled(app_vm_one_file):
    vm = app_vm_one_file
    vm.set_comparison_mode(True)
    assert vm.comparison_enabled is True            # raw flag independent of count
    assert vm.is_comparison_mode() is False         # AND >=2 guard

def test_set_comparison_mode_same_value_is_noop(app_vm_with_two_files):
    vm = app_vm_with_two_files
    calls = []
    vm.subscribe(lambda tag: calls.append(tag) if tag == "comparison_mode" else None)
    vm.set_comparison_mode(False)                   # already False
    assert calls == []
    vm.set_comparison_mode(True)
    assert calls == ["comparison_mode"]
```

- [ ] **Step 2（RED 確認）**: `uv run pytest tests/gui/test_app_viewmodel_comparison_mode.py -q` → FAIL（`set_comparison_mode`/`comparison_enabled` 未定義）。
- [ ] **Step 3（実装）**: `app_viewmodel.py`。`__init__` に `self._comparison_enabled: bool = False`。述語を置換:

```python
def is_comparison_mode(self) -> bool:
    """True when the user has enabled comparison mode AND 2+ files are loaded.
    ...（spec §1 の docstring 逐語）..."""
    return self._comparison_enabled and len(self._loaded_keys) >= 2

def set_comparison_mode(self, enabled: bool) -> None:
    if enabled == self._comparison_enabled:
        return
    self._comparison_enabled = enabled
    self._notify("comparison_mode")

@property
def comparison_enabled(self) -> bool:
    return self._comparison_enabled
```

`inspect()`/状態スナップショット（`get_state` 付近）へ `"comparison_enabled": self._comparison_enabled` を `reference_file` と同層で追加。`register_loaded` docstring の「2nd file's load flips is_comparison_mode() true」を「比較モードの発火はトグル/フラグ ON（かつ ≥2 ファイル）時」に更新。

- [ ] **Step 4（GREEN 確認）**: `uv run pytest tests/gui/test_app_viewmodel_comparison_mode.py -q` → PASS。
- [ ] **Step 5（GraphAreaVM 配線 TDD — T-B5/T-B6）**: `tests/gui/test_graph_area_comparison_mode.py`（新規）に、2 ファイルロード済み（count-mod）→ `app_vm.set_comparison_mode(True)` → 各パネルが家系色になる（T-B5）・**任意パネル（初期＋add_tab）**が hue 由来色を持つ（T-B6）を書く。

```python
def test_toggle_on_recolors_all_panels_via_comparison_mode_branch(area_vm_two_files):
    area_vm = area_vm_two_files            # 2 files loaded, entries plotted, count-mod
    before = _colors(area_vm)
    area_vm._app_vm.set_comparison_mode(True)
    after = _colors(area_vm)
    assert after != before                 # families applied
    assert all(_is_hue_family(c) for c in after)  # every auto entry recolored

def test_resolver_reaches_added_tab_panel(area_vm_two_files):
    area_vm = area_vm_two_files
    area_vm.add_tab()                       # new panel via factory
    _plot_two_file_signals(area_vm.active_tab())
    area_vm._app_vm.set_comparison_mode(True)
    assert _any_hue_family_color(area_vm.active_tab().panel_vm)
```

- [ ] **Step 6（RED 確認）**: FAIL（`_on_app_change` に `comparison_mode` 分岐が無く再着色されない）。
- [ ] **Step 7（実装）**: `graph_area_vm.py` `_on_app_change` に分岐追加:

```python
elif change == "comparison_mode":
    # ON: recolor autos into families. OFF: reapply is a structural no-op
    # (resolver None → continue) → freeze-on-OFF for free. No ON/OFF branch.
    self._for_each_panel(lambda p: p.reapply_auto_colors())
```

- [ ] **Step 8（GREEN 確認）**: Step 5 のテスト PASS。
- [ ] **Step 9（OFF 凍結＋no-churn TDD — T-A4）**: 2 ファイル・ON で家系色 → `set_comparison_mode(False)` → (a) 色不変 (b) `notify` 回数=0・`_cache` 同一性 を assert。**sabotage 2 種を実証**: (1) `reapply_auto_colors` の `hue is None` の `continue` を「count-mod へ戻す」へ改変 → 色不変 assert RED。(2) invalidate/notify を `if changed` の外へ → no-churn assert RED。改変を戻して GREEN。
- [ ] **Step 10（sticky／2→1 unload／E-0 独立 TDD — T-A6/T-A7/T-A5）**:
  - T-A6: 単一で同一ファイル 3 信号 add → ON → 3 本相異バリアント（潰れない）。
  - T-A7: 2 ファイル・ON で家系色 → 1 ファイルへ unload → 生存曲線は家系色凍結・`comparison_enabled` True 保持。
  - T-A5（E-0 独立・setup 明示）: 2 つの distinct group_key で同一裸名 → **同一アクティブパネル**へ `add_signal_to_axis` で両プロット → 両 visible → `cursor_readings` の name に「bare (group_key)」併記が出る（`is_comparison_mode()` False でも）。**sabotage**: readings の `_visible_display_names` を `is_comparison_mode()` ゲートで包む → RED。
- [ ] **Step 11（VM テストスイープ — M13）**: `uv run pytest tests/gui/ -q` を実行し、`is_comparison_mode`/hue/family/badge/chip を 2 ファイルで検証する既存 E-2 VM テストの FAIL を**サイト別に**修正。判断基準:
  - テストの意図が「比較挙動の検証」→ setup に `app_vm.set_comparison_mode(True)` を明示追加。
  - テストの意図が「単一挙動（count-mod）の検証」→ フラグ OFF のまま存置し、期待値を count-mod に整合。
  - `_FakeHueResolver` を注入する isolation テスト → 存置（フラグ回帰の実検出網は GraphAreaVM 経由＋Layer B/C）。
  - 修正した全サイトを report に file:line で列挙（機械置換でないことの証跡）。
- [ ] **Step 12（ゲート＋commit）**: 全ゲート green → `feat(gui): 比較モード transient フラグ＋述語置換＋GraphAreaVM 再着色配線`

---

## Task 2: FileBrowser — 比較 affordance 対称化＋comparison_mode 購読

**Files:**
- Modify: `src/valisync/gui/viewmodels/file_browser_vm.py`（`_on_app_change` の購読タグへ `"comparison_mode"` 追加）
- Modify: `src/valisync/gui/views/file_browser_view.py`（右クリックメニューの比較 affordance を単一モードで両方隠す）
- Test: `tests/gui/test_file_browser_vm*.py`・`tests/gui/test_file_browser_view*.py`

**Interfaces:**
- Consumes: Task 1 の `AppViewModel.is_comparison_mode()`（フラグ連動済み）・`"comparison_mode"` notify。

- [ ] **Step 1（購読 TDD — T-B3）**: トグルで FileBrowser モデルが再構築される（バッジ/チップ出現/消滅）ことを書く。

```python
def test_toggle_comparison_refreshes_badge_and_chip(fb_vm_two_files):
    vm = fb_vm_two_files
    resets = []
    vm.model.modelReset.connect(lambda: resets.append(1))  # or the refresh hook used
    vm._app_vm.set_comparison_mode(True)
    assert resets, "comparison_mode toggle must trigger FileBrowser refresh"
    assert S.FILE_REFERENCE_BADGE_SUFFIX in _reference_row_text(vm)
    assert vm.chip_color(_reference_row(vm)) is not None
    vm._app_vm.set_comparison_mode(False)
    assert S.FILE_REFERENCE_BADGE_SUFFIX not in _reference_row_text(vm)
    assert vm.chip_color(_reference_row(vm)) is None
```

- [ ] **Step 2（RED 確認）**: FAIL（`_on_app_change` が `"comparison_mode"` を購読していないため refresh されない）。
- [ ] **Step 3（実装）**: `file_browser_vm.py` の `_on_app_change` タグ集合へ `"comparison_mode"` を追加:

```python
if change in ("loaded", "unloaded", "releasing", "reference", "comparison_mode"):
    self._refresh()
```

- [ ] **Step 4（GREEN 確認）**: Step 1 PASS。
- [ ] **Step 5（affordance 対称化 TDD — T-B4）**: 単一モードの右クリックは「削除」のみ・比較 ON で「基準に設定」（reference 行は disabled）＋「基準の同名信号を重ねる」（非 reference 行）が現れる。

```python
def test_context_menu_hides_comparison_affordances_in_single_mode(fb_view_two_files):
    view = fb_view_two_files  # 2 files, comparison OFF (default)
    menu = view._build_context_menu(row=1)  # non-reference row
    labels = [a.text() for a in menu.actions()]
    assert S.ACTION_SET_REFERENCE not in labels
    assert S.ACTION_OVERLAY_REFERENCE not in labels
    assert S.ACTION_REMOVE_FILE in labels

def test_context_menu_shows_comparison_affordances_when_enabled(fb_view_two_files):
    view = fb_view_two_files
    view._vm._app_vm.set_comparison_mode(True)
    menu = view._build_context_menu(row=1)
    labels = [a.text() for a in menu.actions()]
    assert S.ACTION_SET_REFERENCE in labels
    assert S.ACTION_OVERLAY_REFERENCE in labels
```

- [ ] **Step 6（RED 確認）**: FAIL（現行は単一モードでも「基準に設定」を表示）。
- [ ] **Step 7（実装）**: `file_browser_view.py` の右クリックメニュー構築（:120-135）を、比較 affordance 全体を `is_comparison_mode()` ゲートで囲う:

```python
key = self._vm.key_at(row)
if key is not None and self._vm.is_comparison_mode():
    is_ref = self._vm.is_reference(row)
    set_ref_action = menu.addAction(S.ACTION_SET_REFERENCE)
    set_ref_action.setEnabled(not is_ref)
    set_ref_action.triggered.connect(lambda *_: self._vm.set_reference(row))
    if not is_ref:
        overlay_action = menu.addAction(S.ACTION_OVERLAY_REFERENCE)
        overlay_action.triggered.connect(
            lambda *_: self.overlay_reference_requested.emit(key)
        )
```

- [ ] **Step 8（GREEN 確認＋既存テスト追随）**: Step 5 PASS。`tests/gui/test_file_browser_view*.py` の既存メニューテストのうち「単一モードで基準に設定が出る」前提を修正（サイト別）。
- [ ] **Step 9（ゲート＋commit）**: 全ゲート green → `feat(gui): FileBrowser 比較 affordance を比較モード連動へ対称化＋comparison_mode 購読`

---

## Task 3: Analyze メニュー QAction＋基準開示＋文言

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（MainWindow 所有 checkable QAction・`analyze_menu.addAction`・`_sync_analysis_actions` 内で app_vm 直読同期・トグルハンドラで基準ステータス開示）
- Modify: `src/valisync/gui/strings.py`（`ACTION_COMPARISON_MODE`・`STATUS_COMPARISON_REFERENCE_TMPL`）
- Test: `tests/gui/test_main_window*.py`（メニュー同期）・`tests/gui/test_menu_mnemonics.py`（無変更の確認）

**Interfaces:**
- Consumes: Task 1 の `app_vm.set_comparison_mode`/`comparison_enabled`/`loaded_file_keys`。

- [ ] **Step 1（メニュー同期 TDD — T-B1）**: 2 ファイルロード → `aboutToShow` 相当の同期 → 項目 enabled・unchecked。トリガ → `app_vm.comparison_enabled` True＋checked。**sabotage**: checkstate を `is_comparison_mode()` へ差し替える → 「1 ファイル＋ON」で checked が False になり RED（生フラグ厳守を捕捉）。

```python
def test_comparison_action_reflects_raw_flag_and_enabled_on_count(main_window_two_files):
    mw = main_window_two_files
    mw._sync_analysis_actions()             # aboutToShow handler
    act = mw._comparison_mode_action
    assert act.isEnabled() is True          # 2 files
    assert act.isChecked() is False         # default OFF
    act.trigger()
    assert mw.app_vm.comparison_enabled is True
    assert act.isChecked() is True

def test_comparison_action_checkstate_uses_raw_flag_not_predicate(main_window_one_file):
    mw = main_window_one_file
    mw.app_vm.set_comparison_mode(True)      # raw flag True, but 1 file
    mw._sync_analysis_actions()
    assert mw._comparison_mode_action.isChecked() is True   # raw flag, NOT is_comparison_mode()
    assert mw._comparison_mode_action.isEnabled() is False  # <2 files
```

- [ ] **Step 2（RED 確認）**: FAIL（`_comparison_mode_action` 未定義）。
- [ ] **Step 3（実装）**: `main_window.py`。MainWindow 所有の checkable QAction を作り Analyze メニューへ追加:

```python
self._comparison_mode_action = QAction(S.ACTION_COMPARISON_MODE, self)
self._comparison_mode_action.setCheckable(True)
self._comparison_mode_action.triggered.connect(self._on_toggle_comparison_mode)
analyze_menu.addSeparator()
analyze_menu.addAction(self._comparison_mode_action)
```

`_sync_analysis_actions` の末尾へ app_vm 直読同期:

```python
self._comparison_mode_action.setChecked(self.app_vm.comparison_enabled)
enabled = len(self.app_vm.loaded_file_keys) >= 2
self._comparison_mode_action.setEnabled(enabled)
if not enabled:
    self._comparison_mode_action.setToolTip(S.TOOLTIP_COMPARISON_NEEDS_TWO)
```

トグルハンドラ（基準開示 — M8）:

```python
def _on_toggle_comparison_mode(self, checked: bool) -> None:
    self.app_vm.set_comparison_mode(checked)
    if checked and self.app_vm.reference_file_key is not None:
        name = self.app_vm.session.source_name(self.app_vm.reference_file_key)
        self.statusBar().showMessage(
            S.STATUS_COMPARISON_REFERENCE_TMPL.format(name=name)
        )
```

`strings.py` へ `ACTION_COMPARISON_MODE`（& なし）・`TOOLTIP_COMPARISON_NEEDS_TWO`・`STATUS_COMPARISON_REFERENCE_TMPL`。

- [ ] **Step 4（GREEN 確認）**: Step 1 PASS。
- [ ] **Step 5（<2 無効＋checked 保持 TDD — T-B2）**: 1 ファイル → 項目 disabled。2 ファイル・ON → 1 ファイルへ unload → 項目 disabled かつ **checkstate=checked 保持**（意図的決定をロック）。
- [ ] **Step 6（ニーモニクス無変更 — M5）**: `uv run pytest tests/gui/test_menu_mnemonics.py -q` が**変更なしで PASS**することを確認（`comparison_mode` にニーモニクス非付与ゆえ G-46 walk 集合・対訳表は不変）。もし FAIL したらニーモニクスを付けてしまっている退行。
- [ ] **Step 7（ゲート＋commit）**: 全ゲート green → `feat(gui): Analyze メニュー「比較モード」トグル＋基準ファイル開示`

---

## Task 4: realgui T-C1＋凍結カタログ＋docs＋スイープ監査＋最終ゲート

**Files:**
- Modify: `tests/realgui/test_comparison_model_realclick.py`（トグルジャーニー拡張）
- Modify: `docs/design.md`（決定履歴）・`docs/uiux-adversarial-review-catalog.md`・`CLAUDE.md`
- Verify: `design_export/screenshots_catalog_{dark,light}`（01-09 差分ゼロ）

- [ ] **Step 1（realgui T-C1 拡張）**: 既存 `test_comparison_model_realclick.py` に、2 ファイルロード → 実 OS で Analyze メニュー「比較モード」クリック → 家系色が**実ピクセルで出現**（ON 前 count-mod・ON 後 青系/橙系）→ 再クリックで OFF → **家系色が凍結（count-mod へ戻らない）**を実ピクセルで実証 → ◎基準バッジの出現/消滅。エビデンススクショを `design_export/evidence_comparison_toggle/` へ保存し Read で目視、所見を report へ。
- [ ] **Step 2（realgui フル）**: `uv run pytest tests/realgui/ --realgui -q`（timeout 600000・バッチ可）。既知の順序フレークは単体再実行で切り分け。
- [ ] **Step 3（凍結カタログ差分ゼロ検証 — M16）**: 撮影 → `compare_screenshots.py`（両テーマ・`--crop-meta`）で **01-09 全状態が現行ベースライン（PR #145）と完全一致**を実証（トグルは全状態 1 ファイルで不可視 → 差分ゼロ）。想定外差分があれば原因特定。決定性 exit 0。
- [ ] **Step 4（スイープ監査 — M13）**: Task 1/2/3 で修正した既存 E-2 テストサイトを横断監査し、機械的 `set_comparison_mode(True)` 挿入が意図を消していないか・14 サイト相当を漏れなく整合させたかを report へ列挙（`rg 'set_comparison_mode' tests/` で全挿入点を確認）。
- [ ] **Step 5（docs）**:
  - `docs/design.md` 決定履歴に 1 エントリ（比較モードのユーザー切り替え・transient・Analyze メニュー・OFF 凍結・affordance 対称化・カタログ差分ゼロ・敵対的レビュー M1-M16 の要点）。
  - `docs/uiux-adversarial-review-catalog.md`: E-2 系の関連項目へ「単一/比較のユーザー切り替えを追加（2026-07-23）」注記。
  - `CLAUDE.md` の 横断/UIUX 敵対的レビュー行へ本増分の完了サマリ（E-2 に比較モードトグルを追加・次=増分F）。
- [ ] **Step 6（プランのチェックボックス更新）**: 全タスク消化済みへ。
- [ ] **Step 7（最終ゲート＋commit）**: `uv run pytest -q`・ruff・mypy green → `feat(gui): 比較モード realgui ①ゲート＋凍結検証＋docs`

## Self-Review 済み確認事項

- spec §1-§10 の全要素がタスクに 1:1（フラグ状態/述語/set API/inspect 露出/docstring 更新・GraphAreaVM 配線・FileBrowser 購読/affordance 対称化・MainWindow QAction/同期/基準開示・realgui/カタログ/docs）。
- M1-M16 の反映: transient（Global Constraints）・M2 inspect（T1 Step3）・M3 docstring（T1 Step3）・M4 QAction 配置（T3・Global）・M5 ニーモニクス（T3 Step6）・M6 checked+disabled（T3 Step5）・M7 対称化（T2）・M8 基準開示（T3 Step3）・M9 §9.4 2 系（テスト T-A7）・M10 ON 再着色専用テスト（T1 Step5）・M11 resolver 全パネル（T1 Step5 T-B6）・M12 no-churn（T1 Step9）・M13 サイト別スイープ（T1 Step11・T4 Step4）・M14/M15 E-0 独立 setup（T1 Step10 T-A5）・M16 カタログ差分ゼロ（T4 Step3）。
- 型整合: `set_comparison_mode(bool)->None`・`comparison_enabled: bool`・notify タグ `"comparison_mode"` を Interfaces に明記。
