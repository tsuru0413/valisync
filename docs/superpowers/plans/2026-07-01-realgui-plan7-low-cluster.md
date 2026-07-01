# realgui 拡充 Plan 7（最終・low クラスタ＋C3 ② 昇格）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 監査 `docs/realgui-coverage-audit.md` の優先度 low クラスタ（DataExplorer OS ファイルドロップ・ドロップ青枠ハイライト・非アクティブ軸 hover 仮フレーム・grip）と C3 caveat を消化し、realgui カバレッジ拡充を完了する。

**Architecture:** production 変更なし。realgui 新規2本（DataExplorer ドロップ・軸 hover 仮フレーム）＋既存 realgui 強化2本（ドロップ青枠 mid-drag assert・C3 描画ジオメトリ assert）＋docs 更新。全 realgui は Layer C（`--realgui`）で honest-RED（配線破壊で赤）付き。

**Tech Stack:** PySide6 / pyqtgraph / pytest / pytest-qt。realgui は `tests/realgui/_realgui_input.py`（`at`/`LDOWN`/`MOVE`/`LUP`/`drive_qdrag`/`skip_unless_real_display`）。

## Global Constraints

- **production 変更なし** — 本 Plan はテスト追加/強化と docs のみ。`git diff --name-only` は `tests/` と `docs/` のみ。
- **honest-RED 必須** — 各 realgui は「production の配線を破壊すると赤くなる」ことを docstring に明記。コントローラが実機 win32 ①ゲートで実証（merge 前 `/gui-verify`）。
- **QDrag は `drive_qdrag`（bg スレッド＋watchdog）で駆動** — 絶対に QTimer で駆動しない（memory `gui_realgui_drag_qtimer_hang`：OLE モーダルループでハング）。
- **hover は小刻み MOVE スイープ＋リトライ**（memory `gui_realgui_hover_needs_incremental_move`：一発 SetCursorPos では hoverMove 不発）。
- **座標は掴み先が読む座標系で算出**（memory `gui_realgui_zone_widgetspace_and_offscreen_clamp`）。ウィンドウは画面内に配置（オフスクリーン clamp 回避）。
- **realgui 新規ファイルは module 先頭に `pytestmark = pytest.mark.realgui`**、重い PySide6/valisync import は関数内に置く（offscreen collection 安全）。
- コミット trailer（全コミット必須）:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
  ```
- 品質ゲート（コミット前）: `uv run pytest`（0 errors・realgui は headless skip）／`uv run ruff check`／`uv run ruff format --check`／`uv run mypy src/`。

---

## File Structure

| ファイル | 責務 | 新規/変更 |
|---|---|---|
| `tests/realgui/test_data_explorer_file_drop.py` | DataExplorer への URL mime ドロップ→`_load_handler` 発火の realgui | 新規（Task 1） |
| `tests/realgui/test_signal_dnd_realclick.py` | 既存の信号 D&D realgui にドロップ青枠 mid-drag assert を追加 | 変更（Task 2） |
| `tests/realgui/test_axis_hover_frame.py` | 非アクティブ軸 hover→`_hover_axis_index` 更新（仮フレーム描画駆動状態）の realgui | 新規（Task 3） |
| `tests/realgui/test_move_then_resize.py` | C3：既存テストに viewbox 実描画高の縮小 assert を追加 | 変更（Task 4） |
| `docs/realgui-coverage-audit.md`・`docs/roadmap.md`・`CLAUDE.md` | low/grip/C3 を covered/昇格済に更新、realgui 拡充完了を反映 | 変更（Task 5） |

---

## Task 1: DataExplorer OS ファイルドロップ realgui（新規）

**Files:**
- Create: `tests/realgui/test_data_explorer_file_drop.py`

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input.py` の `drive_qdrag(press, waypoints, done=...)`・`skip_unless_real_display()`。`DataExplorerView(app_vm, *, load_handler=Callable[[Path|str], None])`（`data_explorer_view.py:50-58`）— `load_handler` を注入すると `dropEvent` の各 URL に対し `self._load_handler(local)` が呼ばれる（`data_explorer_view.py:166-175`）。
- Produces: なし（末端テスト）。

