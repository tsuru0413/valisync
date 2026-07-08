# gui-shell-controls 増分2a（タブ操作 UI）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 実装済みの多タブ機能（`GraphAreaVM`）へ到達する可視 UI を `GraphAreaView` に足す — 新規タブ（コーナー「+」/Ctrl+T）・タブを閉じる（✕）・タブ改名（ダブルクリックでインライン編集）。SH-02/04/13 を解消する。

**Architecture:** `GraphAreaView` には既に VM へ委譲するコマンドメソッド（`add_tab`/`remove_tab`/`rename_tab`・いずれも rejection を `contextlib.suppress(ValueError)`）が存在する。本増分は**それらを起動するアフォーダンスを QTabWidget のタブバーへ配線するだけ**で、新規ロジックは無い。改名のみインライン `QLineEdit` エディタ（`_TabRenameEditor`）を新設する。

**Tech Stack:** Python 3.12+ / PySide6 (Qt6) / pyqtgraph / pytest + pytest-qt。MVVM（View=Qt / ViewModel=純 Python）。

## Global Constraints

- 設計 spec: [2026-07-08-gui-shell-controls-r2-tabs-panels-sources-design.md](../specs/2026-07-08-gui-shell-controls-r2-tabs-panels-sources-design.md) §3（増分2a）。親 spec §5。
- 対象は `src/valisync/gui/views/graph_area_view.py` 1ファイル（＋テスト）。既存の VM 委譲メソッド（`add_tab`/`remove_tab`/`rename_tab`・L176-185）・`_rebuild`（L94・clear→addTab で毎回再投影）・`_on_current_changed`・`_syncing` ガードを壊さない。
- **`_rebuild` 跨ぎ**: `setTabsClosable`・コーナーウィジェットは QTabWidget に1度設定すれば `clear()` で消えない。ただし**per-tab の close ボタン抑制（最後の1枚）は addTab の度に再適用**が必要 → `_rebuild` の addTab ループ後に行う。
- **ショートカット**: Ctrl+T は手製 QShortcut。`Qt.ShortcutContext.WidgetWithChildrenShortcut`（親 spec §5.1・pyqtgraph 束縛は Escape のみで非衝突）。
- 品質ゲート（コミット前に全通過）: `uv run pytest` / `uv run ruff check`（exit 0・`| tail` 禁止）/ `uv run ruff format --check` / `uv run mypy src/`。
- **全角文字禁止（コード内・コメント/docstring）**: `（）＋−` 等は ASCII `()` `+` `-`（ruff RUF002/003 が検出・プロジェクトは緩和していない）。日本語 UI 文字列（tooltip・ラベル）は可（RUF001 が出たら当該行に `# noqa: RUF001`）。
- GUI テストレイヤー: Layer A/B 必須（headless）＋新入力経路ごとに Layer C スケルトン。テストは既存 `tests/gui/test_graph_area_view.py` の `_make_area(qtbot, panel_factory=...)` パターンに倣い、軽量 `panel_factory=lambda vm: QLabel()` でタブ挙動に集中する。

---

## File Structure

| ファイル | 責務 | 種別 |
|---|---|---|
| `src/valisync/gui/views/graph_area_view.py` | コーナー「+」＋Ctrl+T・tabsClosable＋tabCloseRequested・tabBarDoubleClicked→`_TabRenameEditor`・`_rebuild` で最後の1枚の close 抑制 | 変更 |
| `tests/gui/test_graph_area_tab_ui.py` | 新アフォーダンスの Layer A/B | 新規 |
| `tests/realgui/test_tab_ui_flow.py` | Layer C（コーナー+・Ctrl+T・close・ダブルクリック改名） | 新規 |
| `docs/audit-findings-catalog.md` / `docs/roadmap.md` | SH-02/04/13 解消反映 | 変更 |

**依存順**: Task 1（新規タブ）→ Task 2（閉じる）→ Task 3（改名）は同一ファイルだが独立アフォーダンス。Task 4（realgui）・Task 5（docs）は最後。

---

## Task 1: SH-02 新規タブ（コーナー「+」＋Ctrl+T）

**Files:**
- Modify: `src/valisync/gui/views/graph_area_view.py`
- Test: `tests/gui/test_graph_area_tab_ui.py`

