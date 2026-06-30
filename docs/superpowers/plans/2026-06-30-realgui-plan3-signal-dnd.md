# realgui 信号 D&D 実配送 Implementation Plan (Phase 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChannelBrowser 行起点の信号 QDrag を `drive_qdrag` で実 OS 駆動し、GraphPanel の各ゾーン（プロット＝新軸／Y軸帯＝上書き／Ctrl＝結合）へ**実ドロップ**することを realgui で検証する（合成 sendEvent では再現不可の子→親バブリング配送経路）。

**Architecture:** ドラッグ元 ChannelBrowserView の子 `QTreeView`（`setDragEnabled(True)`＋Qt 組み込み `startDrag`）が `application/x-valisync-signal-keys` MIME の QDrag を起動。ドロップ先 GraphPanelView（親 `setAcceptDrops(True)`／子 plot_widget `setAcceptDrops(False)`）の `dropEvent` が `_zone_at(pos)` でゾーン分類し VM を呼ぶ。realgui は **2ウィジェット（browser＋panel）を画面同時表示**し、browser 行→panel ゾーンへ `drive_qdrag`（背景 OS スレッド＋watchdog）で実ドラッグする**新規クロスウィジェットハーネス**。C2（`QDrag.exec` モーダル中の同期 rebuild→破棄アイテム誤配送ハング）はコントローラ実機ゲートで empirically 確認し、ハング時のみ遅延化 fix を適用する。

**Tech Stack:** PySide6 / pyqtgraph / pytest / pytest-qt / ctypes(Win32)。共有 realgui 入力ヘルパ `tests/realgui/_realgui_input.py`（`drive_qdrag`/`skip_unless_real_display`/`VK_CONTROL` 等）。

## Global Constraints

- 設計 spec: `docs/superpowers/specs/2026-06-30-realgui-coverage-expansion-design.md`（§クラス2 = lines 47-56）。一次根拠: `docs/realgui-coverage-audit.md`（H1-H4）。
- **MVVM**: viewmodels に Qt/pyqtgraph を import しない。本プランは tests のみ追加（C2 fix を要する場合のみ `graph_panel_view.py`＝view を変更）。
- **既存配線は不変が原則**: ドラッグ元/ドロップ先/ゾーン分類/VM アクションは既に実装済み（合成テストで GREEN）。本プランは**実 QDrag 配送を初めて検証**する realgui を追加する（既存 18本超の合成 dropEvent テストは false-green）。
- **honest 検証**: `setAcceptDrops(True)`（graph_panel_view.py:677）を外すと実 QDrag の `dropEvent` 不到達で realgui が RED。RED→GREEN は実 win32 のみで証明可能＝**コントローラの `/gui-verify` ①ゲート**で実施（実装サブエージェントは headless のため `--realgui` を実行しない）。
- **QDrag 駆動は必ず `drive_qdrag`（背景 OS スレッド＋watchdog）**。`QTimer` 駆動は OLE モーダルでハング（memory `gui_realgui_drag_qtimer_hang`）。
- **C2（memory `gui_realgui_qdrag_rebuild_stale_scene`）**: 信号ドロップ dropEvent の rebuild は現状**同期**（graph_panel_view.py:1686-1701、軸移動は QTimer.singleShot 遅延済み 1672）。単発ドロップでは顕在化しない可能性があるため、**ドロップ→直後ジェスチャ**の C2 ガード realgui で実機確認し、**ハングした場合のみ**遅延化 fix を適用する（empirical）。
- realgui(Layer C) は `@pytest.mark.realgui`＋`--realgui` opt-in、配置 `tests/realgui/`。
- コミットメッセージ末尾に必須トレーラ（`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k`）。
- コミット前ゲート: `uv run pytest`（headless 0 errors）/ `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。worktree なら先に `uv sync --extra dev`。

## File Structure

- Create: `tests/realgui/test_signal_dnd_realclick.py` — クロスウィジェット信号 D&D realgui（共有ハーネス＋H1-H4＋C2 ガード）。
- (contingent) Modify: `src/valisync/gui/views/graph_panel_view.py` — C2 ハング確認時のみ信号ドロップ rebuild を `QTimer.singleShot` 遅延化。

**参照（不変・読むだけ）**: `tests/realgui/test_multi_column_axis.py`（`_CapturingView`＋`drive_qdrag`＋scene→物理座標＋drop_seen の正準パターン）、`tests/realgui/test_channel_browser_realclick.py`（ChannelBrowser 構築＋tree 行の物理座標）、`tests/gui/test_context_menus.py`（`_setup_app_2sig` 同型のデータ込み構築）。検証済みアンカー: dropEvent=graph_panel_view.py:1655-1703、ゾーン定数=64-69、`_zone_at`=1221-1224、`_axis_index_at`=1226、accept_drops=676-677、VM `create_new_axis`=graph_panel_vm.py:218 / `overwrite_axis`=204 / `add_signal_to_axis`=181、MIME=qt_signal_models.py:27。

---

### Task 1: クロスウィジェットハーネス確立＋H1（プロット→新軸）

**Files:**
- Create: `tests/realgui/test_signal_dnd_realclick.py`

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input.py` の `drive_qdrag`, `skip_unless_real_display`。
- Produces: モジュール内ヘルパ `_CapturingPanel`（drop_seen 付き GraphPanelView）と `_make_browser_and_panel(qtbot, tmp_path)`（2ウィジェット＋共有セッション）を Task 2-4 が再利用。