**背景**: `DataExplorerView`（QMainWindow）は `setAcceptDrops(True)`（R12.1・`data_explorer_view.py:80`）。`dragEnterEvent`（154）が `hasUrls()` を `acceptProposedAction()`、`dropEvent`（166）が各 URL を `url.toLocalFile()`→`self._load_handler(local)`。実 Explorer ドラッグは cross-process OLE で自動化不可のため、M5 と同型のアプリ内 QDrag URL mime を substitute とする（同一 IDropTarget 経路）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/realgui/test_data_explorer_file_drop.py` を新規作成:

```python
"""Layer C: real-OS-input test for OS file (URL-mime) drop onto DataExplorerView.

Low-cluster item — DataExplorer OS file-manager drop (R12.1). A real Windows
Explorer drag is not automatable (cross-process OLE DoDragDrop); an in-app QDrag
carrying a QUrl mime goes through the identical Qt IDropTarget path and is the
correct substitute (same rationale as test_file_drop_realclick.py / M5).

DataExplorerView is a QMainWindow with setAcceptDrops(True) (data_explorer_view.py:80).
Its dragEnterEvent (line 154) accepts hasUrls(); dropEvent (line 166) converts each
url.toLocalFile() and calls self._load_handler(local) (line 174). A load_handler is
injected at construction (data_explorer_view.py:56) so the drop is observable without
touching the real loader.

Honest RED: change DataExplorerView.dragEnterEvent (data_explorer_view.py:155-156)
from ``event.acceptProposedAction()`` to ``event.ignore()`` — the drop is refused,
dropEvent never runs, _load_handler is never called, and the assertion below fails.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import drive_qdrag, skip_unless_real_display

pytestmark = pytest.mark.realgui


def _make_source_and_explorer(qtbot: QtBot, local_file: Path):
    """Build a URL-drag source widget + DataExplorerView shown side by side.

    Returns (source, explorer, load_spy). ``load_spy`` accumulates each path the
    injected load_handler receives. Qt/valisync imports are kept inside the
    function so offscreen collection never triggers display-dependent imports.
    """
    from PySide6.QtCore import QMimeData, Qt, QUrl
    from PySide6.QtGui import QDrag
    from PySide6.QtWidgets import QApplication, QWidget

    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.data_explorer_view import DataExplorerView

    class _UrlSource(QWidget):
        """Press → move → QDrag with QUrl mime → enter OLE modal loop."""

        def __init__(self, url: QUrl) -> None:
            super().__init__()
            self._url = url
            self._press_pos = None
            self._dragging = False
            self.setFixedSize(80, 60)

        def mousePressEvent(self, event) -> None:  # type: ignore[override]
            if event.button() == Qt.MouseButton.LeftButton:
                self._press_pos = event.pos()
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
            if (
                self._press_pos is not None
                and not self._dragging
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                self._dragging = True
                mime = QMimeData()
                mime.setUrls([self._url])
                drag = QDrag(self)
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.CopyAction)
                self._press_pos = None
                self._dragging = False
            super().mouseMoveEvent(event)

    url = QUrl.fromLocalFile(str(local_file))
    source = _UrlSource(url)
    qtbot.addWidget(source)
    source.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    source.setGeometry(60, 320, 80, 60)
    source.show()
    qtbot.waitExposed(source)

    load_spy: list[str] = []
    explorer = DataExplorerView(
        AppViewModel(Session()),
        load_handler=lambda p: load_spy.append(str(p)),
    )
    qtbot.addWidget(explorer)
    explorer.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    explorer.setGeometry(220, 160, 700, 500)
    explorer.show()
    qtbot.waitExposed(explorer)

    for _ in range(3):
        QApplication.processEvents()

    return source, explorer, load_spy


def _widget_phys(w, lx: int, ly: int) -> tuple[int, int]:
    from PySide6.QtCore import QPoint

    dpr = w.devicePixelRatioF()
    gp = w.mapToGlobal(QPoint(lx, ly))
    return round(gp.x() * dpr), round(gp.y() * dpr)


def test_data_explorer_file_drop_calls_load_handler(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Low: in-app QDrag with QUrl mime dropped on DataExplorer → _load_handler(path).

    Exercises the real Qt OLE IDropTarget chain: QDrag.exec() in source →
    DataExplorerView.dragEnterEvent accepts URL mime → dropEvent →
    _load_handler(local) per URL. The QTreeView child does not accept drops, so
    the drag reaches the QMainWindow drop handler (structural point under test).
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    local_file = tmp_path / "explorer_drop.csv"
    local_file.write_text("t,v\n0.0,1.0\n", encoding="utf-8")

    source, explorer, load_spy = _make_source_and_explorer(qtbot, local_file)

    press = _widget_phys(source, source.width() // 2, source.height() // 2)
    # Drop onto the centre of the explorer window (tree area). The QMainWindow
    # owns setAcceptDrops; the tree child does not accept drops, so the drag
    # bubbles to DataExplorerView.dropEvent.
    target = _widget_phys(explorer, explorer.width() // 2, explorer.height() // 2)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: len(load_spy) > 0)

    for _ in range(4):
        QApplication.processEvents()

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "explorer_drop.png")
        )

    assert len(load_spy) == 1, (
        "load_handler not called — URL mime drop did not reach "
        f"DataExplorerView.dropEvent. screenshot: {tmp_path / 'explorer_drop.png'}"
    )
    assert Path(load_spy[0]).resolve() == Path(str(local_file)).resolve(), (
        f"load_handler got wrong path: {load_spy[0]!r} != {str(local_file)!r}"
    )
```

- [ ] **Step 2: 収集＋headless full を確認**

Run: `uv run pytest --collect-only tests/realgui/test_data_explorer_file_drop.py`
Expected: 1 item collected（import エラーなし）。
Run: `uv run pytest -q`
Expected: 全 pass（realgui は headless skip）・0 errors。

- [ ] **Step 3: 品質ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/realgui/test_data_explorer_file_drop.py
git commit  # trailer 付き（Global Constraints 参照）
# メッセージ: test(realgui): DataExplorer OS ファイルドロップ（URL mime substitute・_load_handler spy）
```

**honest-RED（ゲート記録）**: `data_explorer_view.py:155-156` の `event.acceptProposedAction()` を `event.ignore()` に → ドロップ拒否 → `_load_handler` 未呼出 → `len(load_spy) == 1` 失敗 → RED。

---

## Task 2: ドロップ青枠ハイライトの mid-drag assert 強化（既存 realgui）

**Files:**
- Modify: `tests/realgui/test_signal_dnd_realclick.py`

**Interfaces:**
- Consumes: 既存 `_make_browser_and_panel(qtbot, tmp_path)`（`browser, panel, keys` を返す）・`_row_phys`・`_panel_point_phys`・`drive_qdrag`。`GraphPanelView.is_drop_highlighted() -> bool`（`graph_panel_view.py:1646`）と `styleSheet()`（`_set_drop_highlight` が border を設定・`graph_panel_view.py:1650-1653`）。
- Produces: なし。

**背景**: 信号ドラッグが GraphPanelView に enter すると `dragEnterEvent`（`graph_panel_view.py:1656-1660`）が `_set_drop_highlight(True)`（青枠 border stylesheet）。現状 realgui は `drop_seen` のみ assert し**青枠を検証していない**（監査「相乗り」は想定のまま）。ドラッグ中の `is_drop_highlighted()` を捕捉して honest 化する。

- [ ] **Step 1: 失敗するテストを書く**

`test_signal_dnd_realclick.py` の**末尾**に、mid-drag 捕捉用の capturing panel と新規テストを追加（既存 `_make_browser_and_panel` は共有 `_CapturingPanel` を返すため、ここでは専用のサブクラスをローカルに用意して青枠を捕捉する）:

```python
def test_drop_highlight_visible_mid_drag(qtbot: QtBot, tmp_path: Path) -> None:
    """Low: the blue drop-highlight border is shown mid-drag and cleared after drop.

    GraphPanelView.dragEnterEvent sets _set_drop_highlight(True) for signal mime
    (graph_panel_view.py:1656-1660); dropEvent clears it. Existing D&D realgui only
    asserts drop_seen — this asserts the honest visual state: is_drop_highlighted()
    is True while the drag hovers, and False after the drop.

    Honest RED: make GraphPanelView._set_drop_highlight (graph_panel_view.py:1650)
    a no-op (``self._drop_active = active`` → ``pass``) — the highlight never turns
    on, mid_highlighted stays False, and the assertion fails.
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.channel_browser_view import ChannelBrowserView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    class _HighlightCapturingPanel(GraphPanelView):
        mid_highlighted: bool = False
        mid_border: bool = False
        drop_seen: bool = False

        def dragMoveEvent(self, ev: object) -> None:  # type: ignore[override]
            super().dragMoveEvent(ev)  # type: ignore[arg-type]
            # Capture the drop-highlight state WHILE the drag hovers the panel.
            if self.is_drop_highlighted():
                self.mid_highlighted = True
                if "border" in self.styleSheet():
                    self.mid_border = True

        def dropEvent(self, ev: object) -> None:  # type: ignore[override]
            super().dropEvent(ev)  # type: ignore[arg-type]
            self.drop_seen = True

    from PySide6.QtCore import Qt

    csv = tmp_path / "d.csv"
    csv.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    file_key = app_vm.request_load(csv, _fmt())
    app_vm.set_active_file(file_key)

    browser = ChannelBrowserView(ChannelBrowserVM(app_vm))
    panel = _HighlightCapturingPanel(GraphPanelVM(app_vm.session))
    qtbot.addWidget(browser)
    qtbot.addWidget(panel)
    for w, x in ((browser, 200), (panel, 640)):
        w.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        w.setGeometry(x, 250, 400, 360)
        w.show()
        qtbot.waitExposed(w)
    qtbot.waitUntil(
        lambda: browser.tree.visualRect(browser.model.index(0, 0)).height() > 0,
        timeout=3000,
    )
    QApplication.processEvents()

    _select_rows(browser, [0])
    QApplication.processEvents()

    press = _row_phys(browser, 0)
    target = _panel_point_phys(panel, panel.width() // 2, panel.height() // 2)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen)

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "drop_highlight.png")
        )

    assert panel.drop_seen, (
        f"no dropEvent — QDrag never completed. screenshot: {tmp_path / 'drop_highlight.png'}"
    )
    assert panel.mid_highlighted, (
        "drop-highlight (is_drop_highlighted) was never True mid-drag — the blue "
        f"border feedback is broken. screenshot: {tmp_path / 'drop_highlight.png'}"
    )
    assert panel.mid_border, "styleSheet had no border while highlighted mid-drag"
    # Cleared after drop.
    assert not panel.is_drop_highlighted(), (
        "drop-highlight not cleared after drop — _set_drop_highlight(False) not reached"
    )
