# FU-06 + FU-13 信号プレビューウィンドウ 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChannelBrowser の信号ダブルクリックで2タブ（プレビュー波形／信号プロパティ）の非モーダル単一インスタンスウィンドウを開き、追加導線をボタン/ダブルクリック/Enter 廃止＝右クリックメニュー＋D&D のみに整理する。

**Architecture:** `SignalPreviewVM`（gui/viewmodels・session からプロパティ＋ダウンサンプル波形を供給）＋ `SignalPreviewWindow`（gui/views・`QTabWidget` 2タブ・read-only pyqtgraph プロット）。`ChannelBrowserView` は `doubleClicked`→`preview_requested(key)` へ配線変更＋ボタン/Enter-add 撤去。`MainWindow` が preview window を単一インスタンス所有し配線。設計 [spec](../specs/2026-07-14-fu06-fu13-signal-preview-window-design.md)。

**Tech Stack:** PySide6/pyqtgraph, MVVM, pytest-qt。

## Global Constraints

- core（Signal/Downsampler/session の非 Qt 部）は Qt 非依存維持。`SignalPreviewVM` は gui/viewmodels、`SignalPreviewWindow` は gui/views。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過（unscoped・repo ルートで実行し出力そのまま報告）。
- Python コメント/文字列に全角約物 `()：+=` 禁止（RUF001/002/003）。ASCII を使う（`->`/`→`/`・` は可・時間範囲区切りは ASCII `-`）。
- 入力経路（ダブルクリック）変更ゆえ merge 前に gui-verify ①realgui（Task 5）。
- 追加は右クリック "Add to Active Panel" ＋ D&D のみ（Enter は何もしない）。

---

### Task 1: SignalPreviewVM（プロパティ＋波形データ供給）

**Files:**
- Create: `src/valisync/gui/viewmodels/signal_preview_vm.py`
- Test: `tests/gui/test_signal_preview_vm.py`

**Interfaces:**
- Consumes: `AppViewModel`（`active_file_key` / `session.group_signals(key)`）・`Signal.time_range()`/`finite_view()`・`core.downsampler.Downsampler`。
- Produces: `SignalPreviewVM(app_vm)`・`set_signal(key: str | None)`・`properties() -> list[tuple[str, str]]`・`plot_data() -> tuple[np.ndarray, np.ndarray] | None`。単一コンシューマ（window）が set_signal 後に明示再描画するため Observable/notify は持たない（YAGNI・spec の `_notify` 記述は本簡略化で代替）。

- [ ] **Step 1: 失敗テスト**

`tests/gui/test_signal_preview_vm.py`:

```python
"""Tests for SignalPreviewVM (FU-13): preview properties + downsampled waveform."""

from __future__ import annotations

import numpy as np
from pytestqt.qtbot import QtBot

from valisync.core.models import Signal
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM


def _sig(name: str, ts: np.ndarray, vs: np.ndarray) -> Signal:
    return Signal(
        name=name,
        timestamps=ts,
        values=vs,
        file_format="MDF4",
        bus_type="CAN",
        source_file="",
        metadata={"unit": "km/h", "comment": "veh speed"},
    )


def _vm(qtbot: QtBot) -> SignalPreviewVM:
    app_vm = AppViewModel()
    ts = np.arange(0.0, 100.0, 1.0)
    vs = np.sin(ts)
    app_vm.session.group_signals = lambda k: [_sig("g::Speed", ts, vs)]
    app_vm.set_active_file("g")
    return SignalPreviewVM(app_vm)


def test_properties_include_name_unit_samples_timerange_minmax(qtbot: QtBot) -> None:
    vm = _vm(qtbot)
    vm.set_signal("g::Speed")
    props = dict(vm.properties())
    assert props["名前"] == "g::Speed"
    assert props["単位"] == "km/h"
    assert props["サンプル数"] == "100"
    assert "時間範囲" in props and "s" in props["時間範囲"]
    assert "最小値" in props and "最大値" in props
    assert props["コメント"] == "veh speed"


def test_properties_empty_for_unknown_or_none(qtbot: QtBot) -> None:
    vm = _vm(qtbot)
    assert vm.properties() == []  # no signal set
    vm.set_signal("g::Missing")
    assert vm.properties() == []


def test_plot_data_downsampled_within_range(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    ts = np.arange(0.0, 10000.0, 1.0)  # 10k points
    vs = np.cos(ts)
    app_vm.session.group_signals = lambda k: [_sig("g::Big", ts, vs)]
    app_vm.set_active_file("g")
    vm = SignalPreviewVM(app_vm)
    vm.set_signal("g::Big")
    data = vm.plot_data()
    assert data is not None
    x, y = data
    assert 0 < len(x) <= 480  # downsampled to <= _PREVIEW_POINTS
    assert len(x) == len(y)
    assert x[0] >= 0.0 and x[-1] <= 9999.0  # within original range


def test_plot_data_none_for_unknown(qtbot: QtBot) -> None:
    vm = _vm(qtbot)
    vm.set_signal("g::Missing")
    assert vm.plot_data() is None


def test_time_range_does_not_materialize_sorted_view_cache(qtbot: QtBot) -> None:
    """properties() must read time range via Signal.time_range() (raw min/max),
    NOT sorted_view()[0][0]/[-1] which would inflate the FU-20 float64 cache
    (memory signal_range_via_sorted_view_materializes_float64_cache)."""
    app_vm = AppViewModel()
    ts = np.arange(0.0, 50.0, 1.0)
    sig = _sig("g::S", ts, np.sin(ts))
    app_vm.session.group_signals = lambda k: [sig]
    app_vm.set_active_file("g")
    vm = SignalPreviewVM(app_vm)
    vm.set_signal("g::S")
    # Reading properties (time range) must not populate the sorted-view cache.
    _ = vm.properties()
    assert sig._sorted_view_cache is None
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_signal_preview_vm.py -v`
Expected: FAIL（`signal_preview_vm` モジュール無し）。

- [ ] **Step 3: 実装**

`src/valisync/gui/viewmodels/signal_preview_vm.py`:

```python
"""SignalPreviewVM (FU-13): supplies preview properties and a downsampled
waveform for a single signal shown in the SignalPreviewWindow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from valisync.core.downsampler.downsampler import Downsampler

if TYPE_CHECKING:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

_PREVIEW_POINTS = 480  # target sample count for the read-only preview plot


class SignalPreviewVM:
    """Resolves the active file's signal by key and provides preview data.

    No Observable/notify: the window is the sole consumer and re-renders
    explicitly after set_signal (YAGNI)."""

    def __init__(self, app_vm: AppViewModel) -> None:
        self._app_vm = app_vm
        self._signal_key: str | None = None

    def set_signal(self, key: str | None) -> None:
        self._signal_key = key

    def _signal(self) -> Any | None:
        key = self._signal_key
        active_key = self._app_vm.active_file_key
        if not key or not active_key:
            return None
        try:
            for sig in self._app_vm.session.group_signals(active_key):
                if sig.name == key:
                    return sig
        except KeyError:
            return None
        return None

    def properties(self) -> list[tuple[str, str]]:
        sig = self._signal()
        if sig is None:
            return []
        md = sig.metadata or {}
        rows: list[tuple[str, str]] = [("名前", str(sig.name))]
        unit = str(md.get("unit", ""))
        if unit:
            rows.append(("単位", unit))
        rows.append(("サンプル数", str(len(sig.timestamps))))
        tr = sig.time_range()  # raw min/max -- must NOT use sorted_view (FU-20)
        if tr is not None:
            rows.append(("時間範囲", f"{tr[0]:.4g} - {tr[1]:.4g} s"))
        fts, fvs = sig.finite_view()
        if len(fvs) > 0:
            rows.append(("最小値", f"{float(fvs.min()):.6g}"))
            rows.append(("最大値", f"{float(fvs.max()):.6g}"))
        origin = " / ".join(
            b
            for b in (
                sig.bus_type,
                md.get("channel_group_name", ""),
                md.get("source_name", ""),
            )
            if b
        )
        if origin:
            rows.append(("由来", origin))
        comment = str(md.get("comment", ""))
        if comment:
            rows.append(("コメント", comment))
        labels = md.get("value_labels")
        if labels:
            rows.append(
                ("ラベル", ", ".join(f"{k}={v}" for k, v in labels.items()))
            )
        return rows

    def plot_data(self) -> tuple[np.ndarray, np.ndarray] | None:
        sig = self._signal()
        if sig is None or len(sig.timestamps) == 0:
            return None
        ds = Downsampler().downsample(sig, _PREVIEW_POINTS)
        ts, vs = ds.sorted_view()
        return ts, vs
```

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_signal_preview_vm.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 品質ゲート＋コミット**