**最重要リスク（このタスクの本質）**: ChannelBrowser→GraphPanel のクロスウィジェット実 QDrag は**未確立の手法**。(a) browser と panel が**同一セッション**を共有し、browser が出す名前空間付きキー（例 `f"{file_key}::a"`、test_context_menus.py:107 参照）が **GraphPanelVM の `_signal_map()` で解決される**こと、(b) 2ウィジェットを画面上の別位置に同時表示し、tree 行→panel ゾーンへドラッグできること、を確立する。`app_vm.session` を GraphPanelVM に渡してキー空間を一致させる（解決しない場合は GraphPanelVM のキー生成と request_load の名前空間付与を読んで構築を調整する＝このタスクの確立作業）。

- [ ] **Step 1: realgui ファイルを作成（ハーネス＋H1）**

`tests/realgui/test_signal_dnd_realclick.py`:

```python
"""Layer C: real-OS-input tests for signal drag-and-drop from ChannelBrowser to GraphPanel.

Opt-in — run with ``--realgui`` on Windows + a real display. Drives a genuine
QDrag from a ChannelBrowser tree row (Qt's built-in startDrag) and drops it on a
GraphPanel zone, exercising the OS → QDrag.exec → dropEvent child→parent bubbling
that a synthesized event cannot reproduce (memory gui_drag_drop_not_sendevent_reproducible).
The QDrag is driven from a background OS thread with a watchdog (drive_qdrag) so
the OLE modal loop cannot hang the machine. See docs/gui-testing-layers.md (Layer C).
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import drive_qdrag, skip_unless_real_display

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


def _make_browser_and_panel(qtbot: QtBot, tmp_path: Path):
    """Build a ChannelBrowser (drag source) + GraphPanel (drop target) sharing one
    session, shown side by side. Returns (browser, panel, keys) where keys are the
    browser's signal keys in selection order (also valid in the panel's VM)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.channel_browser_view import ChannelBrowserView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    class _CapturingPanel(GraphPanelView):
        drop_seen: bool = False

        def dropEvent(self, ev: object) -> None:  # type: ignore[override]
            super().dropEvent(ev)  # type: ignore[arg-type]
            self.drop_seen = True

    csv = tmp_path / "d.csv"
    csv.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    file_key = app_vm.request_load(csv, _fmt())
    app_vm.set_active_file(file_key)

    browser = ChannelBrowserView(ChannelBrowserVM(app_vm))
    # Share the SAME session so the browser's namespaced keys resolve in the panel.
    panel = _CapturingPanel(GraphPanelVM(app_vm.session))
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
    QApplication.processEvents()
    keys = [browser.model.signal_key_at(browser.model.index(r, 0)) for r in range(2)]
    return browser, panel, keys


def _row_phys(browser, row: int) -> tuple[int, int]:
    """Physical-pixel center of a ChannelBrowser tree row."""
    idx = browser.model.index(row, 0)
    dpr = browser.devicePixelRatioF()
    center = browser.tree.visualRect(idx).center()
    gp = browser.tree.viewport().mapToGlobal(center)
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _panel_point_phys(panel, lx: int, ly: int) -> tuple[int, int]:
    """Physical-pixel of a logical (lx, ly) point in the panel's widget space."""
    from PySide6.QtCore import QPoint

    dpr = panel.devicePixelRatioF()
    gp = panel.mapToGlobal(QPoint(lx, ly))
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _select_rows(browser, rows: list[int]) -> None:
    from PySide6.QtCore import QItemSelectionModel

    sm = browser.tree.selectionModel()
    sm.clearSelection()
    flag = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for r in rows:
        sm.select(browser.model.index(r, 0), flag)


def test_drop_on_plot_creates_new_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """H1: drag signal row → drop on plot centre (ZONE_PLOT) → a new axis appears."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    browser, panel, keys = _make_browser_and_panel(qtbot, tmp_path)
    assert keys[0], "browser produced no signal key for row 0"
    n_before = len(panel.vm.axes)

    _select_rows(browser, [0])
    QApplication.processEvents()

    press = _row_phys(browser, 0)
    target = _panel_point_phys(panel, panel.width() // 2, panel.height() // 2)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen)

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "h1.png"))

    assert panel.drop_seen, (
        f"no dropEvent on the panel — real QDrag never completed. screenshot: {tmp_path / 'h1.png'}"
    )
    qtbot.waitUntil(lambda: keys[0] in panel.vm.curve_keys(), timeout=2000)
    assert len(panel.vm.axes) >= max(1, n_before), "no axis holds the dropped signal"
```

