# gui-shell-controls 増分3（シェル chrome）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `main_window.py` のシェル chrome を仕上げ、SH-05（ショートカット/mnemonic）・SH-12（ドックトグルのツールバー化）・SH-11（Reset Layout）・SH-14（アイコン/ツールチップ/バージョン）を解消し gui-shell-controls を完結する。

**Architecture:** `ShellActions`（QAction レジストリ・増分1a）が open/export にアイコン/ショートカット/ツールチップを既に付与済み。本増分はその上に不足分（open_folder/Exit ショートカット・mnemonic・ドックトグルのツールバー搭載・Reset Layout・data_explorer アイコン・About バージョン）を配線する。新規 VM ロジックは無い（View 層のみ・MVVM 不変）。

**Tech Stack:** Python 3.12+ / PySide6 (Qt6) / pytest + pytest-qt。

## Global Constraints

- 設計 spec: [2026-07-08-gui-shell-controls-r3-shell-chrome-design.md](../specs/2026-07-08-gui-shell-controls-r3-shell-chrome-design.md)。
- **MVVM 不変**: ViewModel を変更しない（View 層 `main_window.py`＋`shell_actions.py` のみ）。既存の central_stack/welcome・Recent・永続化・cross-view 配線を壊さない。
- **全角約物のみ禁止**（コード内・コメント/docstring）: `（）＋−`（ruff RUF002/003）を使わず ASCII `()` `+` `-`。**日本語カナ漢字・`。`・`・`・em dash `—` はコードベース標準で可（ruff 通過）**。日本語 UI 文字列（メニュー/ツールチップ/About）は可（RUF001 は該当行 `# noqa: RUF001`。「開く…」等の三点リーダ `…` も UI リテラルで既存使用）。
- 品質ゲート（コミット前に全通過）: `uv run pytest` / `uv run ruff check`（exit 0・`| tail` 禁止）/ `uv run ruff format --check` / `uv run mypy src/`。
- GUI テストレイヤー: Layer A/B 必須（headless）＋新入力経路ごとに Layer C スケルトン。テストは `tests/gui/test_main_window_central.py` の `_mw(qtbot, tmp_path)` パターン（`MainWindow(AppViewModel())`＋QSettings 分離）に倣う。

---

## File Structure

| ファイル | 責務 | 種別 |
|---|---|---|
| `src/valisync/gui/views/shell_actions.py` | open_folder に Ctrl+Shift+O 付与 | 変更 |
| `src/valisync/gui/views/main_window.py` | mnemonic・Exit ショートカット・ドックトグルのツールバー搭載・Reset Layout（既定捕捉＋アクション）・data_explorer アイコン/ツールチップ・About バージョン（`_about_text`） | 変更 |
| `tests/gui/test_shell_chrome.py` | SH-05/11/12/14 の Layer A/B | 新規 |
| `tests/realgui/test_shell_chrome_flow.py` | Layer C（ツールバートグル・Reset Layout） | 新規 |
| `docs/audit-findings-catalog.md` / `docs/roadmap.md` | SH-05/11/12/14 解消・gui-shell-controls 完結反映 | 変更 |

**依存順**: Task 1（SH-05）→ 2（SH-12）→ 3（SH-11）→ 4（SH-14）は同一 `main_window.py`（Task 1 のみ `shell_actions.py` も）。Task 5（realgui）・6（docs）は最後。

---

## Task 1: SH-05 ショートカット/mnemonic

**Files:**
- Modify: `src/valisync/gui/views/shell_actions.py`・`src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_shell_chrome.py`

