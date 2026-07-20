# 折りたたみ可能ドック Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** File Browser / Channel Browser / Diagnostics の3ドックに共通の折りたたみ（タイトルバーのみに畳む・フロート/閉じる維持・QSettings 永続）を付ける（FU-14 実現）。

**Architecture:** 再利用可能な `CollapsibleDockTitleBar`（chevron トグル＋タイトル＋フロート＋閉じる）を `dock.setTitleBarWidget()` で3ドックに composition で差す。折りたたみ＝内容 hide＋dock の maxHeight をタイトルバー高にクランプ／展開＝クランプ解除＋`resizeDocks` で高さ復元。MainWindow が collapse 状態を QSettings 永続（restoreState 後に再適用）。

**Tech Stack:** PySide6（QDockWidget・setTitleBarWidget・resizeDocks）・既存 `theme/icons.py`（Lucide 着色）・既存 QSettings 永続基盤・realgui Layer C。

**Spec:** [docs/superpowers/specs/2026-07-20-collapsible-docks-design.md](../specs/2026-07-20-collapsible-docks-design.md)

## Global Constraints

- **トークン/エクスポート変更なし** — tokens.py/qss.py/export は触らない。色は既存 `chrome_text`（chevron 着色は `icons.icon()` 経由で自動）。
- 対象は3ドックのみ（file_dock / channel_dock / diagnostics_dock）。畳みは**タイトルのみ**（Diagnostics に件数バッジ等の特別要約は出さない）。フロート/閉じるは維持。
- collapse 状態は Qt の `saveState()` に乗らない → QSettings 別キー `dockCollapsed`（`{objectName: bool}`）で永続。`_restore_state()`/`_reset_layout()` の後に再適用（restoreState は独自状態を戻さない — memory gui_restorestate_resets_dock_corner_config と同型）。
- SVG は `currentColor` のみ（`tests/gui/test_theme_icons.py` が検証）。vendored Lucide は unpkg pinned v1.24.0・無改変。
- **collapse の実効（実際に縮む）は Layer C 実機でしか確証できない**（memory gui_isvisible_true_for_offscreen_hidden_dock: offscreen は隠しドックでも isVisible True・縮まない）。Layer B は状態フラグ/maxHeight/Signal/ラウンドトリップまで。
- QSettings は conftest 隔離済み（`_ORG/_APP`）。
- コミット前ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全て exit 0（全リポジトリ実行・出力そのまま報告）。

---

### Task 1: chevron アイコンの vendoring＋登録

**Files:**
- Create: `src/valisync/gui/theme/icons/lucide/chevron-down.svg`・`chevron-right.svg`（unpkg pinned・無改変）
- Modify: `src/valisync/gui/theme/icons.py`（ICONS レジストリ）
- Test: `tests/gui/test_theme_icons.py`

**Interfaces:**
- Produces: `icons.icon("chevron_down") -> QIcon`・`icons.icon("chevron_right") -> QIcon`（Task 2 が消費）

- [ ] **Step 1: SVG を pinned unpkg から取得（無改変・r5 と同じ手順）**

```bash
curl -fsSL https://unpkg.com/lucide-static@1.24.0/icons/chevron-down.svg \
  -o src/valisync/gui/theme/icons/lucide/chevron-down.svg
curl -fsSL https://unpkg.com/lucide-static@1.24.0/icons/chevron-right.svg \
  -o src/valisync/gui/theme/icons/lucide/chevron-right.svg
```

取得後、両ファイルが `stroke="currentColor"` を含み固定色（hex/rgb）を持たないことを目視確認（Lucide の標準形。もし `fill`/`stroke` にリテラル色があれば規約違反なので取得元を確認）。`package-data` の glob は `icons/**/*.svg`（r5）で自動包含・pyproject 変更不要。LICENSES.md は Lucide ISC を既に網羅・追記不要。

- [ ] **Step 2: 失敗するテストを書く**

`tests/gui/test_theme_icons.py` に、chevron 2個が登録され着色 QIcon を返すことのテストを追加（既存の icon() テストの書式に合わせる。`qapp` fixture を使う）:

```python
def test_chevron_icons_registered_and_render(qapp):
    from valisync.gui.theme import icons

    for name in ("chevron_down", "chevron_right"):
        ico = icons.icon(name)
        assert not ico.isNull(), name
```

