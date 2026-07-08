# gui-plot-analysis-controls 増分1 — アクティブパネル＋載せる入口 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** アクティブパネル概念（タブごと・クリック活性化・枠表示）を導入して Add/Export の `panels[0]` 固定バグを解消し、ChannelBrowser に「アクティブパネルへ追加」ボタンとダブルクリック/Enter 追加を付ける（PC-07🟠・PC-02🔴・PC-04🟠）。

**Architecture:** VM（`GraphAreaVM._Tab.active_panel_index`）が真実、View はクリックで `activate_requested` を emit し枠 overlay を描くだけ。`active_panel` 通知は `_rebuild` を起こさない軽量経路。spec: [2026-07-09-gui-plot-analysis-controls-design.md](../specs/2026-07-09-gui-plot-analysis-controls-design.md) §6。

**Tech Stack:** Python 3.13 / PySide6 / pyqtgraph / pytest-qt。テストは Layer A（純 VM）・Layer B（sendEvent/qtbot 合成）・Layer C（`tests/realgui/` 実 OS 入力）。

## Global Constraints

- ブランチ: `feature/gui-plot-analysis-controls`（main 直コミット禁止）
- 品質ゲート: `uv run pytest`・`uv run ruff check`・`uv run ruff format --check`・`uv run mypy src/` 全通過でコミット（`| tail` 禁止 — exit code が隠れる）
- MVVM: View → VM → Session のみ。View から Session/コア直アクセス禁止
- **overlay 原則**: `plot_widget` は panel 原点 (0,0) を維持。新規 UI はレイアウト行に積まず overlay（`_panel_chrome` パターン。memory `gui_panel_chrome_layout_row_shifts_hittest_origin`）
- 通知タグ `"active_panel"` は `GraphAreaView._rebuild()` を**起こさない**（クリック中の widget 破棄＝クラッシュ源）
- Layer C は `@pytest.mark.realgui`＋`tests/realgui/` 配置＋**実 OS 入力プリミティブ（`_realgui_input.at()`/`key()`）のみ**（合成 `qtbot.mouseClick` 等は契約ガード `tests/gui/test_realgui_layer_c_contract.py` が CI で落とす）
- オブジェクト再生成/同一性の assert は参照保持＋`is`/`is not`（`id()` 比較は禁止 — memory `gui_id_reuse_flake_object_recreation`）

## gui-test-plan 分析サマリ（②実質性・レイヤー判定）

| Task | 変更種別 | A | B | C |
|---|---|---|---|---|
| 1 VM 状態 | VM/純ロジック | 必須 | — | — |
| 2 配送修正 | VM/統合ロジック | 必須 | — | — |
| 3 クリック活性化 | 入力イベント→ハンドラ | 必須 | **必須**（press→signal→VM） | 推奨→Task 7 |
| 4 枠 overlay | ウィジェット構成・状態 | 必須 | 必須（可視/原点不変/非rebuild） | 描画はスクショ→Task 7 |
| 5 Add ボタン | 入力イベント→ハンドラ | 必須 | **必須**（click→emit） | 不要（plain button） |
| 6 dblclick/Enter | 入力イベント→ハンドラ | 必須 | **必須**（warm-up＋二重発火ガード） | **必須**→Task 7（合成 dblclick は不発罠） |
| 7 realgui | — | — | — | ①証拠ゲート対象 |

- **Layer C 専用の実質**: OS→Qt のヒットテスト/配送（パネルクリック→活性化→**別ウィジェットからの Add がそのパネルへ着地**する閉ループ）と、枠/追加曲線の**描画結果**（スクショ判定）。VM 状態の再チェックだけの realgui は naive（禁止）
- **realgui 掴み点監査**: 不要 — ゾーン幾何（frame 幅/grip/軸幅）は不変更。枠 overlay は `WA_TransparentForMouseEvents` でヒットテスト非干渉
- **honest layering note**: `add_to_panel_requested.emit(...)` 直叩きは配線テストであって入力経路テストではない。ボタンは `qtbot.mouseClick`、Enter は `qtbot.keyClick`、dblclick は warm-up click 前置＋sabotage 検証（memory `gui_qtest_dblclick_warmup_click`）

---