**Interfaces:**
- Consumes: `ShellActions._add(key, text, icon, shortcut, status)`（:44）・`file_menu`/`help_menu`/`view_menu`（`main_window.py:150-168`）。
- Produces: `open_folder` shortcut = `Ctrl+Shift+O`。`self.action_exit`（Exit・`QKeySequence.StandardKey.Quit`）。メニュータイトル mnemonic（`&File`/`&View`/`&Analyze`/`&Help`）・`E&xit`・`&About ValiSync`。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_shell_chrome.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def _mw(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    mw = MainWindow(AppViewModel())
    mw.recent_files = mw.recent_files.__class__(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(mw)
    return mw


def test_open_folder_has_shortcut(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    assert mw.shell_actions.action("open_folder").shortcut() == QKeySequence(
        "Ctrl+Shift+O"
    )


def test_exit_has_quit_shortcut(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    assert mw.action_exit.shortcut() == QKeySequence(QKeySequence.StandardKey.Quit)


def test_menu_titles_have_mnemonics(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    titles = [a.text() for a in mw.menuBar().actions()]
    assert "&File" in titles
    assert "&View" in titles
    assert "&Help" in titles
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_shell_chrome.py -q`
Expected: FAIL（open_folder shortcut 空・`action_exit` 無し・タイトルに `&` 無し）

- [ ] **Step 3: 実装**

`shell_actions.py` の open_folder 呼出しの shortcut を変更:
```python
        self._add(
            "open_folder",
            "フォルダを開く…",  # noqa: RUF001
            style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            "Ctrl+Shift+O",
            "データソースフォルダを登録する",
        )
```
（`…` で RUF001 が出れば当該行 noqa。既存の他 `_add` 呼出しに合わせる。）

`main_window.py` のメニュー構築（:149-168）を mnemonic 化＋Exit ショートカット:
```python
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.shell_actions.action("open"))
        file_menu.addAction(self.shell_actions.action("open_folder"))
        self.recent_menu = file_menu.addMenu("Recent Files")
        file_menu.addAction(self.shell_actions.action("export"))
        file_menu.addSeparator()
        self.action_exit = file_menu.addAction("E&xit")
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_exit.triggered.connect(self.close)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.file_dock.toggleViewAction())
        view_menu.addAction(self.channel_dock.toggleViewAction())
        view_menu.addAction(self.diagnostics_dock.toggleViewAction())

        self.menuBar().addMenu("&Analyze")
        help_menu = self.menuBar().addMenu("&Help")
        about = help_menu.addAction("&About ValiSync")
        about.triggered.connect(self._show_about)
```
import: `QKeySequence` を `from PySide6.QtGui import ...` に統合（既存 QAction 等の行）。

- [ ] **Step 4: パス確認＋既存無回帰**

```bash
uv run pytest tests/gui/test_shell_chrome.py tests/gui/test_main_window_central.py -q
```

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/shell_actions.py src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/shell_actions.py src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py
uv run mypy src/valisync/gui/views/shell_actions.py src/valisync/gui/views/main_window.py
git add src/valisync/gui/views/shell_actions.py src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py
git commit -m "feat(gui): シェルにショートカット/mnemonic — open_folder=Ctrl+Shift+O・Exit=Quit・&メニュー（SH-05）"
```

---

## Task 2: SH-12 ドック表示トグルのツールバー化

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_shell_chrome.py`（追記）

**Interfaces:**
- Consumes: `self.file_dock`/`channel_dock`/`diagnostics_dock`（既存 QDockWidget・`toggleViewAction()`）・ツールバー（`main_toolbar`・:171）。
- Produces: ツールバーに3ドックの `toggleViewAction()` を搭載（View メニューと同一 QAction＝状態連動）。

- [ ] **Step 1: 失敗するテストを書く（追記）**

```python
def test_toolbar_has_dock_toggles(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QToolBar

    mw = _mw(qtbot, tmp_path)
    toolbar = mw.findChild(QToolBar, "main_toolbar")
    assert toolbar is not None
    toolbar_actions = toolbar.actions()
    assert mw.file_dock.toggleViewAction() in toolbar_actions
    assert mw.channel_dock.toggleViewAction() in toolbar_actions
    assert mw.diagnostics_dock.toggleViewAction() in toolbar_actions


def test_toolbar_toggle_hides_dock(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    mw.show()
    qtbot.waitExposed(mw)
    toggle = mw.file_dock.toggleViewAction()
    assert mw.file_dock.isVisible()
    toggle.trigger()  # ツールバーボタンと同一 action
    assert not mw.file_dock.isVisible()
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_shell_chrome.py -q`
Expected: FAIL（ツールバーに toggle が無い）

- [ ] **Step 3: 実装**

`main_window.py` のツールバー構築（:171-178）末尾に追加:
```python
        toolbar.addSeparator()
        toolbar.addAction(self.file_dock.toggleViewAction())
        toolbar.addAction(self.channel_dock.toggleViewAction())
        toolbar.addAction(self.diagnostics_dock.toggleViewAction())
```

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_shell_chrome.py -q`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py
uv run mypy src/valisync/gui/views/main_window.py
git add src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py
git commit -m "feat(gui): ドック表示トグルをツールバーに追加（SH-12・ユーザー指摘）"
```

---

## Task 3: SH-11 Reset Layout

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_shell_chrome.py`（追記）

**Interfaces:**
- Consumes: `self.saveState()`/`self.restoreState()`（QMainWindow・docks/toolbar は objectName 設定済み）・`view_menu`・既存 `self._restore_state()` 呼出し（`__init__` 末尾付近）。
- Produces: `self._default_state`（構築時の既定配置・`_restore_state` の**前**に捕捉）・`self.action_reset_layout`（View メニュー）・`_reset_layout()`。

- [ ] **Step 1: 失敗するテストを書く（追記）**

```python
def test_reset_layout_restores_default_dock_area(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtCore import Qt

    mw = _mw(qtbot, tmp_path)
    # 既定は Right (main_window __init__)。左へ動かして Reset で戻る。
    assert mw.dockWidgetArea(mw.file_dock) == Qt.DockWidgetArea.RightDockWidgetArea
    mw.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, mw.file_dock)
    assert mw.dockWidgetArea(mw.file_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    mw._reset_layout()
    assert mw.dockWidgetArea(mw.file_dock) == Qt.DockWidgetArea.RightDockWidgetArea


def test_reset_layout_action_in_view_menu(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    assert mw.action_reset_layout.text() == "Reset Layout"
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_shell_chrome.py -q`
Expected: FAIL（`_default_state`/`action_reset_layout`/`_reset_layout` 無し）

- [ ] **Step 3: 実装**

`main_window.py` の View メニュー（Task 1 で mnemonic 化済み）末尾に Reset Layout を追加:
```python
        view_menu.addSeparator()
        self.action_reset_layout = view_menu.addAction("Reset Layout")
        self.action_reset_layout.triggered.connect(self._reset_layout)
```
`__init__` の既存 `self._restore_state()` 呼出しの**直前**に既定捕捉を挿入:
```python
        # SH-11: 永続状態で上書きされる前の既定配置を捕捉 (Reset Layout 用)。
        self._default_state = self.saveState()
        self._restore_state()
```
メソッド追加:
```python
    def _reset_layout(self) -> None:
        """Restore the default dock/toolbar arrangement captured at startup (SH-11)."""
        self.restoreState(self._default_state)
```

- [ ] **Step 4: パス確認＋既存無回帰**

```bash
uv run pytest tests/gui/test_shell_chrome.py tests/gui/test_main_window_central.py -q
```

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py
uv run mypy src/valisync/gui/views/main_window.py
git add src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py
git commit -m "feat(gui): Reset Layout — 起動時の既定ドック配置を捕捉し復元（SH-11）"
```

---

## Task 4: SH-14 アイコン/ツールチップ/バージョン

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_shell_chrome.py`（追記）

**Interfaces:**
- Consumes: `self.action_data_explorer`（インライン QAction・:176）・`self._show_about`（:432）・`self.style()`。
- Produces: `action_data_explorer` にアイコン（`SP_DirIcon`）＋ツールチップ。`_about_text()`（version 込み・純関数）。`_show_about` は `_about_text()` を表示。

- [ ] **Step 1: 失敗するテストを書く（追記）**

```python
def test_data_explorer_action_has_icon_and_tooltip(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    assert not mw.action_data_explorer.icon().isNull()
    assert mw.action_data_explorer.toolTip() != ""


def test_about_text_includes_version(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    text = mw._about_text()
    assert text.startswith("ValiSync v")
    assert "—" in text  # "ValiSync v{ver} — ..."
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_shell_chrome.py -q`
Expected: FAIL（icon null・`_about_text` 無し）

- [ ] **Step 3: 実装**

`main_window.py` の `action_data_explorer` 生成（:176-178）を icon/tooltip 付きへ:
```python
        self.action_data_explorer = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon),
            "Data Explorer",
            self,
        )
        self.action_data_explorer.setToolTip("データエクスプローラを開く")  # noqa: RUF001
        self.action_data_explorer.setStatusTip("データエクスプローラを開く")  # noqa: RUF001
        self.action_data_explorer.triggered.connect(self.open_data_explorer)
        toolbar.addAction(self.action_data_explorer)
```
import: `QStyle` を `from PySide6.QtWidgets import ...` に統合（未 import なら）。
`_show_about`（:432-435）を version 対応へ:
```python
    def _about_text(self) -> str:
        try:
            from importlib.metadata import version

            ver = version("valisync")
        except Exception:  # PackageNotFoundError 等
            ver = "unknown"
        return f"ValiSync v{ver} — ADAS 信号解析デスクトップ"  # noqa: RUF001

    def _show_about(self) -> None:
        QMessageBox.about(self, "About ValiSync", self._about_text())
```

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_shell_chrome.py -q`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py
uv run mypy src/valisync/gui/views/main_window.py
git add src/valisync/gui/views/main_window.py tests/gui/test_shell_chrome.py
git commit -m "feat(gui): Data Explorer アイコン/ツールチップ＋About にバージョン（SH-14）"
```

---

## Task 5: Layer C realgui スケルトン

**Files:**
- Create: `tests/realgui/test_shell_chrome_flow.py`

**Interfaces:**
- Consumes: `MainWindow`（ツールバーのドックトグル・Reset Layout）。
- 目的: 実 OS 入力でツールバートグル/Reset を検証（honest gate・`skip_unless_real_display` で CI skip）。

- [ ] **Step 1: スケルトンを書く**

```python
# tests/realgui/test_shell_chrome_flow.py
"""Layer C: シェル chrome の実 OS 入力 (SH-11/12)。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def _shown_mw(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    mw.recent_files = mw.recent_files.__class__(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(mw)
    mw.resize(1000, 700)
    mw.show()
    qtbot.waitExposed(mw)
    QApplication.processEvents()
    return mw


def test_toolbar_dock_toggle_real_click(qtbot: QtBot, tmp_path: Path) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

    mw = _shown_mw(qtbot, tmp_path)
    toolbar = mw.findChild(QToolBar, "main_toolbar")
    toggle = mw.file_dock.toggleViewAction()
    btn = toolbar.widgetForAction(toggle)
    assert isinstance(btn, QToolButton)
    assert mw.file_dock.isVisible()
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not mw.file_dock.isVisible(), "ツールバートグル実クリックでドックが隠れない"


def test_reset_layout_real(qtbot: QtBot, tmp_path: Path) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    mw = _shown_mw(qtbot, tmp_path)
    mw.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, mw.file_dock)
    QApplication.processEvents()
    mw.action_reset_layout.trigger()
    QApplication.processEvents()
    assert mw.dockWidgetArea(mw.file_dock) == Qt.DockWidgetArea.RightDockWidgetArea
```

- [ ] **Step 2: 収集確認**

Run: `uv run pytest tests/realgui/test_shell_chrome_flow.py --collect-only -q`
Expected: 2 tests collected（`--realgui` 無しでは skip）

- [ ] **Step 3: ゲート＋コミット**

```bash
uv run ruff check tests/realgui/test_shell_chrome_flow.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format tests/realgui/test_shell_chrome_flow.py
git add tests/realgui/test_shell_chrome_flow.py
git commit -m "test(realgui): シェル chrome の honest gate スケルトン（SH-11/12）"
```

---

## Task 6: docs 反映（catalog / roadmap）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（SH-05/11/12/14 解消）
- Modify: `docs/roadmap.md`（gui-shell-controls 完結）

- [ ] **Step 1: catalog の SH-05/11/12/14 に解消注記**

既存 ✅解消 行の書式（増分2b の SH-06/08/10/15 等）に倣い、優先度を `✅解消` にし本文先頭へ太字注記（元本文は残す・日付 2026-07-08・増分3）:
- SH-05: `**✅解消（2026-07-08・増分3）: open_folder=Ctrl+Shift+O・Exit=Ctrl+Q・メニュー mnemonic（&File 等）。open=Ctrl+O/export=Ctrl+E は ShellActions 済み。**`
- SH-12: `**✅解消（2026-07-08・増分3）: 3ドックの toggleViewAction をツールバーに搭載（View メニューと状態連動の可視トグル）。**`
- SH-11: `**✅解消（2026-07-08・増分3）: 起動時に既定配置を saveState 捕捉し View>Reset Layout で restoreState 復元。**`
- SH-14: `**✅解消（2026-07-08・増分3）: Data Explorer に SP_DirIcon＋ツールチップ・About に importlib.metadata バージョン。**`

- [ ] **Step 2: roadmap 更新**

gui-shell-controls 行に「増分3（シェル chrome: SH-05/11/12/14）実装済み・**全 SH 完結**」を追記、SH-05/11/12/14 を ✅解消 に。

- [ ] **Step 3: コミット**

```bash
git add docs/audit-findings-catalog.md docs/roadmap.md
git commit -m "docs: gui-shell-controls 増分3（SH-05/11/12/14）解消・完結を catalog/roadmap に反映"
```

---

## Self-Review（プラン→spec 突合）

**1. Spec カバレッジ**（設計 §3）:
- SH-05 ショートカット/mnemonic → Task 1。✓
- SH-12 ドックトグルのツールバー化 → Task 2。✓
- SH-11 Reset Layout（既定捕捉＋アクション）→ Task 3。✓
- SH-14 アイコン/ツールチップ/バージョン → Task 4。✓
- Layer C → Task 5。docs → Task 6。✓

**2. プレースホルダ走査**: TBD/TODO なし。全コード実挙動。

**3. 型整合**: `action_exit`/`action_reset_layout`/`action_data_explorer`（QAction）・`_default_state`（QByteArray）・`_reset_layout()`・`_about_text()->str` — Produces と後続 Consumes 一致。`open_folder` shortcut は `shell_actions.py` の既存 `_add` shortcut 引数を None→"Ctrl+Shift+O"。

**留意（実装時）**: (a) MVVM 不変（VM を触らない）。(b) `_default_state` は必ず `_restore_state()` の**前**に捕捉（後だと永続状態が既定になる）。(c) mnemonic の `&` はメニュータイトル/Exit/About に付す（日本語 ShellActions 文言は既存ショートカットがあり mnemonic 必須でない）。(d) `…`（三点リーダ）・日本語 UI 文字列で RUF001 が出たら該当行 noqa。(e) toggleViewAction は View メニューとツールバーで同一オブジェクト＝状態自動連動。
