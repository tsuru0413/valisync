# アクティブパネル枠の複数プロット条件化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** タブ内パネルが1枚のときはアクティブ枠を描かず、2枚以上のときのみ従来どおりアクティブパネルへ amber 枠を描く（UIUX 再設計プログラム増分A・クイックウィン）。

**Architecture:** `GraphAreaView._sync_active_frames()`（描画の単一集約点・rebuild 後と "active_panel" 軽量通知の両経路が通る）にタブ内パネル数の条件を1つ追加。VM の `active_panel_index` 契約（追跡・Add/Export 配送）・軸 affordance・トークン値は不変。

**Tech Stack:** PySide6（既存 `_active_frame` overlay 機構）・既存テスト基盤（Layer A/B + realgui Layer C）。

**Spec:** [docs/superpowers/specs/2026-07-18-active-frame-multi-panel-design.md](../specs/2026-07-18-active-frame-multi-panel-design.md)

## Global Constraints

- トークン値・qss・view のスタイルは一切変えない（描画**条件**のみ）。src に色リテラル禁止（test_theme_guard が検出）。
- VM（graph_area_vm.py）は変更しない — 変更は `graph_area_view.py` の `_sync_active_frames` と Layer B テストのみ。
- **DP15 の意図的 supersession**: 既存 `test_single_panel_shows_frame`（「1枚でも枠は出す(一貫性)」）は本増分が覆す過去の設計判断。削除でなく**反転**し、docstring に supersession の出典（spec）を記録する。
- コミット前ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全て exit 0（touched-files にスコープせず全リポジトリで実行し出力をそのまま報告）。

---

### Task 1: `_sync_active_frames` 条件分岐＋Layer B テスト

**Files:**
- Modify: `src/valisync/gui/views/graph_area_view.py`（`_sync_active_frames`・222行付近）
- Test: `tests/gui/test_active_panel.py`（`test_single_panel_shows_frame` の反転＋新規2本）

**Interfaces:**
- Consumes: `GraphAreaVM.active_panel_index(tab_index) -> int`・`GraphAreaVM.panels(tab_index) -> list[GraphPanelVM]`・`GraphAreaVM.add_panel(tab_index)`・`GraphAreaVM.remove_panel(tab_index, panel_index)`（全て既存）
- Produces: 変更後の描画規則（後続タスクの実機検証が前提にする）

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_active_panel.py` の `test_single_panel_shows_frame`（152行付近）を**反転**して置換（テスト名も変更）:

```python
def test_single_panel_hides_frame(qtbot: QtBot, session: Session) -> None:
    """増分A: パネル1枚なら枠を描かない — DP15「1枚でも枠(一貫性)」を意図的に
    supersede (spec 2026-07-18-active-frame-multi-panel)。1枚時のアクティブは
    自明で枠は情報を運ばず、波形から視線を奪うのみ (UIUX 監査 課題C)。
    追跡/配送 (Add/Export のアクティブ配送) は不変。"""
    vm = GraphAreaVM(AppViewModel(session))
    area = GraphAreaView(vm, panel_factory=lambda p: GraphPanelView(p))
    qtbot.addWidget(area)
    area.show()
    qtbot.waitExposed(area)
    only = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    assert not only._active_frame.isVisible()
```

同ファイル末尾（`test_frame_reapplied_after_rebuild` の後）に新規2本を追加:

```python
def test_frame_appears_when_second_panel_added(qtbot: QtBot, session: Session) -> None:
    """1→2枚: add_panel (自動アクティブ) で新パネルにのみ枠が出る。"""
    vm = GraphAreaVM(AppViewModel(session))
    area = GraphAreaView(vm, panel_factory=lambda p: GraphPanelView(p))
    qtbot.addWidget(area)
    area.show()
    qtbot.waitExposed(area)
    vm.add_panel(0)
    first = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    second = area.tabs.widget(0).widget(1)  # type: ignore[attr-defined]
    assert second._active_frame.isVisible()
    assert not first._active_frame.isVisible()


def test_frame_disappears_when_second_panel_removed(
    qtbot: QtBot, area_with_two_panels: tuple[GraphAreaView, GraphAreaVM]
) -> None:
    """2→1枚: remove_panel 後は残パネルがアクティブでも枠なし。"""
    area, vm = area_with_two_panels
    vm.remove_panel(0, 1)
    only = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    assert vm.active_panel_index(0) == 0
    assert not only._active_frame.isVisible()