（SVG 色規約テスト＝`currentColor` のみは既存の全 .svg 走査テストが新ファイルも自動対象にする。もし対象がハードコードリストなら chevron 2件を追加する — 実装時に test_theme_icons.py の該当テストを確認。）

- [ ] **Step 3: RED 確認**

Run: `uv run pytest tests/gui/test_theme_icons.py -v`
Expected: `test_chevron_icons_registered_and_render` が FAIL（KeyError: 'chevron_down'）

- [ ] **Step 4: ICONS に登録**

`src/valisync/gui/theme/icons.py` の `ICONS` に追加:

```python
    "chevron_down": "lucide/chevron-down.svg",
    "chevron_right": "lucide/chevron-right.svg",
```

- [ ] **Step 5: GREEN＋ゲート＋コミット**

```bash
uv run pytest tests/gui/test_theme_icons.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/icons/lucide/chevron-down.svg src/valisync/gui/theme/icons/lucide/chevron-right.svg src/valisync/gui/theme/icons.py tests/gui/test_theme_icons.py
git commit -m "feat(theme): chevron アイコンを vendoring+登録 (collapsible-docks Task 1)"
```

---

### Task 2: CollapsibleDockTitleBar コンポーネント

**Files:**
- Create: `src/valisync/gui/views/collapsible_dock_title_bar.py`
- Test: `tests/gui/test_collapsible_dock_title_bar.py`

**Interfaces:**
- Consumes: `icons.icon("chevron_down"/"chevron_right")`（Task 1）
- Produces: `CollapsibleDockTitleBar(dock: QDockWidget, main_window: QMainWindow, title: str, parent=None)` with `collapsed_changed = Signal(bool)`・`is_collapsed() -> bool`・`set_collapsed(collapsed: bool) -> None`（Task 3 が消費）

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_collapsible_dock_title_bar.py`:

```python
"""CollapsibleDockTitleBar — ドック共通の折りたたみタイトルバー (増分C Task 2)。"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]


def _dock_in_window(qtbot: QtBot):
    from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow

    win = QMainWindow()
    dock = QDockWidget("D", win)
    dock.setObjectName("d")
    content = QLabel("content")
    dock.setWidget(content)
    from PySide6.QtCore import Qt

    win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    qtbot.addWidget(win)
    return win, dock, content


def test_collapse_hides_content_and_clamps_maxheight(qtbot: QtBot):
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    dock.setTitleBarWidget(bar)
    win.show()
    qtbot.waitExposed(win)
    assert not bar.is_collapsed()
    bar.set_collapsed(True)
    assert bar.is_collapsed()
    assert not content.isVisible()  # 内容 hide
    assert dock.maximumHeight() <= bar.sizeHint().height() + 4  # タイトル高にクランプ
    bar.set_collapsed(False)
    assert not bar.is_collapsed()
    assert content.isVisible()
    assert dock.maximumHeight() >= 10000  # クランプ解除 (QWIDGETSIZE_MAX)


def test_toggle_emits_collapsed_changed(qtbot: QtBot):
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    win.show()
    seen: list[bool] = []
    bar.collapsed_changed.connect(seen.append)
    bar._toggle_button.click()  # トグルボタン実クリック相当
    bar._toggle_button.click()
    assert seen == [True, False]


def test_float_and_close_buttons(qtbot: QtBot):
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    dock.setTitleBarWidget(bar)
    win.show()
    assert not dock.isFloating()
    bar._float_button.click()
    assert dock.isFloating()  # フロート トグル
    bar._close_button.click()
    assert not dock.isVisible()  # 閉じる
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_collapsible_dock_title_bar.py -v`
Expected: ImportError（モジュール未作成）

- [ ] **Step 3: 実装**

`src/valisync/gui/views/collapsible_dock_title_bar.py`:

```python
"""ドック共通の折りたたみタイトルバー (collapsible-docks 増分C)。

QDockWidget に最小化フラグは無いため setTitleBarWidget で差す。既定タイトルバー
(フロート/閉じる)を置換するので、それらを自前で持つ。折りたたみ=内容 hide+
dock の maxHeight をタイトルバー高へクランプ、展開=クランプ解除+resizeDocks で
高さ復元 (Qt はクランプ解除だけでは自動再拡大しない場合があるため)。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QToolButton,
    QWidget,
)

