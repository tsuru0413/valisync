# realgui コンテナメニュー3経路 Implementation Plan (Phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChannelBrowser / DataExplorer / GraphPanel の右クリックコンテキストメニューが**実 OS 右クリック**で確実に出ることを production 修正＋realgui で保証する（headless が構造的に false-green を出す3経路）。

**Architecture:** ChannelBrowser/DataExplorer は旧コンテナ `contextMenuEvent` override（子アイテムビューがイベントを伝播せず実機不発）を撤去し、子 `QTreeView` に `Qt.CustomContextMenu` ＋ `customContextMenuRequested` シグナル経路へ移行（FileBrowser PR#11 と同型）。GraphPanel は pyqtgraph `ViewBox` の既定メニューを `setMenuEnabled(False)` で抑止し、自前 `contextMenuEvent` が実右クリックで勝つことを保証。各経路に実 OS 右クリック realgui（`activePopupWidget` が自前 QMenu であることを assert）を追加し、merge 前に `/gui-verify` ①ゲートで honest RED→GREEN を実証する。

**Tech Stack:** PySide6 / pyqtgraph / pytest / pytest-qt / ctypes(Win32)。共有 realgui 入力ヘルパ `tests/realgui/_realgui_input.py`（Phase 1）。

## Global Constraints

- 設計 spec: `docs/superpowers/specs/2026-06-30-realgui-coverage-expansion-design.md`（§クラス1＝lines 36-42・honest 検証＝line 106）。一次根拠: `docs/realgui-coverage-audit.md`（H5/H6/H7）。
- **MVVM**: viewmodels に Qt/pyqtgraph を import しない。本プランは views（`src/valisync/gui/views/`）と tests のみ変更で viewmodels 不変。
- **挙動保存**: production 修正はメニュー**配送経路のみ**を変える。メニューの内容（`build_context_menu` の生成物・アクション・en/disable ロジック）は不変。ChannelBrowser は ExtendedSelection の**複数選択でメニューが効く**仕様（選択ベース）なので、右クリックハンドラは**選択を変更しない**（`setCurrentIndex` 禁止＝複数一括追加を壊さない）。
- **honest TDD（①②の核）**: 各 realgui は配線破壊（`setContextMenuPolicy`/`setMenuEnabled` 除去）で RED になることを1度実証してから GREEN。RED→GREEN は実 win32 のみで証明可能なため**コントローラの `/gui-verify` ①ゲート**で実施（実装サブエージェントは headless のため `--realgui` を実行しない）。
- realgui(Layer C) は `@pytest.mark.realgui`＋`--realgui` opt-in、配置 `tests/realgui/`（offscreen 強制 conftest 無し＝実ディスプレイで起動）。非 realgui headless テストは `tests/gui/`。
- コミットメッセージ末尾に必須トレーラ（`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k`）。
- コミット前ゲート: `uv run pytest`（headless 0 errors）/ `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。worktree なら先に `uv sync --extra dev`。

## File Structure

- Modify: `src/valisync/gui/views/channel_browser_view.py` — コンテナ override 撤去＋子 CustomContextMenu。
- Modify: `src/valisync/gui/views/data_explorer_view.py` — 同上。
- Modify: `src/valisync/gui/views/graph_panel_view.py` — 全 ViewBox に `setMenuEnabled(False)`。
- Create: `tests/realgui/test_channel_browser_realclick.py` — 実右クリック→自前メニュー realgui。
- Create: `tests/realgui/test_data_explorer_realclick.py` — 同上。
- Create: `tests/realgui/test_graph_panel_menu_realclick.py` — 実右クリック→自前メニュー（pyqtgraph 既定でない）realgui。

**参照テンプレート（不変・読むだけ）**: `src/valisync/gui/views/file_browser_view.py`（CustomContextMenu 正準実装 = lines 34/40/50/60-80）、`tests/realgui/test_file_browser_realclick.py`（実右クリック realgui の正準パターン）、`tests/gui/test_context_menus.py`（各 view のデータ込み構築 fixture）。

---

### Task 1: ChannelBrowser を CustomContextMenu 化＋実右クリック realgui

**Files:**
- Modify: `src/valisync/gui/views/channel_browser_view.py`
- Create: `tests/realgui/test_channel_browser_realclick.py`

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input.py` の `RDOWN, RUP, at, skip_unless_real_display`。`tests/gui/test_context_menus.py` の `_setup_app_2sig` と同じ構築手順。
- Produces: `ChannelBrowserView._show_context_menu(pos: QPoint)`（新規ハンドラ）。`contextMenuEvent` は撤去。