Run: `uv run pytest`; `uv run ruff check`; `uv run ruff format --check`; `uv run mypy src/`

```bash
git add src/valisync/gui/viewmodels/signal_preview_vm.py tests/gui/test_signal_preview_vm.py
git commit -m "feat(fu13): SignalPreviewVM(プロパティ＋ダウンサンプル波形供給)"
```

---

### Task 2: SignalPreviewWindow（2タブウィンドウ）

**Files:**
- Create: `src/valisync/gui/views/signal_preview_window.py`
- Test: `tests/gui/test_signal_preview_window.py`

**Interfaces:**
- Consumes: Task 1 の `SignalPreviewVM`。
- Produces: `SignalPreviewWindow(vm: SignalPreviewVM)`・`show_signal(key: str) -> None`（set_signal→両タブ再描画→show/raise/activate）。属性 `tabs: QTabWidget`・`preview_plot`（pg.PlotWidget）・タブタイトル「プレビュー」「信号プロパティ」。

- [ ] **Step 1: 失敗テスト**

`tests/gui/test_signal_preview_window.py`:

```python
"""Tests for SignalPreviewWindow (FU-13): 2-tab preview + properties window."""

from __future__ import annotations

import numpy as np
from pytestqt.qtbot import QtBot

from valisync.core.models import Signal
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM
from valisync.gui.views.signal_preview_window import SignalPreviewWindow


def _sig(name: str) -> Signal:
    ts = np.arange(0.0, 200.0, 1.0)
    return Signal(
        name=name,
        timestamps=ts,
        values=np.sin(ts),
        file_format="MDF4",
        bus_type="CAN",
        source_file="",
        metadata={"unit": "V"},
    )


def _window(qtbot: QtBot) -> SignalPreviewWindow:
    app_vm = AppViewModel()
    app_vm.session.group_signals = lambda k: [_sig("g::A"), _sig("g::B")]
    app_vm.set_active_file("g")
    win = SignalPreviewWindow(SignalPreviewVM(app_vm))
    qtbot.addWidget(win)
    return win


def test_two_tabs_present_with_titles(qtbot: QtBot) -> None:
    win = _window(qtbot)
    titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert titles == ["プレビュー", "信号プロパティ"]


def test_show_signal_populates_plot_and_properties(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_signal("g::A")
    # Preview tab: a curve is drawn.
    assert len(win.preview_plot.listDataItems()) == 1
    # Properties tab: rows populated (name row present).
    assert win.property_row_count() >= 1


def test_show_signal_replaces_content_single_instance(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_signal("g::A")
    win.show_signal("g::B")  # same window, content swapped
    assert len(win.preview_plot.listDataItems()) == 1  # not accumulated
    assert win.windowTitle().endswith("g::B") or "g::B" in win.windowTitle()


def test_show_signal_unknown_shows_no_curve(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_signal("g::Missing")
    assert len(win.preview_plot.listDataItems()) == 0
    assert win.property_row_count() == 0
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_signal_preview_window.py -v`
Expected: FAIL（`signal_preview_window` モジュール無し）。

- [ ] **Step 3: 実装**

`src/valisync/gui/views/signal_preview_window.py`:

```python
"""SignalPreviewWindow (FU-13): non-modal, single-instance window with a
Preview (read-only waveform) tab and a Signal Properties tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM

_PREVIEW_PEN = pg.mkPen("#4FC3F7", width=1)


class SignalPreviewWindow(QWidget):
    def __init__(self, vm: SignalPreviewVM) -> None:
        super().__init__(None)
        self._vm = vm
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle("信号プレビュー")
        self.resize(560, 400)

        self.tabs = QTabWidget(self)

        # --- Preview tab: plot OR "cannot preview" label (QStackedWidget) --------
        self.preview_plot = pg.PlotWidget()
        self.preview_plot.setMouseEnabled(False, False)
        self.preview_plot.setMenuEnabled(False)
        self.preview_plot.hideButtons()
        self._no_preview = QLabel("プレビューできません")
        self._no_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_stack = QStackedWidget()
        self._preview_stack.addWidget(self.preview_plot)  # index 0
        self._preview_stack.addWidget(self._no_preview)  # index 1
        self.tabs.addTab(self._preview_stack, "プレビュー")

        # --- Properties tab ------------------------------------------------------
        self._props_host = QWidget()
        self._props_form = QFormLayout(self._props_host)
        self.tabs.addTab(self._props_host, "信号プロパティ")

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)

    def property_row_count(self) -> int:
        return self._props_form.rowCount()

    def show_signal(self, key: str) -> None:
        self._vm.set_signal(key)
        self._render()
        self.setWindowTitle(f"信号プレビュー - {key}")
        self.show()
        self.raise_()
        self.activateWindow()

    def _render(self) -> None:
        # Preview tab.
        self.preview_plot.clear()
        data = self._vm.plot_data()
        if data is not None:
            x, y = data
            self.preview_plot.plot(x, y, pen=_PREVIEW_PEN)
            self._preview_stack.setCurrentIndex(0)
        else:
            self._preview_stack.setCurrentIndex(1)
        # Properties tab: rebuild the form.
        while self._props_form.rowCount() > 0:
            self._props_form.removeRow(0)
        for label, value in self._vm.properties():
            self._props_form.addRow(QLabel(label), QLabel(value))
```

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_signal_preview_window.py -v`
Expected: 全 PASS。

- [ ] **Step 5: 品質ゲート＋コミット**

Run 全ゲート。

```bash
git add src/valisync/gui/views/signal_preview_window.py tests/gui/test_signal_preview_window.py
git commit -m "feat(fu13): SignalPreviewWindow(プレビュー波形/信号プロパティ 2タブ)"
```

---

### Task 3: ChannelBrowserView 追加導線の整理（doubleClick→preview・ボタン/Enter-add 撤去）

**Files:**
- Modify: `src/valisync/gui/views/channel_browser_view.py`
- Test: `tests/gui/test_channel_browser_view.py`

**Interfaces:**
- Produces: 新シグナル `preview_requested = Signal(str)`（ダブルクリックした leaf の signal_key で emit）。`add_button` 削除。Enter-add の eventFilter 撤去。`add_to_panel_requested`（右クリック "Add to Active Panel" ＋ D&D）は不変。
- Consumes: Task 4（MainWindow）が `preview_requested` を購読。

- [ ] **Step 1: 失敗テスト（挙動変更＋無回帰）**

`tests/gui/test_channel_browser_view.py` に追加/更新。既存の「ダブルクリック→add」「Enter→add」「add_button」系テストは新挙動へ更新（下記）。

```python
def test_double_click_emits_preview_not_add(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-13: double-click emits preview_requested with the leaf key, NOT add."""
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    parent = view.model.index(0, 0, QModelIndex())  # array parent
    child = view.model.index(0, 0, parent)  # a leaf
    view.tree.selectionModel().select(
        child,
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    with qtbot.waitSignal(view.preview_requested, timeout=1000) as prev:
        view.tree.doubleClicked.emit(child)
    assert prev.args[0].endswith("[0]")


def test_no_add_button(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-06: the 'add to active panel' button is removed."""
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    assert not hasattr(view, "add_button")


def test_enter_does_not_emit_add(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-06/Enter removal: pressing Enter on the tree emits neither add nor preview."""
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent

    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    parent = view.model.index(0, 0, QModelIndex())
    child = view.model.index(0, 0, parent)
    view.tree.selectionModel().select(
        child,
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    fired: list[str] = []
    view.add_to_panel_requested.connect(lambda _k: fired.append("add"))
    view.preview_requested.connect(lambda _k: fired.append("preview"))
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    view.tree.keyPressEvent(ev)
    assert fired == []  # Enter does nothing


def test_context_menu_add_still_emits(qtbot: QtBot, tmp_path: Path) -> None:
    """Regression: right-click 'Add to Active Panel' still emits add_to_panel_requested."""
    _app_vm, view, _key = _make_view_with_arrays(qtbot, tmp_path)
    parent = view.model.index(0, 0, QModelIndex())
    child = view.model.index(0, 0, parent)
    view.tree.selectionModel().select(
        child,
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )
    menu = view.build_context_menu()
    add_action = next(a for a in menu.actions() if a.text() == "Add to Active Panel")
    with qtbot.waitSignal(view.add_to_panel_requested, timeout=1000):
        add_action.trigger()
```

既存テストの更新: `test_double_click_emits_add`（もしあれば）→ 上記 preview 版へ置換。Enter→add 系・add_button 系テストは削除/更新。**実装者は `test_channel_browser_view.py` 内の `add_button`/`activated`/Enter-add に依存する既存テストを grep し、新挙動へ更新すること**（`grep -nE "add_button|activated|Key_Return|Key_Enter|_emit_add" tests/gui/test_channel_browser_view.py`）。

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_channel_browser_view.py -k "preview or add_button or enter_does_not or context_menu_add" -v`
Expected: 新規は FAIL（preview_requested 無し・add_button まだ在る等）。

- [ ] **Step 3: 実装**

`channel_browser_view.py`:

1. クラスのシグナル定義に追加（`add_to_panel_requested = Signal(list)` の近く）:
```python
    preview_requested = Signal(str)  # FU-13: double-click a leaf -> open preview
```

2. `add_button` の生成（`self.add_button = QPushButton(...)` 一式）と `controls.addWidget(self.add_button)`、`_refresh` 内の `self.add_button.setEnabled(...)` を**削除**。

3. `self.tree.activated.connect(lambda _index: self._emit_add_selected())` を**削除**し、代わりに:
```python
        # FU-13: double-click (not Enter) opens the preview window. doubleClicked
        # fires only on double-click, so Enter never triggers it.
        self.tree.doubleClicked.connect(self._emit_preview)
```

4. Enter 用 `eventFilter`（Return/Enter を消費して add する分岐）を**削除**。`eventFilter` が他用途を持たなければメソッドごと削除し、`self.tree.installEventFilter(self)` も削除。

5. `_emit_preview` を追加（`_emit_add_selected` の近く。`_emit_add_selected` は右クリックメニューが使うため残す）:
```python
    def _emit_preview(self, index: _Index) -> None:
        """Emit preview_requested for a leaf; parents (key is None) are ignored."""
        key = self.model.signal_key_at(index)
        if key is not None:
            self.preview_requested.emit(key)
```
（`_Index` 型が本ファイルに無ければ `QModelIndex` を引数型に使う。`signal_key_at` は SignalTreeModel の既存メソッド。）

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_channel_browser_view.py -v`
Expected: 新規＋更新含め全 PASS（D&D/選択/フィルタ/ソート等の無回帰含む）。

- [ ] **Step 5: 品質ゲート＋コミット**

```bash
git add src/valisync/gui/views/channel_browser_view.py tests/gui/test_channel_browser_view.py
git commit -m "feat(fu06/fu13): ダブルクリックをプレビューへ・追加ボタン/Enter-add 撤去(追加は menu/D&D)"
```

---

### Task 4: MainWindow 配線（preview window 単一インスタンス所有）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`
- Test: `tests/gui/test_main_window.py`

**Interfaces:**
- Consumes: Task 1-3（`SignalPreviewVM`/`SignalPreviewWindow`/`ChannelBrowserView.preview_requested`）。
- Produces: `self.signal_preview_window`（単一インスタンス）・`preview_requested`→`show_signal` 配線。

- [ ] **Step 1: 失敗テスト**

`tests/gui/test_main_window.py`:

```python
def test_channel_browser_double_click_opens_preview(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-13 wiring: ChannelBrowser preview_requested opens the single preview window."""
    from valisync.gui.views.signal_preview_window import SignalPreviewWindow

    window = _make_window(qtbot)
    assert isinstance(window.signal_preview_window, SignalPreviewWindow)  # type: ignore[union-attr]
    # Emitting preview_requested drives show_signal (window becomes visible).
    window.channel_browser_view.preview_requested.emit("nonexistent::key")  # type: ignore[union-attr]
    assert window.signal_preview_window.isVisible()  # type: ignore[union-attr]
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_main_window.py::test_channel_browser_double_click_opens_preview -v`
Expected: FAIL（`signal_preview_window` 属性無し）。

- [ ] **Step 3: 実装**

`main_window.py` の `__init__`（ChannelBrowser 構築後・dock 設定周辺）に追加:

```python
        from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM
        from valisync.gui.views.signal_preview_window import SignalPreviewWindow

        # FU-13: single-instance, non-modal preview window opened by double-click.
        self.signal_preview_window = SignalPreviewWindow(
            SignalPreviewVM(self.app_vm)
        )
        self.channel_browser_view.preview_requested.connect(
            self.signal_preview_window.show_signal
        )
```

（import はファイル冒頭にまとめても良い。`self.app_vm` は既存の AppViewModel 参照。）

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_main_window.py -v`
Expected: 全 PASS（無回帰含む）。

- [ ] **Step 5: 品質ゲート＋コミット**

```bash
git add src/valisync/gui/views/main_window.py tests/gui/test_main_window.py
git commit -m "feat(fu13): MainWindow が信号プレビューウィンドウを所有し doubleClick を配線"
```

---

### Task 5: gui-verify ①ゲート（realgui＋real-display スクショ）＝メインセッション駆動

**Files:**
- Modify（必要時）: `tests/realgui/test_channel_browser_realclick.py`（実ダブルクリック→プレビュー）。
- Scratch（非コミット）: real-display スクショ確認。

- [ ] **Step 1: realgui（入力経路変更＝ダブルクリック）**

実 OS 入力で「ChannelBrowser の信号を実ダブルクリック→プレビューウィンドウが開き、プレビュータブに波形が描画される」を検証（スクショ）。既存の右クリック "Add to Active Panel"／D&D 追加 realgui が無回帰であることも確認。`GetDoubleClickTime` 窓内2連打（memory [[gui_qtest_dblclick_warmup_click]]）。

- [ ] **Step 2: journey smoke（無条件）**

Run: `QT_QPA_PLATFORM=windows uv run pytest --realgui tests/realgui/test_journey_smoke.py -v`

- [ ] **Step 3: 証拠集約＋ゲート判定**

headless full（0 errors）・realgui pass/スクショ・contract 照合（ダブルクリック=入力経路 realgui／プレビュー描画=real display スクショ／追加無回帰）を集約。

---

## Self-Review

- **Spec coverage**: FU-13 プレビューウィンドウ（Task 1 VM＋Task 2 window＋Task 4 配線）・FU-06＋Enter 廃止＋ダブルクリック転用（Task 3）・gui-verify（Task 5）＝spec 全項目。
- **Placeholder scan**: 全 step に実コード/実コマンド。
- **Type consistency**: `SignalPreviewVM(app_vm)`/`set_signal(key)`/`properties()->list[tuple[str,str]]`/`plot_data()->tuple|None`（Task 1）＝`SignalPreviewWindow(vm)`/`show_signal(key)`（Task 2）＝`ChannelBrowserView.preview_requested: Signal(str)`（Task 3）＝`MainWindow.signal_preview_window`＋`preview_requested`→`show_signal` 配線（Task 4）で一貫。`_PREVIEW_POINTS=480` は VM 側（plot_data のダウンサンプル target）。
- **YAGNI**: プレビュー静的（操作なし）・単一インスタンス・Observable 無し（単一コンシューマ明示再描画）。