```

- [ ] **Step 2: 収集＋headless full**

Run: `uv run pytest --collect-only tests/realgui/test_signal_dnd_realclick.py`
Expected: 既存＋新規1本が collected。
Run: `uv run pytest -q`
Expected: 全 pass・0 errors。

- [ ] **Step 3: 品質ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/realgui/test_signal_dnd_realclick.py
git commit  # test(realgui): ドロップ青枠ハイライトの mid-drag assert（is_drop_highlighted＋border）
```

**honest-RED**: `graph_panel_view.py:1651` の `self._drop_active = active` を `pass` 化（`_set_drop_highlight` no-op）→ `mid_highlighted` False → RED。

---

## Task 3: 非アクティブ軸 hover 仮フレームの mid-hover assert（新規）

**Files:**
- Create: `tests/realgui/test_axis_hover_frame.py`

**Interfaces:**
- Consumes: `tests/gui/_panel_factory.make_two_axis_panel() -> GraphPanelView`（軸0=s1・軸1=s2・どちらも非アクティブで返る）。`GraphPanelView.set_active_axis(index)`（`graph_panel_view.py:1057`）・`_hover_axis_index`（`660`・`set_hover_axis` 経由で更新・`1071`）。`_AlignedAxisItem.paint` が `_is_active_or_hover()`（`328`）で仮フレームを描画。`view._y_axes[i]` は各軸の `_AlignedAxisItem`。
- Produces: なし。