**背景**: 現状 `channel_browser_view.py:113-114` がコンテナ `contextMenuEvent` override。子 `self.tree`（QTreeView, line 42）の右クリックが伝播せず実機でメニュー不発になりうる。`build_context_menu()`（103-111, "Add to Active Panel"）は**選択ベース**（`selected_signal_keys()`）。

- [ ] **Step 1: realgui テストを作成（honest = 現状コードに対し RED 想定）**

`tests/realgui/test_channel_browser_realclick.py`:

```python
"""Layer C: real-OS-input test for the ChannelBrowser "Add to Active Panel" menu.

Opt-in — run with ``--realgui`` on Windows + a real display. Issues a genuine
right-click via Win32 and asserts the application's own QMenu pops up (the OS →
Qt path a synthesized event cannot exercise). See ``docs/gui-testing-layers.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import RDOWN, RUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def _fmt():
    from valisync.core.models import Delimiter, FormatDefinition

    return FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )


def test_add_to_panel_menu_appears_on_real_os_right_click(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()

    from PySide6.QtCore import QEventLoop, QItemSelectionModel, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
    from valisync.gui.views.channel_browser_view import ChannelBrowserView

    path = tmp_path / "d.csv"
    path.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(path, _fmt())
    app_vm.set_active_file(key)

    view = ChannelBrowserView(ChannelBrowserVM(app_vm))
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 360, 240)
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(
        lambda: view.tree.visualRect(view.model.index(0, 0)).height() > 0,
        timeout=3000,
    )

    # Select the first signal row so "Add to Active Panel" is enabled.
    index = view.model.index(0, 0)
    view.tree.selectionModel().select(
        index,
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )

    dpr = view.devicePixelRatioF()
    center = view.tree.visualRect(index).center()
    gp = view.tree.viewport().mapToGlobal(center)
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)

    captured: dict[str, object] = {}

    def do_real_right_click() -> None:
        at(phys_x, phys_y, RDOWN)
        at(phys_x, phys_y, RUP)

    loop = QEventLoop()

    def capture() -> None:
        popup = QApplication.activePopupWidget()
        captured["type"] = type(popup).__name__ if popup is not None else None
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "ch.png"))
        if isinstance(popup, QMenu):
            captured["actions"] = [a.text() for a in popup.actions()]
            popup.close()
        loop.quit()

    QTimer.singleShot(300, do_real_right_click)
    QTimer.singleShot(900, capture)
    QTimer.singleShot(4000, loop.quit)  # safety net
    loop.exec()

    assert captured.get("type") == "QMenu", (
        "no context menu on a real OS right-click; "
        f"got {captured.get('type')!r}. screenshot: {tmp_path / 'ch.png'}"
    )
    assert captured.get("actions") == ["Add to Active Panel"]
```

- [ ] **Step 2: ヘッドレス収集を確認（realgui は skip）**

Run: `uv run pytest tests/realgui/test_channel_browser_realclick.py --collect-only -q`
Expected: 1 test collected・import エラー無し（実行すれば offscreen で skip）。

- [ ] **Step 3: production 修正（コンテナ override 撤去＋子 CustomContextMenu）**

`src/valisync/gui/views/channel_browser_view.py` の import 行を差し替え（`QContextMenuEvent` 撤去・`QPoint`/`Qt` 追加）:

```python
from PySide6.QtCore import QItemSelection, QMimeData, QPoint, Qt, Signal
```

（`from PySide6.QtGui import QContextMenuEvent` の行は**削除**。`QtGui` から他に import が無くなるためその import 文ごと削除する。）

`self.tree` セットアップ（`self.tree.setItemsExpandable(False)`、line 50 直後）に追加:

```python
        # CustomContextMenu so a real right-click on the child tree emits
        # customContextMenuRequested. Overriding contextMenuEvent on this
        # container does not fire reliably from the child item view, so the
        # menu would not appear in the real GUI (mirrors FileBrowser PR#11).
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
```

Wiring 節（`self.tree.selectionModel().selectionChanged.connect(...)`、line 59 直後）に追加:

```python
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
```

`contextMenuEvent`（line 113-114）を**削除**し、代わりに `_show_context_menu` を追加（`build_context_menu` の直後）:

```python
    def _show_context_menu(self, pos: QPoint) -> None:
        """Show the signal menu on a real right-click (CustomContextMenu).

        Driven by ``QTreeView.customContextMenuRequested`` so the menu appears on
        the real OS path (overriding contextMenuEvent on this container does not
        fire from the child item view). The menu operates on the current
        multi-selection (R14.1 / H4), so this deliberately does NOT change the
        selection — right-clicking with several rows selected keeps them all for
        a bulk "Add to Active Panel".
        """
        global_pos = self.tree.viewport().mapToGlobal(pos)
        self.build_context_menu().exec(global_pos)
```

- [ ] **Step 4: 既存 headless が無回帰なことを確認**

Run: `uv run pytest tests/gui/test_context_menus.py -q`
Expected: `TestChannelBrowserMenu` 全 pass（`build_context_menu` 不変なので 4 件とも GREEN のまま）。

- [ ] **Step 5: フルゲート**

Run: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`
Expected: headless 全 pass・0 errors（新 realgui は skip）、lint/format/type クリーン。

- [ ] **Step 6: Commit**

```bash
git add src/valisync/gui/views/channel_browser_view.py tests/realgui/test_channel_browser_realclick.py
git commit -m "feat(gui): ChannelBrowser を CustomContextMenu 化＋実右クリック realgui"
```

---

### Task 2: DataExplorer を CustomContextMenu 化＋実右クリック realgui

**Files:**
- Modify: `src/valisync/gui/views/data_explorer_view.py`
- Create: `tests/realgui/test_data_explorer_realclick.py`

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input.py` の `RDOWN, RUP, at, skip_unless_real_display`。`tests/mdf4_helpers.write_mdf4`（実ファイル生成）。
- Produces: `DataExplorerView._show_context_menu(pos: QPoint)`（新規ハンドラ）。`contextMenuEvent` は撤去。

**背景**: 現状 `data_explorer_view.py:190-195` がコンテナ `contextMenuEvent` override（`indexAt(viewport.mapFromGlobal(globalPos))` 有効時に `build_context_menu(filePath).exec`）。子 `self.tree`（QTreeView, line 74, `setCentralWidget`）。`build_context_menu(path)`（178-188, "Load File"/"Remove from Data Sources"）は**パスベース**（右クリック行から `fs_model.filePath`）なので選択非依存＝FileBrowser 同型でクリーンに置換できる。

- [ ] **Step 1: realgui テストを作成**

`tests/realgui/test_data_explorer_realclick.py`:

```python
"""Layer C: real-OS-input test for the DataExplorer file context menu.

Opt-in — run with ``--realgui`` on Windows + a real display. Issues a genuine
right-click via Win32 and asserts the application's own QMenu pops up.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.mdf4_helpers import CAN, write_mdf4
from tests.realgui._realgui_input import RDOWN, RUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_file_menu_appears_on_real_os_right_click(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()

    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.data_explorer_view import DataExplorerView

    mf4 = write_mdf4(
        tmp_path / "log.mf4",
        [{"name": "s", "timestamps": [0.0, 1.0], "values": [1.0, 2.0], "bus_type": CAN}],
    )

    view = DataExplorerView(AppViewModel())
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 480, 320)
    view.show()
    qtbot.waitExposed(view)

    # Root the tree at tmp_path and wait for the file row (QFileSystemModel
    # populates the directory asynchronously).
    view.add_source(tmp_path)
    file_index = view.fs_model.index(str(mf4))
    qtbot.waitUntil(
        lambda: file_index.isValid() and view.tree.visualRect(file_index).height() > 0,
        timeout=5000,
    )

    dpr = view.devicePixelRatioF()
    center = view.tree.visualRect(file_index).center()
    gp = view.tree.viewport().mapToGlobal(center)
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)

    captured: dict[str, object] = {}

    def do_real_right_click() -> None:
        at(phys_x, phys_y, RDOWN)
        at(phys_x, phys_y, RUP)

    loop = QEventLoop()

    def capture() -> None:
        popup = QApplication.activePopupWidget()
        captured["type"] = type(popup).__name__ if popup is not None else None
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "de.png"))
        if isinstance(popup, QMenu):
            captured["actions"] = [a.text() for a in popup.actions()]
            popup.close()
        loop.quit()

    QTimer.singleShot(300, do_real_right_click)
    QTimer.singleShot(900, capture)
    QTimer.singleShot(4000, loop.quit)  # safety net
    loop.exec()

    assert captured.get("type") == "QMenu", (
        "no context menu on a real OS right-click; "
        f"got {captured.get('type')!r}. screenshot: {tmp_path / 'de.png'}"
    )
    assert captured.get("actions") == ["Load File", "Remove from Data Sources"]
```

- [ ] **Step 2: ヘッドレス収集を確認**

Run: `uv run pytest tests/realgui/test_data_explorer_realclick.py --collect-only -q`
Expected: 1 test collected・import エラー無し。

- [ ] **Step 3: production 修正**

`src/valisync/gui/views/data_explorer_view.py` の import を差し替え:

```python
from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
)
```

（`QContextMenuEvent` を `QtGui` の import から**削除**。）

`self.tree = QTreeView(self)`（line 74）の直後に追加:

```python
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
```

`self.tree.activated.connect(self._on_activated)`（line 77）の直後に追加:

```python
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
```

`contextMenuEvent`（line 190-195）を**削除**し、`build_context_menu` の直後に追加:

```python
    def _show_context_menu(self, pos: QPoint) -> None:
        """Show the file menu on a real right-click (CustomContextMenu).

        Driven by ``QTreeView.customContextMenuRequested`` so the menu fires on
        the real OS path (mirrors FileBrowser PR#11); overriding contextMenuEvent
        on this container does not fire reliably from the child item view.
        """
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        global_pos = self.tree.viewport().mapToGlobal(pos)
        self.build_context_menu(self.fs_model.filePath(index)).exec(global_pos)
```

- [ ] **Step 4: 既存 headless が無回帰なことを確認**

Run: `uv run pytest tests/gui/test_context_menus.py::TestDataExplorerMenu tests/gui/test_data_explorer_view.py -q`
Expected: 全 pass（`build_context_menu` 不変）。

- [ ] **Step 5: フルゲート**