### Task 1: GraphAreaVM — タブごとの active_panel_index

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_area_vm.py`
- Test: `tests/gui/test_graph_area_vm.py`（既存パターンの鏡写し・qtbot 不要の純 VM）

**Interfaces:**
- Consumes: 既存 `_Tab`・`Observable._notify`・`add_panel`/`remove_panel`
- Produces: `_Tab.active_panel_index: int = 0`／`set_active_panel(tab_index: int, panel_index: int) -> None`（範囲外は no-op・変化時のみ `_notify("active_panel")`）／`active_panel_index(tab_index: int | None = None) -> int`（None=アクティブタブ）／`active_panel() -> GraphPanelVM`。`add_panel` は新規パネルを自動アクティブ化（`"panels"` 通知のみ・`"active_panel"` は出さない＝rebuild が枠を再適用するため二重通知不要）。`remove_panel` は clamp（アクティブより前を消したら -1・自身なら同 index を `len-1` に clamp）。`inspect()` の各タブに `"active_panel_index"` を追加

- [ ] **Step 1: 失敗するテストを書く** — `tests/gui/test_graph_area_vm.py` に追記（既存 `test_set_active_tab_*` :244-260 の隣・同じ構築ヘルパを使う）

```python
class TestActivePanel:
    def test_initial_active_panel_index_is_zero(self, vm: GraphAreaVM) -> None:
        assert vm.active_panel_index(0) == 0

    def test_set_active_panel_changes_index(self, vm: GraphAreaVM) -> None:
        vm.add_panel(0)
        vm.set_active_panel(0, 0)
        vm.set_active_panel(0, 1)
        assert vm.active_panel_index(0) == 1

    def test_set_active_panel_notifies_active_panel_tag(self, vm: GraphAreaVM) -> None:
        vm.add_panel(0)
        vm.set_active_panel(0, 0)
        changes: list[str] = []
        vm.subscribe(changes.append)
        vm.set_active_panel(0, 1)
        assert changes == ["active_panel"]

    def test_set_active_panel_same_index_does_not_notify(self, vm: GraphAreaVM) -> None:
        changes: list[str] = []
        vm.subscribe(changes.append)
        vm.set_active_panel(0, 0)
        assert changes == []

    def test_set_active_panel_out_of_range_is_noop(self, vm: GraphAreaVM) -> None:
        vm.set_active_panel(0, 5)
        assert vm.active_panel_index(0) == 0

    def test_add_panel_makes_new_panel_active(self, vm: GraphAreaVM) -> None:
        vm.add_panel(0)
        assert vm.active_panel_index(0) == 1

    def test_remove_panel_before_active_shifts_index(self, vm: GraphAreaVM) -> None:
        vm.add_panel(0)
        vm.add_panel(0)  # 3 panels, active=2
        vm.remove_panel(0, 0)
        assert vm.active_panel_index(0) == 1  # 同じパネルを指し続ける

    def test_remove_active_last_panel_clamps(self, vm: GraphAreaVM) -> None:
        vm.add_panel(0)  # 2 panels, active=1
        vm.remove_panel(0, 1)
        assert vm.active_panel_index(0) == 0

    def test_active_panel_is_per_tab(self, vm: GraphAreaVM) -> None:
        vm.add_panel(0)  # tab0 active=1
        vm.add_tab()     # tab1 active=0
        assert vm.active_panel_index(0) == 1
        assert vm.active_panel_index(1) == 0

    def test_active_panel_returns_vm_of_active_tab(self, vm: GraphAreaVM) -> None:
        vm.add_panel(0)
        assert vm.active_panel() is vm.panels(0)[1]

    def test_active_panel_index_defaults_to_active_tab(self, vm: GraphAreaVM) -> None:
        vm.add_tab()
        vm.add_panel(1)
        assert vm.active_panel_index() == 1  # tab1 がアクティブ

    def test_inspect_includes_active_panel_index(self, vm: GraphAreaVM) -> None:
        assert vm.inspect()["tabs"][0]["active_panel_index"] == 0
```

（`vm` fixture が無ければ既存テストの構築式 `GraphAreaVM(app_vm)` をファイル冒頭の既存 fixture/ヘルパに合わせる）

- [ ] **Step 2: RED 確認** — `uv run pytest tests/gui/test_graph_area_vm.py::TestActivePanel -v` → `AttributeError: set_active_panel` 系で全 FAIL
- [ ] **Step 3: 最小実装** — `graph_area_vm.py`

```python
@dataclass
class _Tab:
    """Internal representation of one tab."""

    name: str
    panels: list[GraphPanelVM] = field(default_factory=list)
    x_sync_enabled: bool = True
    active_panel_index: int = 0
```

`add_panel` の `self._notify("panels")` の直前に:

```python
        # PC-07: 作った＝使う。新規パネルを自動アクティブ化（"panels" の rebuild が
        # 枠を再適用するので "active_panel" は重ねて出さない）。
        tab.active_panel_index = len(tab.panels) - 1
```

`remove_panel` の `self._unsubscribe_panel(panel)` の後に（`remove_tab` :146-149 の clamp が手本）:

```python
        if tab.active_panel_index >= len(tab.panels):
            tab.active_panel_index = len(tab.panels) - 1
        elif panel_index < tab.active_panel_index:
            tab.active_panel_index -= 1
```

パネル管理節の末尾に新 API:

```python
    def set_active_panel(self, tab_index: int, panel_index: int) -> None:
        """Make the panel at *panel_index* the active panel of tab *tab_index*.

        Out-of-range indices are ignored (clicks race panel removal). Notifies
        "active_panel" only on change — the View treats it as a repaint-only
        path (never a rebuild).
        """
        tab = self._tabs[tab_index]
        if not (0 <= panel_index < len(tab.panels)):
            return
        if tab.active_panel_index == panel_index:
            return
        tab.active_panel_index = panel_index
        self._notify("active_panel")

    def active_panel_index(self, tab_index: int | None = None) -> int:
        """Return the active panel index of *tab_index* (default: active tab)."""
        if tab_index is None:
            tab_index = self.active_tab_index
        return self._tabs[tab_index].active_panel_index

    def active_panel(self) -> GraphPanelVM:
        """Return the active panel VM of the active tab (Add/Export の配送先)."""
        tab = self.active_tab()
        return tab.panels[tab.active_panel_index]
```

`inspect()` のタブ dict に `"active_panel_index": tab.active_panel_index,` を追加。

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/gui/test_graph_area_vm.py -v` → 全 PASS（既存含む）
- [ ] **Step 5: コミット** — `git add -A && git commit -m "feat(gui): GraphAreaVM にタブごとの active_panel_index（自動アクティブ＋clamp・PC-07 基盤）"`