**背景**: 非アクティブ軸を hover すると `_AlignedAxisItem.hoverEnterEvent`→`view.set_hover_axis(index)`→`_hover_axis_index` 更新→`paint` が仮フレームを描く。仮フレームは即時モード描画（別 QGraphicsItem でない）ため `isVisible()` を持たない。**描画を駆動する `_hover_axis_index` が最も honest な assert 代理**。純粋な外観はスクショ＋`/verify`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/realgui/test_axis_hover_frame.py` を新規作成:

```python
"""Layer C: real-OS-input test for the non-active-axis hover provisional frame.

Low-cluster item — hovering a non-active Y axis draws a provisional frame that
signals "clickable to activate". _AlignedAxisItem.paint draws it when
_is_active_or_hover() is True (graph_panel_view.py:328,374); hovering sets
GraphPanelView._hover_axis_index via set_hover_axis (line 1071). The frame is
immediate-mode paint (no separate QGraphicsItem), so _hover_axis_index — the state
that gates the paint — is the honest assertable proxy. The visual appearance is
captured to a screenshot for /verify.

Real OS hover only: pyqtgraph's hoverMove dispatch needs genuine incremental
mouse movement; a one-shot SetCursorPos delivers no hoverMoveEvent
(memory gui_realgui_hover_needs_incremental_move).

Honest RED: make GraphPanelView.set_hover_axis (graph_panel_view.py:1071) a no-op
(early ``return`` before it assigns _hover_axis_index) — hovering never updates the
state, mid_hover_index stays None, and the assertion fails.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import MOVE, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_non_active_axis_hover_sets_hover_index(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Low: hovering a NON-active axis sets _hover_axis_index (drives the frame paint).

    Axis 0 is made active; then the cursor hovers axis 1 (non-active). The hover
    must set _hover_axis_index == 1 (which drives _AlignedAxisItem's provisional
    frame). This is real-OS-only because hoverMove needs incremental movement.
    """
    skip_unless_real_display()
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # Place fully on-screen (avoid off-screen cursor clamp, memory
    # gui_realgui_zone_widgetspace_and_offscreen_clamp).
    screen = QApplication.primaryScreen().availableGeometry()
    view.setGeometry(screen.x() + 80, screen.y() + 80, 800, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )

    view.set_active_axis(0)  # axis 0 active → axis 1 is the non-active hover target
    QApplication.processEvents()
    assert view._active_axis_index == 0

    axis = view._y_axes[1]  # the NON-active axis (_AlignedAxisItem)
    gv = view.plot_widget
    dpr = view.devicePixelRatioF()
    w = axis.width()
    h = axis.boundingRect().height()

    def item_to_phys(lx: float, ly: float) -> tuple[int, int]:
        sp = axis.mapToScene(QPointF(lx, ly))
        g = gv.viewport().mapToGlobal(gv.mapFromScene(sp))
        return round(g.x() * dpr), round(g.y() * dpr)

    # Sweep onto the axis-1 interior in small steps until the hover registers.
    gx, gy = item_to_phys(w * 0.5, h * 0.5)
    hovered = False
    for _attempt in range(6):
        for off in range(30, -1, -3):
            at(gx, gy - off, MOVE)
            QApplication.processEvents()
            time.sleep(0.012)
        time.sleep(0.04)
        QApplication.processEvents()
        if view._hover_axis_index == 1:
            hovered = True
            break

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "axis_hover_frame.png")
        )

    assert hovered, (
        "hovering the non-active axis 1 never set _hover_axis_index == 1 — the "
        "provisional hover frame is not being driven. "
        f"got {view._hover_axis_index!r}. screenshot: {tmp_path / 'axis_hover_frame.png'}"
    )
    # Active axis is unchanged by a mere hover (hover is transient, never promoted).
    assert view._active_axis_index == 0, "hover must not change the active axis"
