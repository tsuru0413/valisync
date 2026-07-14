# FU-05 File Browser ヘッダボタン(開く/閉じる)廃止 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** File Browser ヘッダの「開く...」「閉じる」ボタンとヘッダ行を撤去し、追加/クローズ導線を既存の menu / toolbar / Ctrl+O / 右クリック "Remove File" に集約する。

**Architecture:** `FileBrowserView` から `open_button`/`close_button`/`header` QHBoxLayout と死蔵配線（`_close_selected`・`open_requested` シグナル）を除去。`MainWindow` の `open_requested`->`open_file` 接続を除去。右クリック "Remove File"（`_confirm_and_unload`/`build_context_menu`）・D&D・スピナー・空状態プレースホルダは不変。

**Tech Stack:** PySide6, MVVM, pytest-qt。

## Global Constraints

- 変更は `gui/views/` に閉じる。core は Qt 非依存維持。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過（unscoped・repo ルートで実行し出力そのまま報告）。
- Python コメント/文字列に全角約物 `()：+=` 禁止（RUF001/002/003）。ASCII を使う。
- 空状態プレースホルダは変更しない（ユーザー判断）。追加は右クリック "Remove File" ＋ D&D、開くは menu/toolbar/Ctrl+O/Welcome CTA のみ。
- 入力経路（ボタン撤去）変更ゆえ merge 前に gui-verify ①（realgui 無回帰＋ journey smoke）。

---

### Task 1: FileBrowser ヘッダボタン(開く/閉じる)＋死蔵配線の撤去

**Files:**
- Modify: `src/valisync/gui/views/file_browser_view.py`
- Modify: `src/valisync/gui/views/main_window.py`（`open_requested` 接続の除去・現 `:223` 付近）
- Test: `tests/gui/test_file_browser_open.py`（open ボタンテストを不在アサートへ）
- Test: `tests/gui/test_file_browser_delete_confirm.py`（close ボタンテストを不在アサートへ・confirm/menu テストは不変）

**Interfaces:**
- Consumes: なし（既存の `_confirm_and_unload`/`build_context_menu`/`FileListModel` を維持）。
- Produces: `FileBrowserView` は `open_button`/`close_button`/`_close_selected`/`open_requested` を**持たなくなる**。`_confirm_and_unload(row: int) -> None`・`build_context_menu(row: int) -> QMenu`・`is_showing_placeholder() -> bool` は不変。`MainWindow` は `file_browser_view.open_requested` を参照しない。

- [ ] **Step 1: 既存テストを不在アサートへ書き換え（RED を狙う）**

`tests/gui/test_file_browser_open.py` を全置換（open ボタン/シグナルが撤去されたことを検証する内容へ。ファイル名は removal の記録として残す）:

```python
from __future__ import annotations

from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
from valisync.gui.views.file_browser_view import FileBrowserView


def test_no_open_button_or_signal(qtbot: QtBot) -> None:
    """FU-05: the header 'open' button and its open_requested signal are removed.

    Open is reached via the Welcome CTA / toolbar / File>Open / Ctrl+O instead.
    """
    view = FileBrowserView(FileBrowserVM(AppViewModel()))
    qtbot.addWidget(view)
    assert view.findChild(QPushButton, "file_browser_open") is None
    assert not hasattr(view, "open_requested")
```

`tests/gui/test_file_browser_delete_confirm.py` の `test_header_has_close_button`（`:62-65`）を close ボタン**不在**アサートへ置換（他の confirm/menu テストは触らない）:

```python
def test_no_close_button(qtbot: QtBot) -> None:
    """FU-05: the header 'close' button is removed; closing a file is via the
    right-click 'Remove File' menu (still covered above)."""
    _app, _vm, view = _make_browser_with_file(qtbot)
    assert view.findChild(QPushButton, "file_browser_close") is None
```

同ファイル冒頭の docstring 末尾「and a visible header "close" button exists.」を「the right-click 'Remove File' menu is the surviving close affordance.」へ修正（記述整合）。

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_file_browser_open.py tests/gui/test_file_browser_delete_confirm.py -v`
Expected: `test_no_open_button_or_signal` と `test_no_close_button` が FAIL（ボタン/シグナルがまだ存在＝`findChild` が None を返さない・`hasattr` が True）。confirm/menu テストは PASS のまま。

- [ ] **Step 3: `file_browser_view.py` からボタン/ヘッダ/死蔵配線を撤去**

3-1. `open_requested = Signal()`（`:40`）を**削除**。

3-2. ヘッダブロック（`:83-94`＝コメント「Header row」から `header.addWidget(self.close_button)` まで）を**削除**:
```python
        # Header row: Open button (allows advancing from empty list - SH-07)
        self.open_button = QPushButton("開く...")
        self.open_button.setObjectName("file_browser_open")
        self.open_button.clicked.connect(self.open_requested)
        self.close_button = QPushButton("閉じる")
        self.close_button.setObjectName("file_browser_close")
        self.close_button.setToolTip("選択中のファイルを閉じる")
        self.close_button.clicked.connect(self._close_selected)
        header = QHBoxLayout()
        header.addWidget(self.open_button)
        header.addStretch(1)
        header.addWidget(self.close_button)