from valisync.gui.theme import icons

_QWIDGETSIZE_MAX = 16777215  # Qt QWIDGETSIZE_MAX (import 不確実性を避け定数化)
_DEFAULT_EXPANDED_H = 180  # 復元時に前回高が無い場合の既定 (px)


class CollapsibleDockTitleBar(QWidget):
    """chevron トグル+タイトル+フロート+閉じるを持つドックタイトルバー。"""

    collapsed_changed = Signal(bool)

    def __init__(
        self,
        dock: QDockWidget,
        main_window: QMainWindow,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dock = dock
        self._main_window = main_window
        self._collapsed = False
        self._expanded_height = _DEFAULT_EXPANDED_H

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        self._toggle_button = QToolButton()
        self._toggle_button.setAutoRaise(True)
        self._toggle_button.setIcon(icons.icon("chevron_down"))
        self._toggle_button.setToolTip("折りたたむ / 展開")
        self._toggle_button.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        lay.addWidget(self._toggle_button)

        self._title = QLabel(title)
        lay.addWidget(self._title)
        lay.addStretch(1)

        self._float_button = QToolButton()
        self._float_button.setAutoRaise(True)
        self._float_button.setText("❐")
        self._float_button.setToolTip("フロート")
        self._float_button.clicked.connect(
            lambda: self._dock.setFloating(not self._dock.isFloating())
        )
        lay.addWidget(self._float_button)

        self._close_button = QToolButton()
        self._close_button.setAutoRaise(True)
        self._close_button.setText("✕")
        self._close_button.setToolTip("閉じる")
        self._close_button.clicked.connect(self._dock.close)
        lay.addWidget(self._close_button)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        content = self._dock.widget()
        if collapsed:
            # 現在高を控えてから畳む (展開時の復元に使う)。
            h = self._dock.height()
            if h > self.sizeHint().height():
                self._expanded_height = h
            if content is not None:
                content.hide()
            self._dock.setMaximumHeight(self.sizeHint().height())
            self._toggle_button.setIcon(icons.icon("chevron_right"))
        else:
            self._dock.setMaximumHeight(_QWIDGETSIZE_MAX)
            if content is not None:
                content.show()
            self._toggle_button.setIcon(icons.icon("chevron_down"))
            # クランプ解除だけでは自動再拡大しないことがあるため高さを戻す。
            self._main_window.resizeDocks(
                [self._dock], [self._expanded_height], Qt.Orientation.Vertical
            )
        self.collapsed_changed.emit(collapsed)
```

- [ ] **Step 4: GREEN＋ゲート＋コミット**

```bash
uv run pytest tests/gui/test_collapsible_dock_title_bar.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/collapsible_dock_title_bar.py tests/gui/test_collapsible_dock_title_bar.py
git commit -m "feat(gui): CollapsibleDockTitleBar (collapsible-docks Task 2)"
```

（❐/✕ はフロート/閉じるの暫定グリフ。SVG 化は絵文字グリフ置換 follow-up と合流させる — 本増分ではトークン/アイコン最小追加に留める。）

---

### Task 3: MainWindow 配線＋QSettings 永続

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_main_window.py`（または既存の main window テストファイル）

**Interfaces:**
- Consumes: `CollapsibleDockTitleBar`（Task 2）
- Produces: `MainWindow` の3ドックが折りたたみタイトルバーを持ち collapse 状態が QSettings 永続

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_main_window.py` 末尾に追加（既存の `qtbot`/`build_main_window` 構成に合わせる。QSettings は conftest 隔離済み）:

```python
def test_docks_have_collapsible_title_bars(qtbot):
    from valisync.gui.app import build_main_window
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win = build_main_window()
    qtbot.addWidget(win)
    for dock in (win.file_dock, win.channel_dock, win.diagnostics_dock):
        assert isinstance(dock.titleBarWidget(), CollapsibleDockTitleBar), dock.objectName()


def test_collapse_state_roundtrips_through_qsettings(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.file_dock.titleBarWidget().set_collapsed(True)
    win.save_state()  # closeEvent 相当
    win2 = build_main_window()
    qtbot.addWidget(win2)
    assert win2.file_dock.titleBarWidget().is_collapsed()
    assert not win2.channel_dock.titleBarWidget().is_collapsed()


def test_reset_layout_expands_all_docks(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.diagnostics_dock.titleBarWidget().set_collapsed(True)
    win._reset_layout()
    assert not win.diagnostics_dock.titleBarWidget().is_collapsed()
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_main_window.py -k "collapsible or collapse_state or reset_layout_expands" -v`
Expected: FAIL（titleBarWidget が None/既定・永続なし）

- [ ] **Step 3: 実装**

`main_window.py` の3ドック生成の後（`_update_central()` 付近か各 addDockWidget の後）で、3ドックにタイトルバーを差す。import 追加:

```python
from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar
```

diagnostics_dock 生成の後（142行付近）に配線ブロックを追加:

```python
        # ── 折りたたみタイトルバー (増分C・FU-14) ────────────────────────────
        self._collapsible_bars: dict[str, CollapsibleDockTitleBar] = {}
        for dock, title in (
            (self.file_dock, "File Browser"),
            (self.channel_dock, "Channel Browser"),
            (self.diagnostics_dock, "Diagnostics"),
        ):
            bar = CollapsibleDockTitleBar(dock, self, title)
            dock.setTitleBarWidget(bar)
            bar.collapsed_changed.connect(self._save_dock_collapsed)
            self._collapsible_bars[dock.objectName()] = bar
```

`save_state`（519行付近）に collapse 状態の保存を追加:

```python
    def save_state(self) -> None:
        """Persist window geometry and dock arrangement to QSettings."""
        settings = QSettings(_ORG, _APP)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        settings.setValue("dockCollapsed", self._dock_collapsed_map())
```

ヘルパと保存スロットを追加（`save_state` の近く）:

```python
    def _dock_collapsed_map(self) -> dict:
        return {
            name: bar.is_collapsed() for name, bar in self._collapsible_bars.items()
        }

    def _save_dock_collapsed(self, *_: object) -> None:
        settings = QSettings(_ORG, _APP)
        settings.setValue("dockCollapsed", self._dock_collapsed_map())

    def _apply_saved_collapse(self) -> None:
        """QSettings の collapse 状態を各タイトルバーへ再適用。

        restoreState はドックのサイズ/配置を戻すが collapse (内容 hide+maxHeight)
        は runtime プロパティで乗らないため、_restore_state/_reset_layout の後に
        明示再適用する (corner 再適用と同型)。
        """
        settings = QSettings(_ORG, _APP)
        saved = settings.value("dockCollapsed") or {}
        for name, bar in self._collapsible_bars.items():
            collapsed = bool(saved.get(name, False)) if isinstance(saved, dict) else False
            bar.set_collapsed(collapsed)
```

`_restore_state`（530行付近）の末尾に `self._apply_saved_collapse()` を追加（restoreState の後）。ただし `_restore_state` は `__init__` で `_collapsible_bars` 設定より前に呼ばれる可能性があるため、**バー配線は `_restore_state()` 呼び出しより前**に置くこと（配線ブロックを 138-142 行の diagnostics_dock 直後＝255行の `_restore_state()` より前に置けば満たす）。

`_reset_layout`（553行付近）に全展開＋再適用を追加:

```python
    def _reset_layout(self) -> None:
        """Restore the default dock/toolbar arrangement captured at startup (SH-11)."""
        self.restoreState(self._default_state)
        self._apply_dock_corners()  # restoreState reset the FU-10 corner; re-apply
        for bar in self._collapsible_bars.values():
            bar.set_collapsed(False)  # 既定=全展開
```

- [ ] **Step 4: GREEN＋full suite＋ゲート＋コミット**

```bash
uv run pytest tests/gui/test_main_window.py -k "collapsible or collapse_state or reset_layout_expands" -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
```

（既存の main window テストが titleBarWidget 前提を持つ場合は honest に更新して報告。特にドックのフロート/閉じる/タイトルの既存テストがカスタムバー経由でも通るか確認。）

```bash
git add src/valisync/gui/views/main_window.py tests/gui/test_main_window.py
git commit -m "feat(gui): 3ドックへ折りたたみタイトルバー配線+QSettings 永続 (collapsible-docks Task 3)"
```

---

### Task 4: realgui（実機で実際に縮む・フロート/閉じる）

**Files:**
- Create: `tests/realgui/test_collapsible_docks_realclick.py`

コード整備はサブエージェント、実 `--realgui` 実行はコントローラ（実機・警告要）。

- [ ] **Step 1: realgui テストを書く（コレクションまで確認）**

`tests/realgui/test_collapsible_docks_realclick.py`: build_main_window→表示→file_dock のタイトルバーの折りたたみトグルを**実クリック**→ドックの高さが実際にタイトルバー高付近まで**縮む**（`dock.height()` を実測・collapse 前後で有意に減少）＋内容非可視（`visibleRegion`/画面内 geometry で判定 — memory gui_isvisible_true_for_offscreen_hidden_dock: isVisible では不可）。再クリックで展開し高さ復元。フロートボタン実クリックで `isFloating()` True。実 OS 入力は `tests/realgui/_realgui_input` の `at`/`LDOWN`/`LUP`、トグルボタンの物理座標はタイトルバー内ボタン geometry から算出。`skip_unless_real_display`。

collect 確認（実入力なし・安全）:
```bash
uv run pytest tests/realgui --collect-only -q
```

- [ ] **Step 2: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/realgui/test_collapsible_docks_realclick.py
git commit -m "test(realgui): 折りたたみドックの実機縮小/フロート (collapsible-docks Task 4)"
```

- [ ] **Step 3: 実 --realgui（コントローラ）**

```bash
uv run pytest tests/realgui --realgui
```

Expected: 全 PASS。**特に「ドックが実際に縮む」「展開で高さ復元」を実機で確認**（Qt ドックレイアウトの maxHeight/resizeDocks が効くか＝FU-14 defer の核心。効かなければ resizeDocks 引数/呼出順を realgui 駆動で調整）。フロート/閉じるの実動作＋journey smoke。

---

### Task 5: 実機検証＋成果物更新（コントローラ）

コード変更なし。実ディスプレイ必須。

- [ ] **Step 1: 前後差分（タイトルバー変化の確認）**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_incrC_dark --theme dark
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_incrC_dark
```

Expected: exit 1。差分が **3ドックのタイトルバー領域に限定**（Qt 既定タイトルバー→カスタムバー）されることを確認。

- [ ] **Step 2: 折りたたみカタログショット追加＋ベースライン/カタログ再生成**

`scripts/capture_ui_screenshots.py` の `--catalog` 分岐に、Diagnostics（または代表1ドック）を collapse した状態の `09_collapsed` 撮影を追加（`window._collapsible_bars["diagnostics_dock"].set_collapsed(True)` → grab）。撮影実装は既存 catalog ショット（06/07/08）の書式に合わせる。

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_baseline --theme dark
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_dark --theme dark --catalog
uv run python scripts/export_design_tokens.py --theme dark --out design_export
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_light --theme light --catalog
uv run python scripts/export_design_tokens.py --theme light --out design_export
```

（トークン変更なしなので export の tokens.css/json/cards は不変。Ground Truth スクショのみ更新＋09_collapsed 追加。）

---

### Task 6: design.md＋最終レビュー・PR・再同期（コントローラ）

**Files:**
- Modify: `docs/design.md`（決定履歴）

- [ ] **Step 1: docs/design.md 決定履歴へ追記**

```markdown
- 2026-07-20: File/Channel/Diagnostics の3ドックに共通の折りたたみを追加（トークン
  変更なし・構造 UI）。QDockWidget に最小化フラグが無いため `CollapsibleDockTitleBar`
  を setTitleBarWidget で composition・畳み=内容 hide+maxHeight クランプ・QSettings 永続。
  過去 defer した FU-14 を実現。出典: inbox 決定メモ③（Diagnostics ドロワー化）＋
  ユーザー要望「File/Channel も折りたたみ可能に」で3ドック共通へ拡張。設計は
  [collapsible-docks spec](superpowers/specs/2026-07-20-collapsible-docks-design.md)。PR #TBD。
```

- [ ] **Step 2: 最終ブランチレビュー（fable — memory feedback_important_reviews_use_fable）→ 指摘対応**
- [ ] **Step 3: design.md PR 番号記入 → push → `gh pr create` → CI watch**
- [ ] **Step 4: DesignSync 再同期（Ground Truth 更新＋09_collapsed・トークン不変）**
- [ ] **Step 5: ユーザーへ完了報告（merge はユーザー判断）。merge 後に CLAUDE.md docs PR。**