- [ ] **Step 2: ヘッドレス収集を確認**

Run: `uv run pytest tests/realgui/test_signal_dnd_realclick.py --collect-only -q`
Expected: 1 test collected・import エラー無し（実行すれば offscreen で skip）。

注意: `panel.vm.curve_keys()` が存在しない場合は GraphPanelVM の実 API（プロット済みキー列挙）を読んで置換する（例 `[e.signal_key for e in panel.vm._plotted]`）。`browser.model.signal_key_at` / `app_vm.session` も実 API に合わせて確認・調整する（ハーネス確立作業の一部）。

- [ ] **Step 3: フルゲート**

Run: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`
Expected: headless 全 pass・0 errors（新 realgui は skip）、lint/format/type クリーン。

- [ ] **Step 4: Commit**

```bash
git add tests/realgui/test_signal_dnd_realclick.py
git commit -m "test(realgui): 信号 D&D クロスウィジェットハーネス＋H1（プロット→新軸）"
```

> **コントローラ注記**: Task 1 commit 後、Task 2 へ進む前に**インターリーブ実機ゲート**で H1 を実 win32 実行し、クロスウィジェットハーネス（QDrag 起動・座標・キー解決・drop_seen）が機能することを証明する。ハーネスが動かない場合はここで修正してから Task 2-4 を書く（未確立手法のため前倒し検証）。

---

### Task 2: H2（Y軸帯→上書き）＋H3（Ctrl→結合）

**Files:**
- Modify: `tests/realgui/test_signal_dnd_realclick.py`

**Interfaces:**
- Consumes: Task 1 の `_make_browser_and_panel`, `_row_phys`, `_panel_point_phys`, `_select_rows`, `drive_qdrag`。`_realgui_input` の `VK_CONTROL`（H3 の Ctrl 結合）。

**前提**: H2/H3 は既存軸が1つある状態から始める。`_make_browser_and_panel` は空 panel を返すため、各テスト冒頭でまず1信号をプロットして軸を作る（row 0 を H1 同様プロットへドロップ、または `panel.vm.create_new_axis(keys[0])` で直接準備）。Y軸帯の座標は widget 左ガター（`x < _Y_AXIS_FIXED_WIDTH * column_count`、`_Y_AXIS_FIXED_WIDTH=72`）内・対象軸の縦バンド。`_zone_at` が ZONE_Y_INNER/OUTER を返す x を選ぶ（ガター右半分＝INNER、左半分＝OUTER）。

- [ ] **Step 1: H2/H3 を追記**

`tests/realgui/test_signal_dnd_realclick.py` 末尾に追記。import 行に `VK_CONTROL` を追加（`from tests.realgui._realgui_input import VK_CONTROL, drive_qdrag, skip_unless_real_display`）:

```python
def _prepare_one_axis(panel, keys, qtbot) -> None:
    """Plot keys[0] onto a fresh axis so a Y-band overwrite/join target exists."""
    from PySide6.QtWidgets import QApplication

    panel.vm.create_new_axis(keys[0])
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(lambda: keys[0] in panel.vm.curve_keys(), timeout=2000)