```

（`Session`/`AppViewModel`/`GraphAreaVM`/`GraphAreaView`/`GraphPanelView`/`area_with_two_panels` は既にこのファイルで import/定義済み — 旧 `test_single_panel_shows_frame` が使っていたものをそのまま使う。）

- [ ] **Step 2: RED を確認**

Run: `uv run pytest tests/gui/test_active_panel.py -v`
Expected: `test_single_panel_hides_frame`・`test_frame_disappears_when_second_panel_removed` が FAIL（現行は1枚でも枠表示）。`test_frame_appears_when_second_panel_added` は現行でも PASS（新挙動の保存側）。

- [ ] **Step 3: 実装**

`src/valisync/gui/views/graph_area_view.py` の `_sync_active_frames` を置換:

```python
    def _sync_active_frames(self) -> None:
        """Re-apply the active-panel frame from VM state (rebuild 後と "active_panel")。

        枠はタブ内にパネルが2枚以上あるときのみ描く — 1枚ならアクティブは自明で
        枠は情報を運ばない (増分A・DP15「1枚でも枠」を意図的に supersede)。
        追跡/配送 (active_panel_index) は不変。
        """
        for tab_index, panel_index, widget in self._panel_views:
            widget.set_panel_active(
                panel_index == self.vm.active_panel_index(tab_index)
                and len(self.vm.panels(tab_index)) >= 2
            )
```

- [ ] **Step 4: GREEN＋full suite**

Run: `uv run pytest tests/gui/test_active_panel.py -v` → 全 PASS
Run: `uv run pytest` → 全 PASS（他の fallout が出たら座標/前提を確認し honest に更新して報告 — 隠蔽・許容緩和で誤魔化さない）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/graph_area_view.py tests/gui/test_active_panel.py
git commit -m "feat(gui): アクティブパネル枠を複数プロット時のみに (UIUX 増分A Task 1)"
```

---

### Task 2: 実機検証＋ベースライン/カタログ/エクスポート更新（メインセッション駆動）

コード変更なし。実ディスプレイ必須（撮影中はマウス/キーボード非接触）。

- [ ] **Step 1: 前後差分で「意図差分のみ」を実証**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_incrA_dark --theme dark
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_incrA_dark
```

Expected: exit 1。差分の空間分布解析（diffmap）で **02-05 の差分が旧 amber 枠の矩形線上に限定**されることを確認（01_welcome はプロット無しのため差分ゼロのはず）。無関係領域の差分ゼロ。

- [ ] **Step 2: 2パネル時の枠を実機目視**

一時スクリプト（scratchpad・非コミット）で `build_main_window` → fixture 読込 → `graph_area_vm.add_panel(0)` → スクショ。アクティブパネルにのみ amber 枠が出ることを目視確認。

- [ ] **Step 3: ベースライン差し替え＋カタログ＋エクスポート再生成**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_baseline --theme dark
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_dark --theme dark --catalog
uv run python scripts/export_design_tokens.py --theme dark --out design_export
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_light --theme light --catalog
uv run python scripts/export_design_tokens.py --theme light --out design_export
```

Expected: 各テーマ `exported 18 files`。

---

### Task 3: design.md 決定履歴＋realgui 全数＋ゲート

**Files:**
- Modify: `docs/design.md`（決定履歴に運用反復2を追記）

- [ ] **Step 1: docs/design.md 決定履歴へ追記**

決定履歴セクションの既存エントリ（2026-07-17 chrome_frame）の後に追加:

```markdown
- 2026-07-19: アクティブパネル枠を複数プロット時のみに（トークン値変更なし・適用
  条件のみ）。単一プロットの常時 amber 枠は情報を運ばず視線を奪う（UIUX 監査
  課題C）— DP15「1枚でも枠（一貫性）」を意図的に supersede。出典:
  claude.ai/design 検討の持ち帰りメモ（2026-07-18 UIUX コンセプト）＋カード
  「コンセプトとメイン画面案」3a/4a。設計は
  [active-frame spec](superpowers/specs/2026-07-18-active-frame-multi-panel-design.md)。
  PR #TBD（Task 4 で記入）。
```

- [ ] **Step 2: realgui 全数＋journey smoke（メインセッション/コントローラが実行）**

```bash
uv run pytest tests/realgui --realgui
```

Expected: 全 PASS。`test_active_panel_flow` は2パネル構成のため枠 assert は新挙動でも有効（変更不要の見込み — FAIL したら前提を確認し honest に更新して報告）。

- [ ] **Step 3: ゲート＋コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add docs/design.md
git commit -m "docs(design): 増分A を決定履歴に記録 (UIUX 増分A Task 3)"
```

---

### Task 4: 最終レビュー・PR・再同期（コントローラ）

- [ ] Step 1: 最終ブランチレビュー（最上位モデル）→ 指摘対応
- [ ] Step 2: design.md の PR 番号記入 → push → `gh pr create` → CI watch
- [ ] Step 3: DesignSync 再同期（dark/light 各18ファイル・新規パスなし）
- [ ] Step 4: ユーザーへ完了報告（merge はユーザー判断）。merge 後に CLAUDE.md docs PR。