**Interfaces:**
- Consumes: 既存 `GraphAreaView.add_tab(name=None)`（L176・`vm.add_tab` 委譲）。
- Produces: コーナー「+」ボタン（objectName `"new_tab_button"`）clicked→`add_tab()`。`self._new_tab_shortcut: QShortcut`（Ctrl+T・WidgetWithChildrenShortcut）activated→`add_tab()`。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_graph_area_tab_ui.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QLineEdit, QToolButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM


def _make_area(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from valisync.gui.views.graph_area_view import GraphAreaView

    vm = GraphAreaVM(AppViewModel(Session()))
    view = GraphAreaView(vm, panel_factory=lambda _vm: QLabel())
    qtbot.addWidget(view)
    return view


def test_corner_new_tab_button_adds_tab(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    btn = view.tabs.cornerWidget()
    assert isinstance(btn, QToolButton)
    assert btn.objectName() == "new_tab_button"
    assert view.tabs.count() == 1
    btn.click()
    assert view.tabs.count() == 2
    assert view.vm.active_tab_index == 1  # add_tab は新タブを active に


def test_ctrl_t_shortcut_adds_tab(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    assert view._new_tab_shortcut.key() == QKeySequence("Ctrl+T")
    view._new_tab_shortcut.activated.emit()  # 接続を検証
    assert view.tabs.count() == 2
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_area_tab_ui.py -q`
Expected: FAIL（`cornerWidget()` は None / `_new_tab_shortcut` なし）

- [ ] **Step 3: 実装**

`graph_area_view.py` の import に追加:
```python
from PySide6.QtGui import QKeySequence, QShortcut  # 既存 QDragEnterEvent 等の行に統合
from PySide6.QtWidgets import QToolButton  # 既存 QtWidgets import に追加
```

`__init__` の `self.tabs = QTabWidget(self)` / `currentChanged` 接続の直後に:
```python
        # SH-02: 新規タブのアフォーダンス (コーナー "+" と Ctrl+T)。
        new_tab_btn = QToolButton(self.tabs)
        new_tab_btn.setObjectName("new_tab_button")
        new_tab_btn.setText("+")
        new_tab_btn.setToolTip("新規タブ (Ctrl+T)")
        new_tab_btn.clicked.connect(lambda: self.add_tab())
        self.tabs.setCornerWidget(new_tab_btn, Qt.Corner.TopRightCorner)

        self._new_tab_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        self._new_tab_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self._new_tab_shortcut.activated.connect(lambda: self.add_tab())
```

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_graph_area_tab_ui.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_tab_ui.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_tab_ui.py
uv run mypy src/valisync/gui/views/graph_area_view.py
git add src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_tab_ui.py
git commit -m "feat(gui): 新規タブ導線 — コーナー + ボタンと Ctrl+T（SH-02）"
```

---

## Task 2: SH-04 タブを閉じる（✕＋最後の1枚は抑制）

**Files:**
- Modify: `src/valisync/gui/views/graph_area_view.py`
- Test: `tests/gui/test_graph_area_tab_ui.py`（追記）

**Interfaces:**
- Consumes: 既存 `GraphAreaView.remove_tab(index)`（L179・`vm.remove_tab` を `suppress(ValueError)` で委譲＝最後の1枚は no-op）。`_rebuild`（L94）。
- Produces: `self.tabs` に `setTabsClosable(True)`＋`tabCloseRequested→remove_tab`。`_rebuild` 末で**タブ数==1 のとき close ボタンを除去**。

- [ ] **Step 1: 失敗するテストを書く（追記）**

```python
def test_close_button_removes_tab(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    view.add_tab()
    view.add_tab()
    assert view.tabs.count() == 3
    view.tabs.tabCloseRequested.emit(1)  # close ボタン押下 = このシグナル
    assert view.tabs.count() == 2


def test_last_tab_close_button_suppressed(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QTabBar

    view = _make_area(qtbot)
    assert view.tabs.count() == 1
    bar = view.tabs.tabBar()
    pos = QTabBar.ButtonPosition(
        bar.style().styleHint(
            bar.style().StyleHint.SH_TabBar_CloseButtonPosition, None, bar
        )
    )
    assert bar.tabButton(0, pos) is None  # 最後の1枚は閉じるボタンなし
    # そして close 要求が来ても最後の1枚は残る (防御)
    view.tabs.tabCloseRequested.emit(0)
    assert view.tabs.count() == 1


def test_close_button_reappears_above_one_tab(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QTabBar

    view = _make_area(qtbot)
    view.add_tab()  # 2 タブ = close ボタンあり
    bar = view.tabs.tabBar()
    pos = QTabBar.ButtonPosition(
        bar.style().styleHint(
            bar.style().StyleHint.SH_TabBar_CloseButtonPosition, None, bar
        )
    )
    assert bar.tabButton(0, pos) is not None
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_area_tab_ui.py -q`
Expected: FAIL（tabsClosable 未設定・close ボタン抑制なし）

- [ ] **Step 3: 実装**

`__init__` の Task 1 追記の直後に:
```python
        # SH-04: タブを閉じる。最後の1枚の抑制は _rebuild で per-tab に行う。
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.remove_tab)
```

`_rebuild`（L94）の `self.tabs.setCurrentIndex(self.vm.active_tab_index)` の**直前**に:
```python
            # SH-04: 最後の1枚は閉じさせない (remove_tab も ValueError を握るが、
            # ボタン自体を消して操作不能を明示)。close ボタン位置はスタイル依存。
            if self.tabs.count() == 1:
                bar = self.tabs.tabBar()
                pos = QTabBar.ButtonPosition(
                    bar.style().styleHint(
                        QStyle.StyleHint.SH_TabBar_CloseButtonPosition, None, bar
                    )
                )
                bar.setTabButton(0, pos, None)
```

import に追加:
```python
from PySide6.QtWidgets import QStyle, QTabBar  # 既存 QtWidgets import に追加
```

- [ ] **Step 4: パス確認＋既存無回帰**

```bash
uv run pytest tests/gui/test_graph_area_tab_ui.py tests/gui/test_graph_area_view.py -q
```
Expected: 新テスト PASS＋既存 GraphAreaView テスト無回帰。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_tab_ui.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_tab_ui.py
uv run mypy src/valisync/gui/views/graph_area_view.py
git add src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_tab_ui.py
git commit -m "feat(gui): タブを閉じる導線 — closable + 最後の1枚は抑制（SH-04）"
```

---

## Task 3: SH-13 タブ改名（ダブルクリック→インライン編集）

**Files:**
- Modify: `src/valisync/gui/views/graph_area_view.py`
- Test: `tests/gui/test_graph_area_tab_ui.py`（追記）

**Interfaces:**
- Consumes: 既存 `GraphAreaView.rename_tab(index, name)`（L183・`vm.rename_tab` を `suppress(ValueError)`＝1-32字外は no-op）。`vm.tabs()[i].name`。
- Produces:
  - `_TabRenameEditor(QLineEdit)`（module-level）: `committed = Signal(str)`（Enter/フォーカス喪失）・`cancelled = Signal()`（Escape）。
  - `GraphAreaView._begin_rename(index)`（`tabBarDoubleClicked` 接続先）: タブ矩形に editor をオーバーレイ。
  - `GraphAreaView._finish_rename(index, text)`: 1-32字なら `rename_tab`＋editor 破棄、範囲外なら editor 継続（赤枠）。
  - `self._rename_editor: _TabRenameEditor | None`。

- [ ] **Step 1: 失敗するテストを書く（追記）**

```python
def test_double_click_opens_rename_editor(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    view._begin_rename(0)  # tabBarDoubleClicked の接続先
    editor = view._rename_editor
    assert isinstance(editor, QLineEdit)
    assert editor.text() == "Tab 1"


def test_rename_commit_updates_vm(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    view._begin_rename(0)
    view._rename_editor.setText("速度ログ")
    view._rename_editor.committed.emit("速度ログ")
    assert view.vm.tabs()[0].name == "速度ログ"
    assert view._rename_editor is None  # 確定で editor 破棄


def test_rename_cancel_keeps_name(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    view._begin_rename(0)
    view._rename_editor.setText("破棄される")
    view._rename_editor.cancelled.emit()
    assert view.vm.tabs()[0].name == "Tab 1"
    assert view._rename_editor is None


def test_rename_invalid_length_keeps_editor_open(qtbot: QtBot) -> None:
    view = _make_area(qtbot)
    view._begin_rename(0)
    view._rename_editor.committed.emit("x" * 33)  # 32 字超
    assert view.vm.tabs()[0].name == "Tab 1"  # 変更されない
    assert view._rename_editor is not None  # 編集継続
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_area_tab_ui.py -q`
Expected: FAIL（`_begin_rename`/`_rename_editor` なし）

- [ ] **Step 3: 実装**

`graph_area_view.py` に module-level クラスを追加（`_default_panel_factory` の近く）:
```python
class _TabRenameEditor(QLineEdit):
    """タブバー上のインライン改名エディタ (SH-13)。

    Enter/フォーカス喪失で committed、Escape で cancelled を出す。位置決めと
    ライフサイクルは GraphAreaView が握る。
    """

    committed = Signal(str)
    cancelled = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.committed.emit(self.text())
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.committed.emit(self.text())
```

import に追加:
```python
from PySide6.QtGui import QFocusEvent, QKeyEvent  # 既存 QtGui import に統合
from PySide6.QtWidgets import QLineEdit  # 既存 QtWidgets import に追加
```

`__init__` の Task 2 追記の直後に:
```python
        # SH-13: ダブルクリックでタブ改名。
        self._rename_editor: _TabRenameEditor | None = None
        self.tabs.tabBarDoubleClicked.connect(self._begin_rename)
```

メソッドを追加（`rename_tab` の近く）:
```python
    def _begin_rename(self, index: int) -> None:
        if index < 0:
            return
        self._discard_rename_editor()  # 進行中があれば畳む
        bar = self.tabs.tabBar()
        editor = _TabRenameEditor(bar)
        editor.setText(self.tabs.tabText(index))
        editor.selectAll()
        editor.setGeometry(bar.tabRect(index))
        editor.committed.connect(lambda text: self._finish_rename(index, text))
        editor.cancelled.connect(self._discard_rename_editor)
        editor.show()
        editor.setFocus()
        self._rename_editor = editor

    def _finish_rename(self, index: int, text: str) -> None:
        # 範囲外は editor を残して修正させる (赤枠でフィードバック)。
        if not (1 <= len(text) <= 32):
            if self._rename_editor is not None:
                self._rename_editor.setStyleSheet("border: 1px solid #c0392b;")
            return
        self._discard_rename_editor()
        self.rename_tab(index, text)  # VM 反映 -> _rebuild

    def _discard_rename_editor(self) -> None:
        editor = self._rename_editor
        self._rename_editor = None
        if editor is not None:
            editor.hide()
            editor.deleteLater()
```

注: `_finish_rename` は先に `_rename_editor=None` にしてから `rename_tab`（→`_rebuild`）を呼ぶため、フォーカス喪失の二重 committed は `_discard_rename_editor` が None チェックで no-op になる。

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_graph_area_tab_ui.py -q`
Expected: PASS（全 tab UI テスト）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_tab_ui.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_tab_ui.py
uv run mypy src/valisync/gui/views/graph_area_view.py
git add src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_tab_ui.py
git commit -m "feat(gui): タブ改名導線 — ダブルクリックでインライン編集（SH-13）"
```

---

## Task 4: Layer C realgui スケルトン（タブ操作の実 OS 入力）

**Files:**
- Create: `tests/realgui/test_tab_ui_flow.py`

**Interfaces:**
- Consumes: `GraphAreaView`（コーナー「+」・Ctrl+T・close ボタン・ダブルクリック改名）。
- 目的: headless が迂回する実タブバー操作を実 OS 入力で検証（honest gate）。`skip_unless_real_display` で CI skip。

- [ ] **Step 1: スケルトンを書く**

```python
# tests/realgui/test_tab_ui_flow.py
"""Layer C: タブ操作アフォーダンスの実 OS 入力 (SH-02/04/13)。"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def _make_shown_area(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication, QLabel

    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.graph_area_view import GraphAreaView

    vm = GraphAreaVM(AppViewModel(Session()))
    view = GraphAreaView(vm, panel_factory=lambda _vm: QLabel())
    qtbot.addWidget(view)
    view.resize(600, 400)
    view.show()
    qtbot.waitExposed(view)
    QApplication.processEvents()
    return view


def test_corner_button_click_adds_tab(qtbot: QtBot) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    view = _make_shown_area(qtbot)
    btn = view.tabs.cornerWidget()
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert view.tabs.count() == 2, "コーナー + の実クリックで新規タブが増えない"


def test_double_click_tab_renames(qtbot: QtBot) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    view = _make_shown_area(qtbot)
    bar = view.tabs.tabBar()
    center = bar.tabRect(0).center()
    qtbot.mouseDClick(bar, Qt.MouseButton.LeftButton, pos=center)
    QApplication.processEvents()
    assert view._rename_editor is not None, "ダブルクリックで改名エディタが出ない"
    qtbot.keyClicks(view._rename_editor, "renamed")
    qtbot.keyClick(view._rename_editor, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert view.vm.tabs()[0].name == "renamed"
```

- [ ] **Step 2: 収集確認**

Run: `uv run pytest tests/realgui/test_tab_ui_flow.py --collect-only -q`
Expected: 2 tests collected（`--realgui` 無しでは skip）

- [ ] **Step 3: ゲート＋コミット**

```bash
uv run ruff check tests/realgui/test_tab_ui_flow.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format tests/realgui/test_tab_ui_flow.py
git add tests/realgui/test_tab_ui_flow.py
git commit -m "test(realgui): タブ操作アフォーダンスの honest gate スケルトン（SH-02/04/13）"
```

---

## Task 5: docs 反映（catalog / roadmap）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（SH-02/04/13 解消）
- Modify: `docs/roadmap.md`（gui-shell-controls に増分2a）

- [ ] **Step 1: catalog の SH-02/04/13 行に解消注記**

各行の優先度を `✅解消` にし、本文先頭へ（他の ✅解消 行の書式に倣う）:
- SH-02: `**✅解消（2026-07-08・増分2a）: QTabWidget コーナー "+" ボタン＋Ctrl+T で GraphAreaVM.add_tab に配線。**`
- SH-04: `**✅解消（2026-07-08・増分2a）: setTabsClosable＋tabCloseRequested→remove_tab。最後の1枚は close ボタン抑制。**`
- SH-13: `**✅解消（2026-07-08・増分2a）: tabBarDoubleClicked→インライン QLineEdit エディタ→rename_tab（1-32字・範囲外は編集継続）。**`
元の課題本文は残す（履歴保持）。

- [ ] **Step 2: roadmap 更新**

gui-shell-controls 行に「増分2a（タブ操作: SH-02/04/13）実装済み」を追記、SH-02/04/13 を strikethrough✅解消に。

- [ ] **Step 3: コミット**

```bash
git add docs/audit-findings-catalog.md docs/roadmap.md
git commit -m "docs: gui-shell-controls 増分2a（タブ操作・SH-02/04/13）解消を catalog/roadmap に反映"
```

---

## Self-Review（プラン→spec 突合）

**1. Spec カバレッジ**（設計 spec §3）:
- SH-02 新規タブ（コーナー+＋Ctrl+T）→ Task 1。✓
- SH-04 閉じる（closable＋last-tab 抑制）→ Task 2。✓
- SH-13 改名（ダブルクリック→インライン）→ Task 3。✓
- Layer C（新入力経路: コーナー+/close/ダブルクリック改名）→ Task 4。Ctrl+T の実キーは realgui で追加可（Task 4 は主要2経路をカバー）。✓
- docs → Task 5。✓

**2. プレースホルダ走査**: TBD/TODO なし。全コード実挙動。

**3. 型整合**: `add_tab(name=None)`/`remove_tab(index)`/`rename_tab(index, name)`（既存 View メソッド）・`_new_tab_shortcut: QShortcut`・`_TabRenameEditor(committed: Signal(str), cancelled: Signal())`・`_begin_rename(index)`/`_finish_rename(index, text)`/`_discard_rename_editor()`・`_rename_editor: _TabRenameEditor | None` — Produces と後続 Consumes が一致。

**留意（実装時）**: (a) `_rebuild` の last-tab 抑制は addTab ループ後・setCurrentIndex 前に置く（既存 `_syncing` ガード内）。(b) close ボタン位置はスタイル依存のため `SH_TabBar_CloseButtonPosition` で取得（RightSide 決め打ちにしない）。(c) `_finish_rename` は editor 破棄を先に行い、フォーカス喪失の二重 committed を None チェックで無害化。(d) コーナーウィジェット/tabsClosable は `_rebuild` の `clear()` で消えない（per-tab の close 抑制のみ再適用）。