def _y_band_phys(panel, axis_index: int) -> tuple[int, int]:
    """Physical pixel inside the Y gutter band of axis_index (ZONE_Y_INNER region:
    right half of the gutter, closer to the plot)."""
    from valisync.gui.views.graph_panel_view import _Y_AXIS_FIXED_WIDTH

    ax = panel.vm.axes[axis_index]
    # Inner half of the gutter (closer to the plot) -> ZONE_Y_INNER.
    lx = int(_Y_AXIS_FIXED_WIDTH * (ax.column + 0.75))
    ly = int((ax.top_ratio + ax.height_ratio / 2) * panel.height())
    return _panel_point_phys(panel, lx, ly)


def test_drop_on_y_band_overwrites_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """H2: drop a 2nd signal on an existing axis's Y band (no Ctrl) → overwrite."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    browser, panel, keys = _make_browser_and_panel(qtbot, tmp_path)
    _prepare_one_axis(panel, keys, qtbot)  # keys[0] on axis 0

    _select_rows(browser, [1])
    QApplication.processEvents()
    press = _row_phys(browser, 1)
    target = _y_band_phys(panel, 0)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen)

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "h2.png"))

    assert panel.drop_seen, f"no dropEvent. screenshot: {tmp_path / 'h2.png'}"
    # Overwrite: axis 0 now holds keys[1] and NOT keys[0].
    qtbot.waitUntil(lambda: keys[1] in panel.vm.curve_keys(), timeout=2000)
    assert keys[0] not in panel.vm.curve_keys(), (
        f"overwrite did not replace the original signal. screenshot: {tmp_path / 'h2.png'}"
    )


def test_ctrl_drop_on_y_band_joins_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """H3: Ctrl-held drop on an existing axis's Y band → join (both signals kept)."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    browser, panel, keys = _make_browser_and_panel(qtbot, tmp_path)
    _prepare_one_axis(panel, keys, qtbot)  # keys[0] on axis 0

    _select_rows(browser, [1])
    QApplication.processEvents()
    press = _row_phys(browser, 1)
    target = _y_band_phys(panel, 0)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen, modifier_vk=VK_CONTROL)

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "h3.png"))

    assert panel.drop_seen, f"no dropEvent. screenshot: {tmp_path / 'h3.png'}"
    # Join: BOTH signals present.
    qtbot.waitUntil(
        lambda: keys[0] in panel.vm.curve_keys() and keys[1] in panel.vm.curve_keys(),
        timeout=2000,
    )