```

3-3. レイアウト構築（`:96-99`）から `layout.addLayout(header)` の行のみを**削除**（結果は下記）:
```python
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
```

3-4. `_close_selected` メソッド（`:146-149`）を**削除**:
```python
    def _close_selected(self) -> None:
        index = self.list_view.currentIndex()
        if index.isValid():
            self._confirm_and_unload(index.row())
```

3-5. 未使用になる import を除去。`:11` を:
```python
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
```
から（`Signal` 削除）:
```python
from PySide6.QtCore import QPoint, Qt, QTimer
```
`:12-22` の import ブロックから `QHBoxLayout` と `QPushButton` を削除（`QLabel`/`QListView`/`QMenu`/`QMessageBox`/`QStackedWidget`/`QVBoxLayout`/`QWidget` は残す）:
```python
from PySide6.QtWidgets import (
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
```

- [ ] **Step 4: `main_window.py` の `open_requested` 接続を撤去**

`src/valisync/gui/views/main_window.py` の Cross-view wiring（現 `:223`）:
```python
        self.file_browser_view.open_requested.connect(self.open_file)
```
の1行を**削除**（削除しないと `open_requested` 撤去で MainWindow 構築時に AttributeError→全 main_window テストが落ちる）。他の Open 導線（`shell_actions.action("open")`・`welcome_view.open_requested`・toolbar）は `open_file` に直結済みで不変。

- [ ] **Step 5: GREEN 確認**

Run: `uv run pytest tests/gui/test_file_browser_open.py tests/gui/test_file_browser_delete_confirm.py tests/gui/test_main_window.py -v`
Expected: 全 PASS（不在アサート2件 GREEN・confirm/menu 無回帰・MainWindow 構築無回帰）。

- [ ] **Step 6: 品質ゲート（unscoped）**

Run: `uv run pytest`; `uv run ruff check`; `uv run ruff format --check`; `uv run mypy src/`
Expected: 全通過（0 errors）。既存の FileBrowser/MainWindow テストで `open_button`/`close_button`/`open_requested`/`_close_selected` を参照する残存がないことを確認（あれば本タスク内で更新）。

- [ ] **Step 7: コミット**

```bash
git add src/valisync/gui/views/file_browser_view.py src/valisync/gui/views/main_window.py tests/gui/test_file_browser_open.py tests/gui/test_file_browser_delete_confirm.py
git commit -m "feat(fu05): File Browser ヘッダの開く/閉じるボタンを撤去(導線は menu/toolbar/Ctrl+O/右クリック)"
```

---

### Task 2: gui-verify ①ゲート（realgui 無回帰＋ journey smoke）＝メインセッション駆動

**Files:**
- Scratch（非コミット）: real-display 確認。realgui の新規/更新は原則不要（FileBrowser open/close ボタンを実クリックする realgui は存在しない＝`open_requested` realgui は全て WelcomeView 由来）。

- [ ] **Step 1: 変更経路の realgui 対応付け**

`git diff --name-only main...HEAD -- src/valisync/gui/` で変更ファイルを列挙し、`grep -l` で realgui の対応を確認。FileBrowser のボタンは新規入力経路を増やさない（撤去）ため realgui は無回帰確認が主。閉じる導線の実経路＝右クリック "Remove File" が既存 realgui でカバーされているか確認（`grep -rl "Remove File\|file_browser\|FileBrowser" tests/realgui/`）。カバーが無ければフラグ（黙って pass しない）。

- [ ] **Step 2: realgui 無回帰＋ journey smoke（実ディスプレイ）**

Run:
```bash
QT_QPA_PLATFORM=windows uv run pytest --realgui tests/realgui/test_journey_smoke.py -v
```
File Browser 右クリック "Remove File" の realgui があれば併せて実行。D&D ロード経路の realgui（あれば）も無回帰確認。

- [ ] **Step 3: headless full＋証拠集約＋ゲート判定**

Run: `uv run pytest`（0 errors）。
集約: headless full 結果・realgui pass/スクショ・contract 照合（開く/閉じる各効果に残る導線が実在・撤去で発見性を失わない＝Welcome CTA/toolbar/右クリックの実在確認）。ボタン撤去は入力経路の削除ゆえ (b) の realgui は主に無回帰。

---

## Self-Review

- **Spec coverage**: ボタン/ヘッダ/死蔵配線撤去（Task 1 の view+main_window）・空状態プレースホルダ不変（Task 1 で非変更）・右クリック Remove File 残置（Task 1 で confirm/menu テスト無変更）・gui-verify（Task 2）＝spec 全項目。
- **Placeholder scan**: 全 step に実コード/実コマンド。TBD/TODO なし。
- **Type consistency**: `_confirm_and_unload(row: int)`・`build_context_menu(row: int)`・`is_showing_placeholder()` は不変で参照整合。撤去する `open_requested`/`open_button`/`close_button`/`_close_selected` はどのタスクも新規参照しない。
- **YAGNI**: プレースホルダにボタン/CTA を作らない・close 可視ボタンを別形で再導入しない・Open 導線の新規追加なし。