---

### Task 2: 配送修正 — Add と Export をアクティブパネルへ

**Files:**
- Modify: `src/valisync/gui/views/main_window.py:375-381`（`_add_to_active_panel`）・`:405-406`（`export_csv` 初期選択）
- Test: `tests/gui/test_integration.py`（既存 `TestAddToActivePanel` :110 のクラスに追加・同じ fixture を使う）

**Interfaces:**
- Consumes: Task 1 の `active_panel_index()`/`active_panel()`
- Produces: `_add_to_active_panel` がアクティブパネルへ配送（docstring の嘘を解消）。`export_csv` の初期選択もアクティブパネル

- [ ] **Step 1: 失敗するテストを書く** — `TestAddToActivePanel` に追加

```python
    def test_add_routes_to_active_panel_not_first(self, window) -> None:
        """PC-07: 配送先は panels[0] 固定でなく VM のアクティブパネル。"""
        vm = window.graph_area_vm
        vm.add_panel(0)  # 追加パネルが自動アクティブ (index 1)
        window.channel_browser_view.add_to_panel_requested.emit([_KEY])
        assert _KEY in vm.panels(0)[1].plotted_signal_keys()
        assert _KEY not in vm.panels(0)[0].plotted_signal_keys()

    def test_add_routes_back_to_first_after_reactivation(self, window) -> None:
        vm = window.graph_area_vm
        vm.add_panel(0)
        vm.set_active_panel(0, 0)
        window.channel_browser_view.add_to_panel_requested.emit([_KEY])
        assert _KEY in vm.panels(0)[0].plotted_signal_keys()

    def test_export_initial_selection_uses_active_panel(self, window, monkeypatch) -> None:
        vm = window.graph_area_vm
        vm.add_panel(0)  # active = panel 1
        vm.panels(0)[1].add_signal(_KEY)
        captured: dict[str, set[str]] = {}

        def fake_ask(app_vm, initial, parent):  # noqa: ANN001 — 既存シグネチャ準拠
            captured["initial"] = set(initial)
            return None  # ダイアログキャンセル

        monkeypatch.setattr(
            "valisync.gui.views.main_window.ExportCsvDialog.ask",
            staticmethod(fake_ask),
        )
        window.export_csv()
        assert captured["initial"] == {_KEY}
```

（`_KEY` は既存 `TestAddToActivePanel` が使う信号キー定数/fixture に合わせる。既存テスト `test_add_to_panel_request_plots_on_active_panel` は前提を明示するため冒頭に `window.graph_area_vm.set_active_panel(0, 0)` を追記して維持）

- [ ] **Step 2: RED 確認** — `uv run pytest tests/gui/test_integration.py::TestAddToActivePanel -v` → 新規 3 本 FAIL（panels[0] へ配送される）
- [ ] **Step 3: 最小実装** — `main_window.py`

```python
    def _add_to_active_panel(self, keys: list[str]) -> None:
        """Plot *keys* on the ACTIVE panel of the active tab (PC-07)."""
        vm = self.graph_area_vm
        panels = vm.panels(vm.active_tab_index)
        if not panels:
            return  # 防御的 no-op（VM 不変条件により通常到達不能）
        target = panels[vm.active_panel_index()]
        for key in keys:
            target.add_signal(key)
```

`export_csv` の初期選択行を差し替え:

```python
        panels = self.graph_area_vm.panels(self.graph_area_vm.active_tab_index)
        initial = (
            set(panels[self.graph_area_vm.active_panel_index()].plotted_signal_keys())
            if panels
            else set()
        )
```

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/gui/test_integration.py -v` → 全 PASS
- [ ] **Step 5: コミット** — `git commit -am "fix(gui): Add/Export の配送先を panels[0] 固定からアクティブパネルへ（PC-07）"`

---

### Task 3: クリック活性化 — activate_requested 経路

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（Signal 追加・`mousePressEvent`:1653・`_AlignedAxisItem.mouseClickEvent`:443-448）
- Modify: `src/valisync/gui/views/graph_area_view.py`（`_wire_panel`:188-211）
- Test: `tests/gui/test_active_panel.py`（新規・Layer B）

**Interfaces:**
- Consumes: Task 1 の `set_active_panel`
- Produces: `GraphPanelView.activate_requested = Signal()`（左 press で emit・軸クリックでも emit）。`_wire_panel` が `vm.set_active_panel(tab_index, panel_index)` へ接続

- [ ] **Step 1: 失敗するテストを書く** — `tests/gui/test_active_panel.py`（新規。GraphAreaView の構築は `tests/gui/test_graph_area_view.py` の既存 fixture/ヘルパを踏襲）

```python
"""増分1: クリック活性化（Layer B — 合成入力で press→signal→VM の実経路を検証）."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt


def test_left_press_on_panel_emits_activate_requested(qtbot, panel_view) -> None:
    emitted: list[bool] = []
    panel_view.activate_requested.connect(lambda *_: emitted.append(True))
    qtbot.mousePress(
        panel_view, Qt.MouseButton.LeftButton, pos=QPoint(panel_view.width() // 2, 10)
    )
    qtbot.mouseRelease(
        panel_view, Qt.MouseButton.LeftButton, pos=QPoint(panel_view.width() // 2, 10)
    )
    assert emitted  # 左 press で活性化要求が出る

def test_right_press_does_not_emit_activate(qtbot, panel_view) -> None:
    emitted: list[bool] = []
    panel_view.activate_requested.connect(lambda *_: emitted.append(True))
    qtbot.mousePress(
        panel_view, Qt.MouseButton.RightButton, pos=QPoint(panel_view.width() // 2, 10)
    )
    qtbot.mouseRelease(
        panel_view, Qt.MouseButton.RightButton, pos=QPoint(panel_view.width() // 2, 10)
    )
    assert not emitted  # 右クリックはメニュー専用（活性化しない）

def test_press_on_second_panel_updates_vm(qtbot, area_with_two_panels) -> None:
    area, vm = area_with_two_panels
    vm.set_active_panel(0, 0)
    second = area.tabs.widget(0).widget(1)  # QSplitter の 2 枚目 GraphPanelView
    qtbot.mousePress(second, Qt.MouseButton.LeftButton, pos=QPoint(second.width() // 2, 10))
    qtbot.mouseRelease(second, Qt.MouseButton.LeftButton, pos=QPoint(second.width() // 2, 10))
    assert vm.active_panel_index(0) == 1

def test_axis_click_also_activates_panel(area_with_two_panels) -> None:
    """軸クリック経路（_AlignedAxisItem.mouseClickEvent）もパネルを活性化する。

    scene 内アイテムへの合成クリックは不安定なため、経路の終端
    （set_active_axis を呼ぶハンドラが activate_requested も emit する契約）を
    ハンドラ経由で検証し、実クリックは Task 7 の realgui が閉ループで証明する。
    """
    area, vm = area_with_two_panels
    vm.set_active_panel(0, 0)
    second = area.tabs.widget(0).widget(1)
    emitted: list[bool] = []
    second.activate_requested.connect(lambda *_: emitted.append(True))
    axis_item = second._y_axes[0]
    axis_item._emit_panel_activation()  # クリックハンドラが呼ぶ共通経路
    assert emitted
```

fixture（同ファイル内）:

```python
import pytest

from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_area_view import GraphAreaView
from valisync.gui.views.graph_panel_view import GraphPanelView


@pytest.fixture
def panel_view(qtbot, session):  # session: 既存 conftest の空 Session fixture に合わせる
    view = GraphPanelView(GraphPanelVM(session))
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)
    return view


@pytest.fixture
def area_with_two_panels(qtbot, session):
    vm = GraphAreaVM(_make_app_vm(session))  # 既存テストの AppViewModel 構築に合わせる
    area = GraphAreaView(vm, panel_factory=lambda p: GraphPanelView(p))
    qtbot.addWidget(area)
    vm.add_panel(0)
    area.resize(800, 600)
    area.show()
    qtbot.waitExposed(area)
    return area, vm
```

（`session`／`GraphAreaView` のコンストラクタ引数は既存 `tests/gui/test_graph_area_view.py` の実際の書き方に**必ず**合わせる — 上記はインターフェイスの意図を示す雛形）

- [ ] **Step 2: RED 確認** — `uv run pytest tests/gui/test_active_panel.py -v` → `AttributeError: activate_requested` で FAIL
- [ ] **Step 3: 最小実装**

`graph_panel_view.py` — クラスの Signal 宣言部（`add_panel_requested` の隣）に:

```python
    # PC-07: 左クリックでこのパネルをアクティブに（GraphAreaView が VM へ配線）。
    activate_requested = Signal()
```

`mousePressEvent`(:1653) の左ボタン分岐先頭に 1 行:

```python
        if event.button() == Qt.MouseButton.LeftButton:
            self.activate_requested.emit()  # PC-07: どのゾーンでも押下＝活性化
            zone = self._zone_at(event.position())
```

`_AlignedAxisItem` に共通ヘルパを追加し `mouseClickEvent`(:446-448) から呼ぶ（軸クリックは scene が消費し親の press に届かないため独自 emit が必要）:

```python
    def _emit_panel_activation(self) -> None:
        """Axis clicks are consumed by the scene — re-emit panel activation here."""
        if self._panel_view is not None:
            self._panel_view.activate_requested.emit()
```

```python
        if self._panel_view is not None and self._vm_axis_index is not None:
            self._panel_view.set_active_axis(self._vm_axis_index)
        self._emit_panel_activation()
        ev.accept()
```

`graph_area_view.py` `_wire_panel` に（`offset_apply_requested` 接続の隣）:

```python
        widget.activate_requested.connect(
            lambda *_: self.vm.set_active_panel(tab_index, panel_index)
        )
```

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/gui/test_active_panel.py tests/gui/test_axis_interaction.py -v` → PASS（軸クリック既存テストの無回帰も確認）
- [ ] **Step 5: コミット** — `git commit -am "feat(gui): パネル左クリック/軸クリックで activate_requested → VM.set_active_panel（PC-07）"`

---

### Task 4: アクティブ枠 overlay ＋ 軽量通知経路

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`__init__` の chrome 節 :707-732 の隣・`resizeEvent`:1839）
- Modify: `src/valisync/gui/views/graph_area_view.py`（`_on_vm_change`:141-148・`_rebuild`:150-186）
- Test: `tests/gui/test_active_panel.py`（追記）

**Interfaces:**
- Consumes: Task 1 の `"active_panel"` 通知・`active_panel_index()`
- Produces: `GraphPanelView.set_panel_active(active: bool) -> None`＋`_active_frame`（objectName `"active_panel_frame"`・`WA_TransparentForMouseEvents`）。`GraphAreaView._sync_active_frames()`＋`self._panel_views: list[tuple[int, int, GraphPanelView]]`

- [ ] **Step 1: 失敗するテストを書く** — `tests/gui/test_active_panel.py` に追記

```python
def test_active_frame_follows_vm_state(qtbot, area_with_two_panels) -> None:
    area, vm = area_with_two_panels
    first = area.tabs.widget(0).widget(0)
    second = area.tabs.widget(0).widget(1)
    # add_panel の自動アクティブで panel 1 がアクティブ
    assert second._active_frame.isVisible()
    assert not first._active_frame.isVisible()
    vm.set_active_panel(0, 0)
    assert first._active_frame.isVisible()
    assert not second._active_frame.isVisible()

def test_single_panel_shows_frame(qtbot, session) -> None:
    """DP15: パネル1枚でも枠は出す（一貫性）。"""
    vm = GraphAreaVM(_make_app_vm(session))
    area = GraphAreaView(vm, panel_factory=lambda p: GraphPanelView(p))
    qtbot.addWidget(area)
    area.show()
    qtbot.waitExposed(area)
    only = area.tabs.widget(0).widget(0)
    assert only._active_frame.isVisible()

def test_frame_does_not_shift_plot_origin(qtbot, area_with_two_panels) -> None:
    """honest-RED: 枠はレイアウト行でなく overlay（memory: 27px hit-test 破壊の再発防止）。"""
    area, _vm = area_with_two_panels
    second = area.tabs.widget(0).widget(1)
    assert second._active_frame.isVisible()
    assert second.plot_widget.pos().x() == 0
    assert second.plot_widget.pos().y() == 0

def test_activation_does_not_rebuild_widgets(qtbot, area_with_two_panels) -> None:
    """"active_panel" 通知は軽量経路 — widget を破棄/再生成しない（参照保持で is 比較）。"""
    area, vm = area_with_two_panels
    first_before = area.tabs.widget(0).widget(0)   # 参照を保持（id() は禁止）
    second_before = area.tabs.widget(0).widget(1)
    vm.set_active_panel(0, 0)
    assert area.tabs.widget(0).widget(0) is first_before
    assert area.tabs.widget(0).widget(1) is second_before

def test_frame_reapplied_after_rebuild(qtbot, area_with_two_panels) -> None:
    area, vm = area_with_two_panels
    vm.set_active_panel(0, 0)
    vm.add_panel(0)  # "panels" → _rebuild、新パネル (index 2) が自動アクティブ
    third = area.tabs.widget(0).widget(2)
    assert third._active_frame.isVisible()
    assert not area.tabs.widget(0).widget(0)._active_frame.isVisible()
```

- [ ] **Step 2: RED 確認** — `uv run pytest tests/gui/test_active_panel.py -v` → `AttributeError: _active_frame` で FAIL
- [ ] **Step 3: 最小実装**

`graph_panel_view.py` `__init__` — `self._position_panel_chrome()`(:732) の直後に:

```python
        # PC-07: アクティブパネル枠。chrome と同じく overlay（レイアウト非参加）で
        # plot_widget を原点 (0,0) に保つ。WA_TransparentForMouseEvents で
        # ゾーン hit-test に一切干渉しない。色はアクティブ軸 amber (#f59e0b) と同系。
        self._active_frame = QFrame(self)
        self._active_frame.setObjectName("active_panel_frame")
        self._active_frame.setStyleSheet(
            "#active_panel_frame {"
            " border: 1px solid #f59e0b; border-radius: 2px; background: transparent; }"
        )
        self._active_frame.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._active_frame.setGeometry(self.rect())
        self._active_frame.setVisible(False)
```

（`QFrame` を `PySide6.QtWidgets` の import へ追加）

公開 API（`set_removable`:1853 の隣）:

```python
    def set_panel_active(self, active: bool) -> None:
        """Show/hide the active-panel frame (PC-07). Repaint-only — no relayout."""
        self._active_frame.setVisible(active)
        if active:
            self._active_frame.raise_()
            self._panel_chrome.raise_()  # chrome は枠より上（+/× を隠さない）
```

`resizeEvent`(:1839) に 1 行追加:

```python
        self._active_frame.setGeometry(self.rect())
```

`graph_area_view.py`:

`_rebuild` のループで widget を記録（`self._panel_views: list[tuple[int, int, GraphPanelView]] = []` を `__init__` で初期化し、ループ冒頭でクリア）:

```python
            self._panel_views.clear()
            for tab_index, tab in enumerate(self.vm.tabs()):
                ...
                for panel_index, panel_vm in enumerate(panel_vms):
                    widget = self._panel_factory(panel_vm)
                    if isinstance(widget, GraphPanelView):
                        self._panel_views.append((tab_index, panel_index, widget))
                    ...
```

`_rebuild` の `finally` 後（`self._update_sync_checkbox()` の隣）に `self._sync_active_frames()`。

```python
    def _sync_active_frames(self) -> None:
        """Re-apply the active-panel frame from VM state (rebuild 後と "active_panel")."""
        for tab_index, panel_index, widget in self._panel_views:
            widget.set_panel_active(
                panel_index == self.vm.active_panel_index(tab_index)
            )
```

`_on_vm_change` に軽量分岐を追加:

```python
        if change == "active":
            self._sync_current()
            self._update_sync_checkbox()
        elif change == "active_panel":
            self._sync_active_frames()  # 軽量: rebuild しない（クリック中の破棄禁止）
        elif change == "sync":
            self._update_sync_checkbox()
        else:  # "tabs" | "panels"
            self._rebuild()
```

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/gui/test_active_panel.py -v` → 全 PASS
- [ ] **Step 5: 回帰確認＋コミット** — `uv run pytest tests/gui/ -x -q` → PASS。`git commit -am "feat(gui): アクティブパネル枠 overlay＋active_panel 軽量通知経路（PC-07）"`

---

### Task 5: ChannelBrowser「アクティブパネルへ追加」ボタン

**Files:**
- Modify: `src/valisync/gui/views/channel_browser_view.py`（layout :77-81・wiring :88-90）
- Test: `tests/gui/test_channel_browser_view.py`（追記）

**Interfaces:**
- Consumes: 既存 `add_to_panel_requested`／`selected_signal_keys()`
- Produces: `self.add_button: QPushButton`（objectName `"channel_browser_add"`・選択 0 件で disabled）／`_emit_add_selected() -> None`（Task 6 も共用）

- [ ] **Step 1: 失敗するテストを書く** — `tests/gui/test_channel_browser_view.py` に追記（既存の view/選択ヘルパを再利用。spy は list-append connect が repo 標準）

```python
def test_add_button_disabled_without_selection(view) -> None:
    assert not view.add_button.isEnabled()

def test_add_button_enabled_with_selection(view) -> None:
    _select_first_row(view)
    assert view.add_button.isEnabled()

def test_add_button_disabled_after_clear(view) -> None:
    _select_first_row(view)
    view.tree.selectionModel().clearSelection()
    assert not view.add_button.isEnabled()

def test_add_button_click_emits_selected_keys(qtbot, view) -> None:
    """Layer B: 実クリック（合成）→ clicked → emit の実経路。emit 直叩き禁止。"""
    emitted: list[list[str]] = []
    view.add_to_panel_requested.connect(emitted.append)
    _select_first_row(view)
    qtbot.mouseClick(view.add_button, Qt.MouseButton.LeftButton)
    assert emitted == [view.selected_signal_keys()]
    assert emitted[0]  # 空 emit でない
```

- [ ] **Step 2: RED 確認** — `uv run pytest tests/gui/test_channel_browser_view.py -v -k add_button` → `AttributeError: add_button` で FAIL
- [ ] **Step 3: 最小実装** — `channel_browser_view.py`

import に `QPushButton, QHBoxLayout` を追加。`__init__` の search_box 生成後に:

```python
        # PC-02: 可視の追加ボタン（FileBrowser の Open ボタンパターン踏襲）。
        # 文言は配送先（アクティブパネル）を正直に示す。
        self.add_button = QPushButton("アクティブパネルへ追加", self)
        self.add_button.setObjectName("channel_browser_add")
        self.add_button.setToolTip("選択中の信号をアクティブパネルへ追加")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._emit_add_selected)
```

layout 構築（:77-81）を差し替え:

```python
        controls = QHBoxLayout()
        controls.addWidget(self.search_box, 1)
        controls.addWidget(self.add_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header_label)
        layout.addLayout(controls)
        layout.addWidget(self._stack)
```

`_on_selection_changed`(:123-126) に enable 同期を追加:

```python
    def _on_selection_changed(
        self, _selected: QItemSelection, _deselected: QItemSelection
    ) -> None:
        keys = self.selected_signal_keys()
        self._vm.set_selection(keys)
        self.add_button.setEnabled(bool(keys))
```

コマンド節（:143 付近）に:

```python
    def _emit_add_selected(self) -> None:
        """Emit add_to_panel_requested for the current selection (PC-02/PC-04 共用)."""
        keys = self.selected_signal_keys()
        if keys:
            self.add_to_panel_requested.emit(keys)
```

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/gui/test_channel_browser_view.py tests/gui/test_context_menus.py -v` → PASS
- [ ] **Step 5: コミット** — `git commit -am "feat(gui): ChannelBrowser に「アクティブパネルへ追加」可視ボタン（PC-02）"`

---

### Task 6: ダブルクリック/Enter 追加＋二重発火ガード

**Files:**
- Modify: `src/valisync/gui/views/channel_browser_view.py`
- Test: `tests/gui/test_channel_browser_view.py`（追記）

**Interfaces:**
- Consumes: Task 5 の `_emit_add_selected()`
- Produces: `tree.activated` → 追加（ダブルクリック専用）。tree への eventFilter で Return/Enter を消費して追加（**activated へ到達させない**＝Windows の Enter 二重発火ガード。spec §6）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_enter_emits_add_exactly_once(qtbot, view) -> None:
    """二重発火ガード: Windows では activated も Enter で発火する — 1 回だけ emit。"""
    emitted: list[list[str]] = []
    view.add_to_panel_requested.connect(emitted.append)
    _select_first_row(view)
    view.tree.setFocus()
    qtbot.keyClick(view.tree, Qt.Key.Key_Return)
    assert len(emitted) == 1

def test_enter_without_selection_does_not_emit(qtbot, view) -> None:
    emitted: list[list[str]] = []
    view.add_to_panel_requested.connect(emitted.append)
    view.tree.setFocus()
    qtbot.keyClick(view.tree, Qt.Key.Key_Return)
    assert emitted == []

def test_double_click_emits_add(qtbot, view) -> None:
    """Layer B dblclick: fresh itemview は warm-up click 前置が必須（memory）。"""
    emitted: list[list[str]] = []
    view.add_to_panel_requested.connect(emitted.append)
    index = view.model.index(0, 0)
    rect_center = view.tree.visualRect(index).center()
    # warm-up（sabotage 検証: warm-up 単独では emit されないことを確認してから dblclick）
    qtbot.mouseClick(
        view.tree.viewport(), Qt.MouseButton.LeftButton, pos=rect_center
    )
    assert emitted == []  # warm-up が自力発火しない証明（false-green 防止）
    qtbot.mouseDClick(
        view.tree.viewport(), Qt.MouseButton.LeftButton, pos=rect_center
    )
    assert len(emitted) == 1
    assert emitted[0] == view.selected_signal_keys()
```

- [ ] **Step 2: RED 確認** — `uv run pytest tests/gui/test_channel_browser_view.py -v -k "enter or double_click"` → FAIL（何も配線されていない）
- [ ] **Step 3: 最小実装** — `channel_browser_view.py`

import に `QEvent` を追加（`PySide6.QtCore`）。wiring 節（:88-90）に:

```python
        # PC-04: 最短追加操作。activated はダブルクリック専用（Enter は eventFilter が
        # 消費して単発 emit を保証 — Windows では activated も Enter で発火するため、
        # 両配線だと 1 打鍵で二重追加になる。spec §6 二重発火ガード）。
        self.tree.activated.connect(lambda _index: self._emit_add_selected())
        self.tree.installEventFilter(self)
```

クラスに eventFilter を追加:

```python
    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if (
            watched is self.tree
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._emit_add_selected()
            return True  # 消費: QAbstractItemView の activated 経路へ流さない
        return super().eventFilter(watched, event)
```

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/gui/test_channel_browser_view.py -v` → 全 PASS
- [ ] **Step 5: コミット** — `git commit -am "feat(gui): ChannelBrowser ダブルクリック/Enter で追加＋Enter 二重発火ガード（PC-04）"`

---

### Task 7: Layer C realgui — 閉ループ実証＋共有 double_click ヘルパ

**Files:**
- Modify: `tests/realgui/_realgui_input.py`（`double_click` 昇格）
- Create: `tests/realgui/test_active_panel_flow.py`

**Interfaces:**
- Consumes: `_realgui_input.at/LDOWN/LUP/key/VK_RETURN/to_phys/skip_unless_real_display`・`tests/realgui/conftest.py` の QSettings 隔離（autouse）・`test_diagnostics_dock_realinput.py::_double_click` パターン・`test_tab_ui_flow.py::_make_shown_area`／`_phys_center` の配置/座標作法
- Produces: `_realgui_input.double_click(x: int, y: int) -> None`（GetDoubleClickTime 窓内 2 連打＋各イベント間 pump。3 使用箇所目での共有昇格 — 既存 2 ファイルの module-local 版はそのまま）

**②実質性（このテストでしか証明できないもの）**: OS→Qt ヒットテスト/配送で「パネル 2 の実クリック → 枠がパネル 2 に描画（スクショ） → **別ウィジェット**（ChannelBrowser）からの追加がパネル 2 に着地して曲線が描画（スクショ）」の閉ループ。実ダブルクリック（OS の WM_LBUTTONDBLCLK 変換）と実 Enter キーの配送。自動 assert（VM 状態・`_active_frame.isVisible()`）は backstop、スクショ AI 判定が本体。

- [ ] **Step 1: `double_click` を共有ヘルパへ昇格** — `_realgui_input.py` に追加（`test_diagnostics_dock_realinput.py` の確立実装をそのまま移植）

```python
def double_click_interval_s() -> float:
    """OS のダブルクリック窓の半分（上限 150ms）— 確実に窓内に収める."""
    return min(_user32.GetDoubleClickTime() / 2, 150) / 1000.0


def double_click(x: int, y: int) -> None:
    """実 OS ダブルクリック: 同一物理点へ窓内 2 連打。

    各イベント間で event loop を pump する（間隔ゼロの連打は OS が
    dblclick と認識しない — test_diagnostics_dock_realinput.py で確立）。
    """
    from PySide6.QtWidgets import QApplication

    def _pump(dt: float) -> None:
        QApplication.processEvents()
        time.sleep(dt)

    at(x, y, LDOWN); _pump(0.03)
    at(x, y, LUP); _pump(double_click_interval_s())
    at(x, y, LDOWN); _pump(0.03)
    at(x, y, LUP)
    for _ in range(4):
        _pump(0.02)
```

（`import time`／`_user32` は既存モジュール内の定義に合わせる。既存 2 ファイルの module-local `_double_click` の置換は**しない** — 本増分のスコープ外）

- [ ] **Step 2: realgui テストを書く** — `tests/realgui/test_active_panel_flow.py`（新規）

構築は `tests/realgui/test_panel_source_flow.py` の MainWindow＋データ投入作法を踏襲（QSettings 隔離は conftest の autouse が効く）。ウィンドウは `availableGeometry` 内配置＋`raise_()`＋`activateWindow()`（`test_tab_ui_flow.py::_make_shown_area` 作法）。

```python
@pytest.mark.realgui
def test_click_activates_panel_and_add_routes_there(qtbot, tmp_path) -> None:
    """PC-07/PC-02 閉ループ: 実クリックでパネル2活性化 → 実クリックで Add → パネル2着地."""
    window, key = _make_window_with_two_panels_and_signal(qtbot)  # 構築ヘルパ
    vm = window.graph_area_vm
    vm.set_active_panel(0, 0)  # 前提を固定
    second = _panel_widget(window, 0, 1)

    # 1) パネル2の空白部を実クリック → 活性化＋枠
    px, py = _phys_center(second, QPoint(second.width() // 2, 12))
    at(px, py, LDOWN); _pump(); at(px, py, LUP); _pump_n(4)
    assert vm.active_panel_index(0) == 1  # backstop
    assert second._active_frame.isVisible()
    _shot(tmp_path, "01_panel2_active_frame")  # スクショ判定: 枠がパネル2に見える

    # 2) ChannelBrowser の行を実クリックで選択 → Add ボタンを実クリック
    row_center = _phys_center(
        window.channel_browser_view.tree.viewport(),
        window.channel_browser_view.tree.visualRect(
            window.channel_browser_view.model.index(0, 0)
        ).center(),
    )
    at(*row_center, LDOWN); _pump(); at(*row_center, LUP); _pump_n(2)
    btn_center = _phys_center(
        window.channel_browser_view.add_button,
        window.channel_browser_view.add_button.rect().center(),
    )
    at(*btn_center, LDOWN); _pump(); at(*btn_center, LUP); _pump_n(4)

    # 3) パネル2に着地（パネル1は空のまま）＋曲線が実描画
    assert key in vm.panels(0)[1].plotted_signal_keys()
    assert key not in vm.panels(0)[0].plotted_signal_keys()
    _shot(tmp_path, "02_curve_on_panel2")  # スクショ判定: 曲線がパネル2に見える


@pytest.mark.realgui
def test_dblclick_and_enter_add_once_each(qtbot, tmp_path) -> None:
    """PC-04: 実ダブルクリックで1回追加・実 Enter で1回追加（二重発火なしの実証明）."""
    window, key = _make_window_with_two_panels_and_signal(qtbot)
    vm = window.graph_area_vm
    target = vm.active_panel()
    tree = window.channel_browser_view.tree
    row_center = _phys_center(
        tree.viewport(),
        tree.visualRect(window.channel_browser_view.model.index(0, 0)).center(),
    )
    double_click(*row_center)
    _pump_n(4)
    assert target.plotted_signal_keys().count(key) == 1  # 1回だけ

    # Enter（実キーは前面ウィンドウへ届く — 直前の実クリックでフォーカス済み）
    key_input(VK_RETURN)
    _pump_n(4)
    assert target.plotted_signal_keys().count(key) == 2  # +1（二重発火なら +2）
    _shot(tmp_path, "03_dblclick_enter_add")
```

（`key_input` は `_realgui_input.key` の別名 import。`_pump`/`_pump_n`/`_shot`/`_phys_center`/構築ヘルパは既存 realgui の確立パターンをファイル内に定義。**注意**: `plotted_signal_keys()` が dedup を返す場合は 2 回目の追加 assert を「エントリ数」で数える — 実装を確認して合わせる）

- [ ] **Step 3: 契約ガード確認** — `uv run pytest tests/gui/test_realgui_layer_c_contract.py -v` → PASS（実入力プリミティブのみ使用）
- [ ] **Step 4: realgui 実行（RED→GREEN）** — `uv run pytest --realgui tests/realgui/test_active_panel_flow.py -v` → 2 PASS＋スクショ 3 枚を目視/AI 判定（枠位置・曲線着地）
- [ ] **Step 5: コミット** — `git commit -am "test(realgui): アクティブパネル閉ループ＋実ダブルクリック/Enter 追加（増分1 Layer C）"`

---

### Task 8: 品質ゲート＋①証拠ゲート

- [ ] **Step 1: フルゲート** — `uv run pytest`（0 errors）／`uv run ruff check`／`uv run ruff format --check`／`uv run mypy src/` 全通過
- [ ] **Step 2: ①証拠ゲート（/gui-verify）** — `uv run pytest --realgui tests/realgui/test_active_panel_flow.py` の pass ログ＋スクショを PR に添付。既存 realgui の無回帰スイート（軸操作系）も scoped 実行:
  - `- [ ] uv run pytest --realgui tests/realgui/test_click_activate_axis.py`（軸クリック経路に `_emit_panel_activation` を足したため）
  - `- [ ] uv run pytest --realgui tests/realgui/test_active_panel_flow.py + 証拠添付`
- [ ] **Step 3: 挙動変更の stale realgui grep** — `grep -rn "active" tests/realgui/` で活性化前提の既存 assert を確認（memory `gui_behavior_change_stale_parallel_realgui_test`）。mousePressEvent に emit を足しただけなので既存ジェスチャは不変のはずだが、X ズーム/パン realgui が pass することを Step 2 の軸スイートで確認
- [ ] **Step 4: コミット＋push** — `git push -u origin feature/gui-plot-analysis-controls`（PR 作成は増分1完了時にユーザーと確認）

## スコープ外（後続増分）

- 曲線/軸の右クリックメニュー・H キー・entry_id（増分2）
- カーソル・readout（増分3）／グリッド・ツールチップ・ソート（増分4）
- Export ダイアログタイトルへのアクティブパネル表示（spec §10 外・不採用）