```

- [ ] **Step 2: ヘッドレス収集＋フルゲート**

Run: `uv run pytest tests/realgui/test_signal_dnd_realclick.py --collect-only -q`（3 collected）／`uv run pytest`（0 errors）／ruff/format/mypy。

注意: `ax.height_ratio`/`ax.top_ratio`/`ax.column` は YAxisVM の実属性名に合わせて確認・調整する。`_zone_at` のガター内外判定（inner_frac=0.5）に基づき INNER 座標を選ぶ。

- [ ] **Step 3: Commit**

```bash
git add tests/realgui/test_signal_dnd_realclick.py
git commit -m "test(realgui): 信号 D&D H2（Y帯上書き）＋H3（Ctrl 結合）"
```

---

### Task 3: H4（多選択一括）＋C2 ガード（ドロップ→直後ジェスチャ）

**Files:**
- Modify: `tests/realgui/test_signal_dnd_realclick.py`

**Interfaces:**
- Consumes: Task 1/2 のヘルパ。`_realgui_input` の `at`, `LDOWN`, `MOVE`, `LUP`（C2 ガードの後続プレーンドラッグ）。

- [ ] **Step 1: H4 を追記**

```python
def test_multiselect_drop_on_plot_adds_all(qtbot: QtBot, tmp_path: Path) -> None:
    """H4: Ctrl/Shift multi-select two rows → one drag → both signals added."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    browser, panel, keys = _make_browser_and_panel(qtbot, tmp_path)

    _select_rows(browser, [0, 1])  # both rows selected → mime carries both keys
    QApplication.processEvents()
    press = _row_phys(browser, 0)  # press on a selected row
    target = _panel_point_phys(panel, panel.width() // 2, panel.height() // 2)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)

    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen)

    for _ in range(3):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "h4.png"))

    assert panel.drop_seen, f"no dropEvent. screenshot: {tmp_path / 'h4.png'}"
    qtbot.waitUntil(
        lambda: keys[0] in panel.vm.curve_keys() and keys[1] in panel.vm.curve_keys(),
        timeout=2000,
    )
```

- [ ] **Step 2: C2 ガードを追記（ドロップ→直後ジェスチャ。同期 rebuild ならハング）**

このテストは「信号ドロップ直後に新軸スパイン上で実プレーンドラッグ（グリップ/ズーム）」を行う。dropEvent の rebuild が同期なら、`QDrag.exec` モーダル巻き戻り前に scene が破棄され次ジェスチャが破棄アイテムへ誤配送→ハング（memory `gui_realgui_qdrag_rebuild_stale_scene`）。**実機ゲートでハングしたら**コントローラが graph_panel_view.py:1686-1701 の信号ドロップ VM 呼びを軸移動同様 `QTimer.singleShot(0, ...)` で遅延化する（その際、同期 assert している既存 headless drop テストを deferred 対応に更新）。

```python
def test_drop_then_immediate_gesture_does_not_hang(qtbot: QtBot, tmp_path: Path) -> None:
    """C2 guard: a signal drop immediately followed by another gesture must not hang
    (synchronous dropEvent rebuild would mis-route the next gesture to a destroyed
    scene item — memory gui_realgui_qdrag_rebuild_stale_scene). The general watchdog
    in drive_qdrag plus a short post-drop gesture exercises the re-entrancy path."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    from tests.realgui._realgui_input import LDOWN, LUP, MOVE, at

    browser, panel, keys = _make_browser_and_panel(qtbot, tmp_path)

    _select_rows(browser, [0])
    QApplication.processEvents()
    press = _row_phys(browser, 0)
    target = _panel_point_phys(panel, panel.width() // 2, panel.height() // 2)
    mid = ((press[0] + target[0]) // 2, (press[1] + target[1]) // 2)
    drive_qdrag(press, [mid, target], done=lambda: panel.drop_seen)
    for _ in range(3):
        QApplication.processEvents()
    assert panel.drop_seen, f"no dropEvent. screenshot: {tmp_path / 'c2.png'}"

    # Immediately drive a plain drag inside the plot (pan/zoom zone). If the drop
    # rebuild left the scene stale this mis-routes / re-enters QDrag and the
    # drive_qdrag-less manual loop below would stall; we keep it short + bounded.
    qtbot.waitUntil(lambda: keys[0] in panel.vm.curve_keys(), timeout=2000)
    cx, cy = _panel_point_phys(panel, panel.width() // 2, panel.height() // 2)
    at(cx, cy, LDOWN)
    for dx in (8, 16, 24, 32):
        at(cx + dx, cy, MOVE)
        QApplication.processEvents()
    at(cx + 32, cy, LUP)
    QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "c2.png"))
    # Reaching here without a hang is the assertion; confirm the panel is still live.
    assert panel.vm.axes, "panel lost its axes after drop+gesture"
```

- [ ] **Step 3: ヘッドレス収集＋フルゲート**

Run: `uv run pytest tests/realgui/test_signal_dnd_realclick.py --collect-only -q`（5 collected）／`uv run pytest`（0 errors）／ruff/format/mypy。

- [ ] **Step 4: Commit**

```bash
git add tests/realgui/test_signal_dnd_realclick.py
git commit -m "test(realgui): 信号 D&D H4（多選択一括）＋C2 ガード（ドロップ→直後ジェスチャ）"
```

---

## コントローラ ①ゲート（実 win32・honest＋C2 empirical）

実装完了後（および Task 1 後のインターリーブで H1 を先行確認）、コントローラが `/gui-verify` を実 win32 実行。**カーソル占有のためユーザーに席を外す確認を取る**。

1. **GREEN**: `uv run pytest --realgui tests/realgui/test_signal_dnd_realclick.py -v` → H1-H4＋C2 ガードが pass・**ハング無し**。証拠ログ＋スクショ。
2. **C2 判定**: `test_drop_then_immediate_gesture_does_not_hang` が**ハングしたら** → 信号ドロップ rebuild を遅延化（graph_panel_view.py:1686-1701 を `QTimer.singleShot(0, ...)` 化、軸移動 1672 と同型）＋同期 assert の既存 headless drop テストを deferred 対応に更新 → 再ゲートで GREEN。ハングしなければ C2 は単発経路で非問題と記録（遅延化は見送り）。
3. **honest RED**: `setAcceptDrops(True)`（graph_panel_view.py:677）を一時除去 → 信号 realgui が RED（drop_seen False）を確認 → 復元。
4. **全 realgui 無回帰**: `uv run pytest --realgui tests/realgui/ -v` → Phase 1/2 の 15件＋本 Phase（5件）＝**20件 pass・ハング無し**（C2 fix を入れた場合は軸移動系の無回帰も確認）。

ゲート判定: (a) headless full 0 errors (b) realgui 証拠（GREEN＋RED＋C2 判定） (c) CI 緑。3点充足で finishing（push + PR）。

---

## Self-Review

**1. Spec coverage（§クラス2 / H1-H4＋C2）**: H1=Task1・H2/H3=Task2・H4＋C2 ガード=Task3。honest RED（setAcceptDrops）＝ゲート。C2 はゲートで empirical 判定（ユーザー承認）。✔

**2. Placeholder scan**: 各 realgui を全文記載。ただし**未確立 API**（`signal_key_at`/`app_vm.session`/`curve_keys`/`YAxisVM.top_ratio` 等）は「実 API に合わせ確認・調整」と明記＝Task 1 のハーネス確立で解決（実コードから導出可能）。✔

**3. Type 整合**: `_CapturingPanel(GraphPanelView)` drop_seen / `drive_qdrag(press, [waypoints], done=, modifier_vk=)` / ヘルパ戻り値は全 Task で一貫。✔

**4. リスク管理**: クロスウィジェット実 QDrag は未確立手法 → Task 1 で確立＋**インターリーブ実機ゲートで H1 を先行証明**してから H2-H4。C2 は同期 rebuild を empirical 確認（ハング時のみ fix）。✔

**注意点（実装者向け）**: (a) realgui は headless で必ず skip（コントローラ①ゲートが真の検証）。(b) Task 1 のハーネスが動くかは実機ゲートでのみ判明＝Task 1 後に前倒し確認する（コントローラ運用）。(c) `_make_browser_and_panel` のキー解決（browser 名前空間キー↔panel VM）が確立の肝。(d) C2 ガードの後続プレーンドラッグは drive_qdrag を使わない手動 at() ループ（QDrag でないため）＝短く bounded に。