```

- [ ] **Step 2: 収集＋headless full**

Run: `uv run pytest --collect-only tests/realgui/test_axis_hover_frame.py`
Expected: 1 item。
Run: `uv run pytest -q`
Expected: 全 pass・0 errors。

- [ ] **Step 3: 品質ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/realgui/test_axis_hover_frame.py
git commit  # test(realgui): 非アクティブ軸 hover 仮フレーム（_hover_axis_index 駆動状態）
```

**honest-RED**: `graph_panel_view.py:1071` の `set_hover_axis` を早期 `return`（`_hover_axis_index` 未更新）→ `_hover_axis_index` が None のまま → `hovered` False → RED。

---

## Task 4: C3 ② 昇格 — 描画ジオメトリ assert 追加（既存 realgui 強化）

**Files:**
- Modify: `tests/realgui/test_move_then_resize.py:39-124`（`test_first_resize_after_axis_move_works`）

**Interfaces:**
- Consumes: 既存テストの `view`（`make_two_axis_panel`）・`view._view_boxes[0]`（軸0の viewbox・既存テストが resize 参照に使用）・`view.vm.axes[0].height_ratio`。
- Produces: なし。

**背景**: 既存テストの load-bearing assert は VM `height_ratio`（90/114/115 行）のみ＝② borderline（「VM は変わったが実描画は no-op」型 false-green を塞げない）。resize 前後で軸0 viewbox の**実描画高**（`sceneBoundingRect().height()`）が縮小したことを追加 assert する。

