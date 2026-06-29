# R15 Global Cursor 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** プロット領域のクリックで全パネル同期の Global_Cursor を表示し、各信号の補間値をプロット内フロート表（読み取り面）に出す。

**Architecture:** MVVM。`GraphPanelVM` がカーソル時刻と補間値（Session 委譲）を保持、`GraphAreaVM` がアクティブタブ内の兄弟パネルへカーソル時刻をブロードキャスト（既存 X-sync 機構をミラー）。`GraphPanelView` が `pg.InfiniteLine` カーソルとフロート表 `CursorReadout` を描画し、プロット内クリックでカーソル設置。既存凡例 `pg.LegendItem` は撤去しフロート表が識別を兼ねる。

**Tech Stack:** Python 3.13 / uv / PySide6 / pyqtgraph / numpy / pytest(+pytest-qt)。

**設計 spec:** `docs/superpowers/specs/2026-06-29-gui-analysis-cursor-offset-design.md`（R15 担当）。本プランは analysis 増分3本（A=R15 / B=R16+R17 / C=R14）の **Plan A**。

## Global Constraints

- **MVVM 厳守**: `src/valisync/gui/viewmodels/` 配下は PySide6/pyqtgraph/Qt を import しない。コアは `Session` 経由のみ。
- **品質ゲート（各 commit 前に全通過）**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- **worktree 初回**: `uv sync --extra dev` を一度実行（しないと pytest が親の旧コードにフォールバック）。
- **GUI テストレイヤー**: Layer A/B は `tests/gui/`（headless・CI 実行）。Layer C は `tests/realgui/`、`@pytest.mark.realgui`、`--realgui` オプトイン（CI 除外）。
- **カーソル状態は非永続**（セッション/.vsproj に保存しない）。
- **コミット末尾トレーラ（全コミット必須）**:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NXpmTp2UtMGTSBGDCuSQg8
  ```
  以降の commit ステップは `-m "<subject>"` のみ示す。実行時に上記トレーラを必ず付与する。
- **InterpolationMethod 値**: `LINEAR="linear"` / `ZERO_ORDER_HOLD="zero_order_hold"` / `NEAREST="nearest"`（`from valisync.core.interpolation import InterpolationMethod`）。

---

## File Structure

- **Modify** `src/valisync/gui/viewmodels/graph_panel_vm.py` — カーソル状態（`cursor_t` / `interp_method`）、`set_cursor` / `set_interp_method` / `cursor_readings`、`CursorReading` dataclass。
- **Modify** `src/valisync/gui/viewmodels/graph_area_vm.py` — `propagate_cursor` 追加、`_on_panel_change` で `"cursor"` を兄弟へ配信。
- **Create** `src/valisync/gui/views/cursor_readout.py` — `CursorReadout(QWidget)` フロート表オーバーレイ。
- **Modify** `src/valisync/gui/views/graph_panel_view.py` — `InfiniteLine` カーソル、プロット内クリック設置、線ドラッグ移動、`"cursor"` 購読、`CursorReadout` 配線、凡例撤去、補間方式コンテキストサブメニュー。
- **Tests**: `tests/gui/test_graph_panel_vm.py`(拡張) / `tests/gui/test_graph_area_cursor.py`(新) / `tests/gui/test_cursor_readout.py`(新) / `tests/gui/test_graph_panel_cursor.py`(新) / `tests/realgui/test_global_cursor.py`(新)。

---

## Task 1: GraphPanelVM カーソル状態と補間値（Layer A）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`
- Test: `tests/gui/test_graph_panel_vm.py`

**Interfaces:**
- Consumes: 既存 `GraphPanelVM(session)` / `_signal_map() -> dict[str, Signal]` / `_plotted: list[_PlottedEntry]` / `_session.interpolate(signal, t, method) -> float | None` / `_notify(change)`。
- Produces:
  - `@dataclass class CursorReading: name: str; color: str; value: float | None; in_range: bool`
  - `GraphPanelVM.cursor_t: float | None`
  - `GraphPanelVM.interp_method: InterpolationMethod`
  - `GraphPanelVM.set_cursor(t: float | None) -> None`（`_notify("cursor")`）
  - `GraphPanelVM.set_interp_method(method: InterpolationMethod) -> None`（`_notify("cursor")`）
  - `GraphPanelVM.cursor_readings() -> list[CursorReading]`

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_vm.py` の import 群に追記:

```python
import pytest