Run: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`
Expected: headless 全 pass・0 errors、lint/format/type クリーン。

- [ ] **Step 6: Commit**

```bash
git add src/valisync/gui/views/data_explorer_view.py tests/realgui/test_data_explorer_realclick.py
git commit -m "feat(gui): DataExplorer を CustomContextMenu 化＋実右クリック realgui"
```

---

### Task 3: GraphPanel の ViewBox 既定メニューを抑止＋実右クリック realgui

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`
- Create: `tests/realgui/test_graph_panel_menu_realclick.py`

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input.py` の `RDOWN, RUP, at, skip_unless_real_display`。
- Produces: production は新 public シンボル無し（ViewBox 生成ループ内で `setMenuEnabled(False)` を追加するのみ）。

**背景**: 現状 `graph_panel_view.py:1753` の `contextMenuEvent` override が自前メニュー（Add Panel / Remove Panel / Reset All Axes / メインカーソル / サブカーソル（Δ）/ 補間方式）を出す。だが pyqtgraph の `ViewBox` は既定で右クリックに "Plot Options" メニューを出し、実右クリックではそれが**先に**勝って自前メニューが出ない。ViewBox 生成ループ（`_reconcile_axes`）は line 984-998、各 `vb` を `vb.disableAutoRange()`（line 987）で初期化。master は line 992、セカンダリは overlay。**全 vb**（master＋セカンダリ）の既定メニューを抑止しないと多軸時に取りこぼす。

- [ ] **Step 1: realgui テストを作成**

`tests/realgui/test_graph_panel_menu_realclick.py`:

```python
"""Layer C: real-OS-input test for the GraphPanel context menu.

Opt-in — run with ``--realgui`` on Windows + a real display. A genuine
right-click on the plot must raise the panel's OWN menu ("Add Panel" …), NOT
pyqtgraph's default "Plot Options" ViewBox menu. This is the conflict that
``ViewBox.setMenuEnabled(False)`` resolves; a synthesized event cannot prove it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import RDOWN, RUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_panel_menu_wins_over_pyqtgraph_on_real_right_click(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()

    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = GraphPanelView(GraphPanelVM(Session()))
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 520, 360)
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(lambda: view.plot_widget.viewport().width() > 0, timeout=3000)

    # Right-click the centre of the plot viewport (inside the master ViewBox,
    # clear of the Y axis on the left and any grips/frame at the edges).
    dpr = view.devicePixelRatioF()
    vp = view.plot_widget.viewport()
    center = vp.rect().center()
    gp = vp.mapToGlobal(center)
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)

    captured: dict[str, object] = {}

    def do_real_right_click() -> None:
        at(phys_x, phys_y, RDOWN)
        at(phys_x, phys_y, RUP)

    loop = QEventLoop()

    def capture() -> None:
        popup = QApplication.activePopupWidget()
        captured["type"] = type(popup).__name__ if popup is not None else None
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "gp.png"))
        if isinstance(popup, QMenu):
            captured["actions"] = [a.text() for a in popup.actions()]
            popup.close()
        loop.quit()

    QTimer.singleShot(300, do_real_right_click)
    QTimer.singleShot(900, capture)
    QTimer.singleShot(4000, loop.quit)  # safety net
    loop.exec()

    assert captured.get("type") == "QMenu", (
        "no context menu on a real OS right-click; "
        f"got {captured.get('type')!r}. screenshot: {tmp_path / 'gp.png'}"
    )
    actions = captured.get("actions") or []
    assert "Add Panel" in actions, (
        "real right-click did not raise the panel's own menu (pyqtgraph default "
        f"won?); actions={actions!r}. screenshot: {tmp_path / 'gp.png'}"
    )
```

- [ ] **Step 2: ヘッドレス収集を確認**

Run: `uv run pytest tests/realgui/test_graph_panel_menu_realclick.py --collect-only -q`
Expected: 1 test collected・import エラー無し。

- [ ] **Step 3: production 修正（全 ViewBox の既定メニュー抑止）**

`src/valisync/gui/views/graph_panel_view.py`、ViewBox 初期化ループ内の `vb.disableAutoRange()`（line 987）の直後に1行追加:

```python
            vb.disableAutoRange()
            # Suppress pyqtgraph's default right-click "Plot Options" menu so the
            # panel's own contextMenuEvent wins on a real OS right-click. Applied
            # to every ViewBox (master + secondary overlays) so a right-click on
            # any axis region raises the panel menu, not pyqtgraph's.
            vb.setMenuEnabled(False)
```

- [ ] **Step 4: 既存 headless が無回帰なことを確認**

Run: `uv run pytest tests/gui/test_context_menus.py::TestGraphPanelMenu tests/gui/test_graph_panel_cursor.py -q`
Expected: 全 pass（自前 `build_context_menu`／`contextMenuEvent` の Layer B 経路は不変）。

- [ ] **Step 5: フルゲート**

Run: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`
Expected: headless 全 pass・0 errors、lint/format/type クリーン。

- [ ] **Step 6: Commit**

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/realgui/test_graph_panel_menu_realclick.py
git commit -m "feat(gui): GraphPanel の ViewBox 既定メニュー抑止＋実右クリック realgui"
```

---

## コントローラ ①ゲート（実 win32・honest RED→GREEN）

実装3タスク完了後、コントローラが `/gui-verify` を実 win32 で実行（実装サブエージェントは headless のため不可）。**カーソル占有のためユーザーに席を外す確認を取ってから**実施する。

各経路について honest 検証:

1. **GREEN（fix 適用済み）**: `uv run pytest --realgui tests/realgui/test_channel_browser_realclick.py tests/realgui/test_data_explorer_realclick.py tests/realgui/test_graph_panel_menu_realclick.py -v` → 3 件 pass・ハング無し。証拠ログ＋スクショ（`ch.png`/`de.png`/`gp.png`）を残す。
2. **RED（配線破壊で1度実証）**: 各 production 修正行を一時的に外して当該 realgui が RED になることを確認し復元する:
   - ChannelBrowser: `self.tree.setContextMenuPolicy(...)` 行をコメントアウト → `test_channel_browser_realclick` が RED（`activePopupWidget` が None / 自前メニュー出ず）。
   - DataExplorer: 同様に `setContextMenuPolicy` 行 → RED。
   - GraphPanel: `vb.setMenuEnabled(False)` 行をコメントアウト → `test_graph_panel_menu_realclick` が RED（pyqtgraph "Plot Options" が勝ち "Add Panel" 不在）。
   - 各確認後ただちに復元し、再度 `uv run pytest` headless＋当該 realgui GREEN を確認。
3. **全 realgui 無回帰**: `uv run pytest --realgui tests/realgui/ -v` → Phase 1 の 12 件＋本 Phase の 3 件＝**15 件 pass・ハング無し**。

ゲート判定: (a) headless full 0 errors (b) realgui 証拠（GREEN＋RED 実証） (c) CI 緑（push 後）。3点充足で finishing-a-development-branch（push + PR）。

---

## Self-Review

**1. Spec coverage（§クラス1 / H5-H7）**: ChannelBrowser=Task1・DataExplorer=Task2・GraphPanel=Task3 が spec lines 40-42 の各修正に1:1対応。honest RED（spec line 42/106）はコントローラ①ゲートでカバー。✔

**2. Placeholder scan**: 各 Step に実コード（import 差し替え・追加メソッド・realgui 全文）を記載。`build_context_menu` は不変のため再掲不要（既存コードを変更しない）。✔

**3. Type/シグネチャ整合**: 新ハンドラは全経路 `_show_context_menu(self, pos: QPoint) -> None`。realgui は全経路同型（`activePopupWidget`→QMenu→actions）。`setMenuEnabled` は pg.ViewBox メソッド（import 不要）。✔

**4. 挙動保存の確認**: ChannelBrowser は選択非変更（複数一括追加維持）。DataExplorer は indexAt 有効時のみ（現状と同条件）。GraphPanel は自前メニュー内容不変・既定抑止のみ。既存 headless（test_context_menus.py 等）は `build_context_menu` 直叩きのため全経路で無回帰。✔

**注意点（実装者向け）**: (a) DataExplorer の `QFileSystemModel` はディレクトリを非同期populate するため realgui は `waitUntil(file_index 有効)` 必須（収集には影響しない）。(b) import 撤去後 `QtGui` から全 import が消える場合は import 文ごと削除（ruff F401）。(c) realgui は headless で必ず skip（実行しても offscreen でスキップ）＝コントローラ①ゲートが真の検証。