- [ ] **Step 1: 描画ジオメトリの before を捕捉**

`test_move_then_resize.py` の 90 行 `h0_before = view.vm.axes[0].height_ratio` の**直後**に、軸0 viewbox の実描画高を捕捉する行を追加:

```python
    h0_before = view.vm.axes[0].height_ratio
    # ② honest gate: capture the RENDERED height of axis 0's viewbox (not just the
    # VM ratio) so a "VM changed but paint no-op" false-green cannot pass.
    vb0_h_before = view._view_boxes[0].sceneBoundingRect().height()
```

- [ ] **Step 2: 描画ジオメトリの after を assert**

同ファイルの 114 行 `h0_after = view.vm.axes[0].height_ratio` の**直後**（既存の VM assert 群は残す）に、描画高の縮小 assert を追加:

```python
    h0_after = view.vm.axes[0].height_ratio
    vb0_h_after = view._view_boxes[0].sceneBoundingRect().height()
    # ② honest gate: the RENDERED viewbox must actually shrink — proving the resize
    # reached the paint path, not merely the VM. (VM ratio ~0.5 → ~0.30.)
    assert vb0_h_after < vb0_h_before * 0.85, (
        f"axis 0 viewbox did not shrink on screen: {vb0_h_after:.1f} "
        f"(was {vb0_h_before:.1f}) — VM ratio changed but the paint may be a no-op. "
        f"Screens: {tmp_path}"
    )
```

（既存の `assert h0_after < h0_before - 0.05` / `assert h0_after == pytest.approx(0.30, abs=0.07)` はそのまま残す。）

- [ ] **Step 3: 収集＋headless full**

Run: `uv run pytest --collect-only tests/realgui/test_move_then_resize.py`
Expected: 1 item（変更なし）。
Run: `uv run pytest -q`
Expected: 全 pass・0 errors（realgui skip）。