from valisync.core.interpolation import InterpolationMethod
from valisync.gui.viewmodels.graph_panel_vm import CursorReading
```

ファイル末尾に追記:

```python
# ─── Global cursor (R15) ─────────────────────────────────────────────────────


def test_cursor_readings_linear_interpolation(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    key = _first_signal_key(session)
    vm.add_signal(key)
    # CSV helper: t=i*0.01, value=i  → between (0.00,0) and (0.01,1), linear@0.005 = 0.5
    vm.set_cursor(0.005)
    readings = vm.cursor_readings()
    assert len(readings) == 1
    assert readings[0].name == key
    assert readings[0].in_range is True
    assert readings[0].value == pytest.approx(0.5)


def test_cursor_readings_out_of_range_yields_none(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.set_cursor(5.0)  # 最終 timestamp 0.99 を超える
    reading = vm.cursor_readings()[0]
    assert reading.in_range is False
    assert reading.value is None


def test_cursor_readings_empty_when_no_cursor(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    assert vm.cursor_readings() == []


def test_set_cursor_notifies_cursor_change(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.set_cursor(0.1)
    assert "cursor" in changes
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k cursor -v`
Expected: FAIL（`ImportError: cannot import name 'CursorReading'` / `AttributeError: 'GraphPanelVM' object has no attribute 'set_cursor'`）

- [ ] **Step 3: 最小実装を書く**

`graph_panel_vm.py` の import に追記:

```python
from valisync.core.interpolation import InterpolationMethod
```

`RenderCurve` dataclass の直後に追記:

```python
@dataclass
class CursorReading:
    """1 信号のカーソル位置読み取り（Global_Cursor 用）。value=None は範囲外。"""

    name: str
    color: str
    value: float | None
    in_range: bool
```

`__init__` の末尾（`self._cache = {}` の後）に追記:

```python
        # Global cursor (R15) — transient, never persisted.
        self.cursor_t: float | None = None
        self.interp_method: InterpolationMethod = InterpolationMethod.LINEAR
```

クラス末尾（`_signal_map` の近く・public メソッド群）に追記:

```python
    # ─── Global cursor (R15) ─────────────────────────────────────────────────

    def set_cursor(self, t: float | None) -> None:
        """Set the global cursor time (None clears it) and notify."""
        self.cursor_t = t
        self._notify("cursor")

    def set_interp_method(self, method: InterpolationMethod) -> None:
        """Set the interpolation method used for cursor readings and notify."""
        self.interp_method = method
        self._notify("cursor")

    def cursor_readings(self) -> list[CursorReading]:
        """Interpolated value of each visible signal at cursor_t (Session-delegated).

        Returns [] when no cursor is set.  value=None / in_range=False when the
        cursor falls outside a signal's timestamp range (R15.5).
        """
        if self.cursor_t is None:
            return []
        sig_map = self._signal_map()
        out: list[CursorReading] = []
        for entry in self._plotted:
            if not entry.visible:
                continue
            sig = sig_map.get(entry.signal_key)
            if sig is None:
                out.append(CursorReading(entry.signal_key, entry.color, None, False))
                continue
            val = self._session.interpolate(sig, self.cursor_t, self.interp_method)
            out.append(
                CursorReading(entry.signal_key, entry.color, val, val is not None)
            )
        return out
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k cursor -v`
Expected: PASS（4 件）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "feat(gui): GraphPanelVM に Global_Cursor 状態と補間値読み取りを追加（R15）"
```

---

## Task 2: GraphAreaVM カーソル全パネル同期（Layer A）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_area_vm.py`
- Test: `tests/gui/test_graph_area_cursor.py`

**Interfaces:**
- Consumes: 既存 `GraphAreaVM(app_vm)` / `_tabs: list[_Tab]` / `_propagating: bool` / `_on_panel_change(panel, change)` / `panels(tab_index) -> list[GraphPanelVM]` / `add_panel(...)` / Task 1 の `GraphPanelVM.set_cursor` / `cursor_t`。
- Produces: `GraphAreaVM.propagate_cursor(tab_index: int, t: float | None) -> None`。`"cursor"` 変更時にアクティブタブ概念に依らずパネルの所属タブ内全パネルへ配信（X-sync トグルに**非依存**＝常時）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_area_cursor.py` を新規作成:

```python
"""GraphAreaVM の Global_Cursor 全パネル同期（R15.1）。"""

from __future__ import annotations

import csv
from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM


def _loaded_session(tmp_path: Path) -> tuple[Session, str]:
    csv_file = tmp_path / "data.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "s1"])
        for i in range(100):
            w.writerow([i * 0.01, float(i)])
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    session = Session()
    key = session.load(csv_file, fmt)
    return session, key


def test_cursor_propagates_to_sibling_panels(tmp_path):
    session, _ = _loaded_session(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.add_panel()  # tab 0 に 2 枚目のパネル
    panels = area.panels(0)
    assert len(panels) == 2

    panels[0].set_cursor(0.42)

    assert panels[1].cursor_t == 0.42


def test_cursor_propagation_is_not_infinite(tmp_path):
    # 兄弟へ配信→兄弟が再 notify→再帰、を _propagating ガードが止める
    session, _ = _loaded_session(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.add_panel()
    panels = area.panels(0)
    panels[0].set_cursor(0.1)  # 無限再帰なら RecursionError
    assert panels[0].cursor_t == 0.1
    assert panels[1].cursor_t == 0.1
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/gui/test_graph_area_cursor.py -v`
Expected: FAIL（`panels[1].cursor_t is None` — 配信未実装）

- [ ] **Step 3: 最小実装を書く**

`graph_area_vm.py` の既存 `_on_panel_change` を次に置換（`"cursor"` 分岐を追加）:

```python
    def _on_panel_change(self, panel: GraphPanelVM, change: str) -> None:
        """Propagate a panel's X-range (when synced) or cursor (always) to siblings."""
        if self._propagating:
            return
        for tab_index, tab in enumerate(self._tabs):
            if panel not in tab.panels:
                continue
            if change == "range" and tab.x_sync_enabled and panel.x_range is not None:
                lo, hi = panel.x_range
                self.propagate_x_range(tab_index, lo, hi)
            elif change == "cursor":
                # Cursor is a time value broadcast to all sibling panels regardless
                # of the X-sync toggle; each panel renders it within its own range.
                self.propagate_cursor(tab_index, panel.cursor_t)
            return
```

`propagate_x_range` の直後に追記:

```python
    def propagate_cursor(self, tab_index: int, t: float | None) -> None:
        """Push cursor time *t* to every panel in the tab (R15.1), guarded against re-entry."""
        self._propagating = True
        try:
            for panel in self._tabs[tab_index].panels:
                panel.set_cursor(t)
        finally:
            self._propagating = False
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_area_cursor.py -v`
Expected: PASS（2 件）。回帰確認: `uv run pytest tests/gui/test_graph_area_vm.py -v` も PASS。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/viewmodels/graph_area_vm.py tests/gui/test_graph_area_cursor.py
git commit -m "feat(gui): Global_Cursor をタブ内兄弟パネルへ配信（R15.1）"
```

---

## Task 3: CursorReadout フロート表ウィジェット（Layer B）

**Files:**
- Create: `src/valisync/gui/views/cursor_readout.py`
- Test: `tests/gui/test_cursor_readout.py`

**Interfaces:**
- Consumes: Task 1 の `CursorReading`。
- Produces:
  - `class CursorReadout(QWidget)`
  - `CursorReadout.set_readings(readings: list[CursorReading]) -> None` — 行を再構築。範囲外は値欄に `"範囲外"`。
  - `CursorReadout.row_texts() -> list[tuple[str, str]]` — テスト用 introspection: 各行 `(name, value_text)`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_cursor_readout.py` を新規作成:

```python
"""CursorReadout フロート表ウィジェット（R15.2 読み取り面）。"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.graph_panel_vm import CursorReading
from valisync.gui.views.cursor_readout import CursorReadout


def test_set_readings_builds_one_row_per_signal(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings(
        [
            CursorReading("csv::vCar", "#1f77b4", 12.34, True),
            CursorReading("csv::aLong", "#ff7f0e", 0.56, True),
        ]
    )
    texts = w.row_texts()
    assert len(texts) == 2
    assert texts[0][0] == "csv::vCar"
    assert "12.34" in texts[0][1]


def test_out_of_range_shows_label(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings([CursorReading("csv::vCar", "#1f77b4", None, False)])
    assert w.row_texts()[0][1] == "範囲外"


def test_empty_readings_clears_rows(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings([CursorReading("csv::vCar", "#1f77b4", 1.0, True)])
    w.set_readings([])
    assert w.row_texts() == []
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -v`
Expected: FAIL（`ModuleNotFoundError: cursor_readout`）

- [ ] **Step 3: 最小実装を書く**

`src/valisync/gui/views/cursor_readout.py` を新規作成:

```python
"""CursorReadout — プロット上にオーバーレイするカーソル読み取り面（R15.2）。

既存凡例を置き換え、色↔信号名の識別とカーソル補間値を1つの表に集約する。
カーソル表示に連動して可視/不可視を切り替える（呼び出し側が setVisible）。
Plan B(R16/R17) で Δy・統計列を追加するため、列生成は set_readings 内に閉じる。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QMouseEvent, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from valisync.gui.viewmodels.graph_panel_vm import CursorReading

_OUT_OF_RANGE = "範囲外"


def _format_value(reading: CursorReading) -> str:
    if not reading.in_range or reading.value is None:
        return _OUT_OF_RANGE
    return f"{reading.value:.4g}"


class CursorReadout(QWidget):
    """Floating per-panel readout table.  Rows: [colour swatch | name | value]."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CursorReadout")
        # Semi-opaque dark chip so it reads over the waveforms.
        self.setStyleSheet(
            "#CursorReadout { background: rgba(17,17,27,230);"
            " border: 1px solid #45475a; border-radius: 5px; }"
            " QLabel { color: #cdd6f4; }"
        )
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(6, 5, 6, 5)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(2)
        self._rows: list[tuple[str, str]] = []
        self._drag_offset = None  # for click-drag repositioning within parent

    def set_readings(self, readings: list[CursorReading]) -> None:
        """Rebuild the table from *readings* (one row per signal)."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows = []
        for r, reading in enumerate(readings):
            swatch = QLabel()
            pix = QPixmap(10, 10)
            pix.fill(QColor(reading.color))
            swatch.setPixmap(pix)
            name = QLabel(reading.name)
            value_text = _format_value(reading)
            value = QLabel(value_text)
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._grid.addWidget(swatch, r, 0)
            self._grid.addWidget(name, r, 1)
            self._grid.addWidget(value, r, 2)
            self._rows.append((reading.name, value_text))
        self.adjustSize()

    def row_texts(self) -> list[tuple[str, str]]:
        """Test introspection: [(name, value_text), ...] in row order."""
        return list(self._rows)

    # ── Drag to reposition within the parent plot (R: フロート表は移動可) ──
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(self.pos() + event.position().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_cursor_readout.py -v`
Expected: PASS（3 件）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/cursor_readout.py tests/gui/test_cursor_readout.py
git commit -m "feat(gui): カーソル読み取り面 CursorReadout フロート表を追加（R15.2）"
```

---

## Task 4: GraphPanelView 統合（カーソル線・クリック設置・凡例撤去・補間方式メニュー）（Layer B）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`
- Test: `tests/gui/test_graph_panel_cursor.py`
- Test(回帰): `tests/gui/test_graph_panel_view.py`（`legend_labels` 参照の更新）

**Interfaces:**
- Consumes: Task 1（`vm.set_cursor` / `vm.cursor_readings` / `vm.set_interp_method` / `vm.cursor_t`）、Task 3（`CursorReadout`）。既存 `_data_value(pos, "x")` / `_zone_at` / `ZONE_PLOT` / `master ViewBox`（`_view_boxes[0]`）/ `build_context_menu` / `refresh` / VM 購読（`_on_vm_change`）。
- Produces: View 内に `_cursor_line: pg.InfiniteLine` と `_readout: CursorReadout`。`"cursor"` 通知で両者を更新。クリック（移動なし）で `vm.set_cursor`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_cursor.py` を新規作成:

```python
"""GraphPanelView の Global_Cursor 配線（R15）— Layer B（headless）。

実 OS 入力・カーソル線の実ドラッグは Layer C（tests/realgui/test_global_cursor.py）で検証。
ここでは VM 連携・アイテム可視・凡例撤去をヘッドレスで確認する。
"""

from __future__ import annotations

import csv
from pathlib import Path

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView


def _vm_with_signal(tmp_path: Path) -> GraphPanelVM:
    csv_file = tmp_path / "d.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "s1"])
        for i in range(100):
            w.writerow([i * 0.01, float(i)])
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    session = Session()
    key = session.load(csv_file, fmt)
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    return vm


def test_setting_cursor_shows_line_and_readout(qtbot: QtBot, tmp_path):
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    assert not view.cursor_line_visible()  # カーソル未設定時は不可視

    vm.set_cursor(0.5)

    assert view.cursor_line_visible()
    assert view.cursor_line_value() == 0.5
    assert view.readout_visible()
    assert vm.cursor_readings()[0].value is not None


def test_clearing_cursor_hides_line_and_readout(qtbot: QtBot, tmp_path):
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    vm.set_cursor(0.5)
    vm.set_cursor(None)
    assert not view.cursor_line_visible()
    assert not view.readout_visible()


def test_legend_item_removed(qtbot: QtBot, tmp_path):
    # 凡例は撤去済み: GraphPanelView は _legend 属性を持たない
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    assert not hasattr(view, "_legend")


def test_context_menu_has_interp_methods(qtbot: QtBot, tmp_path):
    vm = _vm_with_signal(tmp_path)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    menu = view.build_context_menu()
    labels = [a.text() for a in menu.actions()]
    assert any("補間" in label for label in labels)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py -v`
Expected: FAIL（`AttributeError: cursor_line_visible` ほか）

- [ ] **Step 3: 最小実装を書く**

`graph_panel_view.py` のクラス `GraphPanelView.__init__` 末尾（VM 購読配線の後）に追記:

```python
        # ── Global cursor (R15) ──
        from valisync.gui.views.cursor_readout import CursorReadout

        self._cursor_line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#f9e2af", width=2))
        self._cursor_line.setVisible(False)
        self._cursor_line.setZValue(10)
        self._view_boxes[0].addItem(self._cursor_line, ignoreBounds=True)
        self._cursor_line.sigPositionChanged.connect(self._on_cursor_line_dragged)
        self._readout = CursorReadout(self)
        self._readout.setVisible(False)
        self._suppress_cursor_signal = False
```

`__init__` で `_reconcile_axes`/`refresh` が ViewBox を作り直す可能性があるため、`_cursor_line` の再アタッチは `refresh()` 内の再構築後にも行う。`refresh` の末尾（再構築完了後）に追記:

```python
        # Re-attach the cursor line to the (possibly rebuilt) master ViewBox.
        if self._cursor_line.scene() is None and self._view_boxes:
            self._view_boxes[0].addItem(self._cursor_line, ignoreBounds=True)
        self._sync_cursor_from_vm()
```

新規メソッド群をクラスに追記（`build_context_menu` の手前あたり）:

```python
    # ─── Global cursor (R15) ─────────────────────────────────────────────────

    def _on_vm_cursor_change(self) -> None:
        self._sync_cursor_from_vm()

    def _sync_cursor_from_vm(self) -> None:
        """Reflect vm.cursor_t onto the line + readout (visibility, position, values)."""
        t = self.vm.cursor_t
        if t is None:
            self._cursor_line.setVisible(False)
            self._readout.setVisible(False)
            return
        self._suppress_cursor_signal = True
        self._cursor_line.setValue(t)
        self._suppress_cursor_signal = False
        self._cursor_line.setVisible(True)
        self._readout.set_readings(self.vm.cursor_readings())
        self._readout.move(8, 8)  # 既定の初期位置（ドラッグで移動可）
        self._readout.setVisible(True)
        self._readout.raise_()

    def _on_cursor_line_dragged(self) -> None:
        if self._suppress_cursor_signal:
            return
        self.vm.set_cursor(float(self._cursor_line.value()))

    def _place_cursor_at(self, pos: QPointF) -> None:
        t = self._data_value(pos, "x")
        if t is not None:
            self.vm.set_cursor(t)

    # Test introspection
    def cursor_line_visible(self) -> bool:
        return bool(self._cursor_line.isVisible())

    def cursor_line_value(self) -> float:
        return float(self._cursor_line.value())

    def readout_visible(self) -> bool:
        return bool(self._readout.isVisible())
```

VM 通知を購読しているハンドラ `_on_vm_change` に `"cursor"` 分岐を追加（既存メソッドを置換）:

```python
    def _on_vm_change(self, change: str) -> None:
        if change == "cursor":
            self._on_vm_cursor_change()
            return
        self.refresh()
```

プロット内クリックでカーソル設置 — `mousePressEvent`/`mouseReleaseEvent` を拡張（移動なしのクリックのみ設置。既存 X ゾーンドラッグは不変）。`mousePressEvent` 末尾の `super().mousePressEvent(event)` 直前に追記:

```python
        if event.button() == Qt.MouseButton.LeftButton:
            if self._zone_at(event.position()) == ZONE_PLOT:
                # 候補: 移動が閾値未満なら release でカーソル設置
                self._cursor_press_pos = event.position()
```

`__init__` に `self._cursor_press_pos: QPointF | None = None` を追加。`mouseReleaseEvent` の先頭（既存 X ゾーン処理の前）に追記:

```python
        if self._cursor_press_pos is not None:
            moved = (event.position() - self._cursor_press_pos).manhattanLength()
            press_pos = self._cursor_press_pos
            self._cursor_press_pos = None
            if moved < 4 and self._zone_at(event.position()) == ZONE_PLOT:
                self._place_cursor_at(press_pos)
```

補間方式サブメニュー — `build_context_menu` の `return menu` の直前に追記:

```python
        from valisync.core.interpolation import InterpolationMethod

        interp = menu.addMenu("補間方式")
        for label, method in (
            ("線形", InterpolationMethod.LINEAR),
            ("前値保持", InterpolationMethod.ZERO_ORDER_HOLD),
            ("最近傍", InterpolationMethod.NEAREST),
        ):
            interp.addAction(label).triggered.connect(
                lambda *_, m=method: self.vm.set_interp_method(m)
            )
```

凡例撤去 — 次を削除する:
- `_reconcile_axes` 内の `self._legend = pg.LegendItem()`（`graph_panel_view.py:848`）と `self._legend.setParentItem(master_vb)`（`:927`）。
- 同メソッド内の `self._legend.addItem(item, curve.name)`（`:698`）。
- メソッド `legend_labels`（`:989-991`）。

- [ ] **Step 4: 回帰テストを更新**

`tests/gui/test_graph_panel_view.py` で `legend_labels` を参照する箇所を削除/置換する（凡例撤去に伴う期待値変更）。検索:

Run: `uv run pytest tests/gui/test_graph_panel_view.py -v` → `legend_labels` 関連の失敗を確認し、該当テスト関数を「カーソル読み取り面が信号を識別する」前提に合わせて削除または `view.curve_keys()` ベースへ書き換える。

- [ ] **Step 5: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_graph_panel_cursor.py tests/gui/test_graph_panel_view.py -v`
Expected: PASS。回帰: `uv run pytest tests/gui/ -q` 全 PASS。

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_cursor.py tests/gui/test_graph_panel_view.py
git commit -m "feat(gui): GraphPanelView にカーソル線・クリック設置・読み取り面・補間方式メニューを統合、凡例撤去（R15）"
```

---

## Task 5: realgui — 実 OS 入力でのカーソル設置・移動・全パネル同期（Layer C）

**Files:**
- Create: `tests/realgui/test_global_cursor.py`

**Interfaces:**
- Consumes: Task 1–4 の全成果。既存 realgui ハーネス（`tests/realgui/conftest.py` 相当のアプリ起動・実入力ヘルパ、`@pytest.mark.realgui`、`--realgui` オプトイン）。既存 `tests/realgui/test_active_axis_zoom_pan.py` のアプリ起動・実クリック駆動パターンを踏襲する。
- Produces: 実証拠（カーソル設置・補間値表示・線ドラッグ移動・タブ内2パネル同期）。

> **Why Layer C 必須**: クリック判定・`InfiniteLine` の実ドラッグ・クロスパネル実配送は合成 sendEvent では迂回され、ヘッドレスでは「壊れたままグリーン」になりうる（[[feedback_gui_verify_real_input]] / [[gui_drag_drop_not_sendevent_reproducible]]）。

- [ ] **Step 1: realgui テストを書く**

`tests/realgui/test_global_cursor.py` を新規作成（既存 realgui テストのアプリ起動ヘルパ名・fixture に合わせて調整する。下記は実入力ジェスチャと検証の骨子）:

```python
"""Layer C: Global_Cursor を実 OS 入力で検証（R15）。--realgui で実行。

実行: uv run pytest --realgui tests/realgui/test_global_cursor.py -v
スクリーンショットは QT_QPA_PLATFORM=windows（offscreen は文字が□化）。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.realgui


def test_click_places_cursor_and_shows_value(realgui_panel_with_signal):
    """プロット内側を実クリック → カーソル線可視 ＋ 読み取り面に値が出る。"""
    view, vm = realgui_panel_with_signal
    _real_click_in_plot(view, frac_x=0.5, frac_y=0.5)
    assert view.cursor_line_visible()
    assert view.readout_visible()
    assert vm.cursor_readings()[0].in_range is True


def test_drag_cursor_line_moves_time(realgui_panel_with_signal):
    """カーソル線を実ドラッグ → vm.cursor_t が単調に変化。"""
    view, vm = realgui_panel_with_signal
    _real_click_in_plot(view, frac_x=0.3, frac_y=0.5)
    t0 = vm.cursor_t
    _real_drag_cursor_line(view, dx_frac=0.3)  # 小刻みステップで配送（hover 配送要件）
    assert vm.cursor_t is not None and vm.cursor_t > t0


def test_cursor_syncs_across_panels(realgui_area_two_panels):
    """タブ内2パネル: 一方で設置 → 他方にも同時刻のカーソルが出る（R15.1）。"""
    area_view, panels = realgui_area_two_panels
    _real_click_in_panel(area_view, panel_index=0, frac_x=0.5)
    assert panels[1].cursor_t == pytest.approx(panels[0].cursor_t, abs=1e-9)
```

実入力ヘルパ（`_real_click_in_plot` / `_real_drag_cursor_line` / `_real_click_in_panel`）と fixture（`realgui_panel_with_signal` / `realgui_area_two_panels`）は、既存 `tests/realgui/test_active_axis_zoom_pan.py` の実クリック・小刻みドラッグ駆動（SetCursorPos の漸進移動＋配送リトライ、[[gui_realgui_hover_needs_incremental_move]]）を流用して実装する。ドラッグは別 OS スレッド＋watchdog で駆動しハングを避ける（[[gui_realgui_drag_qtimer_hang]]）。

- [ ] **Step 2: realgui で実行して確認**

Run: `uv run pytest --realgui tests/realgui/test_global_cursor.py -v`
Expected: PASS（3 件）。スクリーンショット取得時は `QT_QPA_PLATFORM=windows`。

- [ ] **Step 3: `/gui-verify` 証拠ゲート**

`/gui-verify` を実行し、R15 のカーソル入力経路（クリック設置・線ドラッグ・全パネル同期）が realgui で実証されていること（skipped を「検証済み」と誤認しない）を確認する。

- [ ] **Step 4: コミット**

```bash
git add tests/realgui/test_global_cursor.py tests/realgui/conftest.py
git commit -m "test(realgui): Global_Cursor の実OS入力検証（クリック設置・線ドラッグ・全パネル同期）（R15 Layer C）"
```

---

## Self-Review

**1. Spec coverage（R15 受け入れ基準）:**
- R15.1 クリックで全パネルに同時表示 → Task 4（クリック設置）＋ Task 2（同期）＋ Task 5（実証）✓
- R15.2 各信号の補間値を読み取り面に表示 → Task 1（readings）＋ Task 3（表）＋ Task 4（配線）✓
- R15.3 補間を Session に委譲 → Task 1（`_session.interpolate`）✓
- R15.4 補間方式の切替 → Task 1（`set_interp_method`）＋ Task 4（メニュー）✓ / カーソルのドラッグ同期更新 → Task 4（`sigPositionChanged`）＋ Task 5 ✓
- R15.5 範囲外表示 → Task 1（value=None）＋ Task 3（"範囲外"）✓
- 凡例撤去・フロート表一本化（spec §5/§6）→ Task 3/4 ✓

**2. Placeholder scan:** 各ステップに実テスト/実装コードあり。realgui の実入力ヘルパは既存ハーネス流用を明示（新規発明を避ける）。TBD/TODO なし。

**3. Type consistency:** `CursorReading(name,color,value,in_range)`・`set_cursor(t)`・`cursor_readings()`・`propagate_cursor(tab_index,t)`・`InterpolationMethod.{LINEAR,ZERO_ORDER_HOLD,NEAREST}`・`cursor_line_visible/value`・`readout_visible` を全タスクで一貫使用。

## 後続プラン（本プラン外）
- **Plan B**: R16 Delta_Cursor（加算式2本目）＋ R17 範囲統計（フロート表に Δy・統計列を追加、`compute_statistics` 委譲、統計列の選択 UI）。本プランの `CursorReadout.set_readings` を列拡張する形で接続。
- **Plan C**: R14 時間オフセット（アクティブ波形ドラッグ・プレビュー・適用ダイアログ・`AppViewModel` オフセット dict・全パネル更新）。