- [ ] **Step 4: 品質ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/realgui/test_move_then_resize.py
git commit  # test(realgui): C3 描画ジオメトリ assert 昇格（viewbox sceneBoundingRect 縮小）
```

**honest-RED**: 既存テストの主眼どおり、`reset_scene_drag_state`（QDrag 後の scene ドラッグ状態リセット）を外すと first-resize が no-op → `vb0_h_after` 不変 → 新 assert も RED（VM assert と二重に検出）。

---

## Task 5: grip 記録＋監査/roadmap/CLAUDE.md 更新（docs）

**Files:**
- Modify: `docs/realgui-coverage-audit.md`（low クラスタ・grip・C3 を covered/昇格済に更新）
- Modify: `docs/roadmap.md`（realgui 拡充完了を反映）
- Modify: `CLAUDE.md`（Phase 状況の realgui 横断行を完了に更新）

**Interfaces:** なし（docs のみ）。

**背景**: grip_hit_area_grabbability は既存 resize/zoom/move realgui が具体点掴みで実質カバー済み＝新規不要。監査に記録し、low クラスタ・C3 の消化と realgui 拡充完了を各 docs に反映する。

- [ ] **Step 1: 監査を更新**

`docs/realgui-coverage-audit.md` の「missing — 優先度 low」節（63-67 行付近）を更新: DataExplorer ドロップ＝covered（Task 1）、ドロップ青枠＝covered（Task 2・mid-drag assert）、軸 hover 仮フレーム＝covered（Task 3・`_hover_axis_index` assert）、grip＝covered（既存 grip ドラッグ realgui が具体点掴みで実証・新規不要）。「クリティック検出」節の C3 caveat（75 行）に「描画ジオメトリ assert へ昇格済（Task 4・PR #<TBD は付けない>）」を追記（PR 番号はプレースホルダにせず「Plan 7 で昇格」と記す）。

- [ ] **Step 2: roadmap／CLAUDE.md を更新**

`docs/roadmap.md` と `CLAUDE.md` の Phase 状況「realgui カバレッジ拡充（横断）」行を、**low クラスタ＋C3 完了＝realgui 拡充 全フェーズ完了**に更新（Phase 1-7 完了・missing 解消）。CLAUDE.md は薄く保つ方針ゆえポインタ更新に留める。

- [ ] **Step 3: コミット**

```bash
git add docs/realgui-coverage-audit.md docs/roadmap.md CLAUDE.md
git commit  # docs: realgui 拡充 Plan 7（low＋C3）完了を監査/roadmap/CLAUDE.md に反映
```

---

## Self-Review（writing-plans）

**Spec coverage:**
- spec §1 DataExplorer ドロップ → Task 1 ✓
- spec §2a ドロップ青枠 → Task 2 ✓
- spec §2b 軸 hover 仮フレーム → Task 3 ✓
- spec §3 C3 描画ジオメトリ → Task 4 ✓
- spec §4 grip 記録 → Task 5 ✓
- spec テスト戦略/ゲート（honest-RED・`/gui-verify`）→ 各タスクに honest-RED 明記＋Global Constraints ✓

**Placeholder scan:** 各コード step に完全コードを記載。Task 5 の PR 番号は「プレースホルダにせず Plan 7 で昇格と記す」と明示（後埋め TBD を回避）。他に TBD/TODO なし。

**Type consistency:** `is_drop_highlighted()->bool`・`set_hover_axis`/`_hover_axis_index`・`set_active_axis`・`_view_boxes[0].sceneBoundingRect().height()`・`DataExplorerView(..., load_handler=...)`・`drive_qdrag(press, waypoints, done=)` は全タスクで一貫（実コードで確認済み）。

**依存:** Task 1-4 は相互独立（別ファイル or 別テスト）。Task 5（docs）は 1-4 完了後に完了状態を反映。番号順で問題なし。

## 実機ゲート（merge 前・コントローラ）

全タスク完了後、`/gui-verify` ①証拠ゲート（実機 win32）:
- Stage A（GREEN＋無回帰）: 全 realgui（既存＋新規 Task1/3、強化 Task2/4）を `--realgui` で pass。
- honest-RED: Task1（dragEnter ignore）／Task2（_set_drop_highlight no-op）／Task3（set_hover_axis no-op）／Task4（reset_scene_drag_state 除去）を各々破壊→対象テスト RED→復元。
- C1/M11 と異なり全て実機依存＝cursor 占有（ユーザーに席外し確認）。
