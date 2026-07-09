# 増分4: 仕上げ（グリッド PC-15 / チャンネルツールチップ PC-19 / 列ソート PC-20）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** gui-plot-analysis-controls の最終増分。プロットの X 方向グリッド表示・チャンネル一覧の遅延リッチツールチップ・信号列のヘッダソートを追加する。

**Architecture:** グリッドはパネルごとの transient VM 状態（`GraphPanelVM.grid_enabled`）を View が pyqtgraph の `_x_axis.setGrid()` へ反映（X 方向の縦線のみ）。ツールチップは `ChannelBrowserVM.tooltip_for(key)` で**ホバー時のみ遅延組立**し `SignalTableModel` の ToolTipRole から呼ぶ（FileListModel の遅延 tooltip 先例に倣う）。列ソートは `QSortFilterProxyModel` を挟んで `setSortingEnabled(True)`（ソート専用・フィルタは現行どおり VM 真実）、選択と D&D の index を `mapToSource` 経由に修正。

**Tech Stack:** Python 3.13 / PySide6（Qt6）/ pyqtgraph / MVVM（View → ViewModel → Session）。

## Global Constraints

- **MVVM 境界**: View → VM のみ。グリッド開閉→`vm.toggle_grid(on)`、ツールチップ→`vm.tooltip_for(key)`。View は core を直接触らない。
- **グリッドは X 方向のみ**（PC-15・DP13）: 縦グリッド線のみ（Y 方向は出さない）。状態は `GraphPanelVM.grid_enabled`（**パネルごと・transient**・永続化しない）。描画は既存の共有 `_x_axis`（`pg.AxisItem` bottom・master ViewBox に link 済み）の `setGrid(alpha)` で行う（overlay の値写像は不変更）。
- **ツールチップ内容**（PC-19・DP14）: 単位 / サンプル数（**生記録数** `len(sig.timestamps)`）/ 由来（`bus_type`・`metadata['channel_group_name']`・`metadata['source_name']` を存在するものだけ）/ コメント（`metadata['comment']`）/ value_labels（LD-07 退行なし・既存 `_labels_tooltip` を一節として内包）。**CSV/Derived の欠損行は省略**（unit と サンプル数以外は空になり得る）。**時間範囲は含めない**。遅延（ホバー時のみ算出）。
- **列ソートはソート専用**（PC-20・DP2）: `QSortFilterProxyModel` はソートのためだけに挟む。**フィルタは現行どおり VM 真実**（proxy にフィルタは設定しない＝accept-all のまま）。ヘッダクリックで Name/Unit ソート。`selected_signal_keys` と D&D のドラッグ元 index は `mapToSource` 経由へ修正（proxy 挿入でビュー index が源 index と一致しなくなるため）。
- **品質ゲート（コミット前に全通過必須）**: `uv run pytest`（exit 0・0 errors）／`uv run ruff check`／`uv run ruff format --check`／`uv run mypy src/`。
- **ruff 注意**: Python の文字列/コメント/docstring 内の全角記号（（）／＋・「」）は RUF001/002/003 を誘発 → ASCII 等価へ。ただし**ユーザー向け日本語ラベル/ツールチップ文字列**（「グリッド」「単位:」「由来:」等）は全角のまま維持。`§` は許容。
- **realgui は実 OS 入力のみ**（`_realgui_input.at()`/`key()`）。合成入力は Layer C 契約ガード `tests/gui/test_realgui_layer_c_contract.py` が CI で落とす。スクショは `QT_QPA_PLATFORM=windows`。**グリッドの描画ピクセルの正しさは realgui のみ誠実**（memory `gui_offscreen_grab_text_tofu`）。**proxy 挿入で D&D のドラッグ元 index 経路が変わるため、既存 ChannelBrowser 発 realgui D&D を①ゲートで再実行し無回帰を証拠化**（D&D は合成再現不可・memory `gui_drag_drop_not_sendevent_reproducible`）。

## File Structure

- `src/valisync/gui/viewmodels/graph_panel_vm.py`: `grid_enabled` 状態＋`toggle_grid`（notify "grid"）。
- `src/valisync/gui/views/graph_panel_view.py`: `build_context_menu` に「グリッド」checkable／`_apply_grid()`（`_x_axis.setGrid`）／`_on_vm_change` の "grid" 分岐／軸再構築後にも `_apply_grid()`。
- `src/valisync/gui/viewmodels/channel_browser_vm.py`: `tooltip_for(key)` 遅延組立＋`_signal_by_key`。`SignalItem.tooltip` 廃止（value_labels は tooltip_for へ内包）。
- `src/valisync/gui/adapters/qt_signal_models.py`: `SignalTableModel` の ToolTipRole を `vm.tooltip_for(item.key)` へ。
- `src/valisync/gui/views/channel_browser_view.py`: `QSortFilterProxyModel` 挿入＋`setSortingEnabled(True)`＋`selected_signal_keys` の `mapToSource`。
- Tests: `tests/gui/test_graph_panel_vm.py`・`tests/gui/test_graph_panel_view.py`（グリッド）・`tests/gui/test_channel_browser_vm.py`・`tests/gui/test_qt_signal_models.py`（ツールチップ）・`tests/gui/test_channel_browser_view.py`（ソート）・`tests/realgui/test_grid_realclick.py`（新規）＋`tests/realgui/test_signal_dnd_realclick.py`（無回帰）。

---

## Task 1: グリッド（PC-15・DP13）— VM 状態＋X 方向縦グリッド描画

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`value_precision`:162 付近の状態群に `grid_enabled`／`set_value_precision`:1045 付近の隣に `toggle_grid`）
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`build_context_menu`:2392 の「Reset All Axes」後に checkable「グリッド」／`_on_vm_change`:866 に "grid" 分岐／`_apply_grid`／軸再構築メソッド末尾〔`self._build_signature = signature` :1189 の直後〕で `_apply_grid()`）
- Test: `tests/gui/test_graph_panel_vm.py`・`tests/gui/test_graph_panel_view.py`

**Interfaces:**
- Consumes（既存）: `self._x_axis`（`pg.AxisItem` bottom・master ViewBox に link）・`self._notify`・`_on_vm_change`。
- Produces:
  - `GraphPanelVM.grid_enabled: bool`（既定 False・パネルごと transient）
  - `GraphPanelVM.toggle_grid(on: bool) -> None`（設定＋`_notify("grid")`）
  - `GraphPanelView._apply_grid()`（`_x_axis.setGrid(_GRID_ALPHA if vm.grid_enabled else False)`）
  - モジュール定数 `_GRID_ALPHA = 60`

**GUI テスト分析（gui-test-plan）:**
- 変更種別: VM 状態（Layer A）＋メニュー構成・描画反映（Layer B）＋実描画ピクセル（Layer C=Task 4）。
- 実質性: Layer A で `grid_enabled` トグル＋notify。Layer B で「グリッド」が checkable＋現在値反映＋トグルで `_x_axis.grid` が `_GRID_ALPHA`⇄`False` に変わる（`AxisItem.setGrid` は `self.grid` に格納するので introspect 可能）。**描画された縦線が実際に見えるか**は Layer C（Task 4・スクショ）。
- honest layering note: `_x_axis.grid` の値変化は「setGrid を呼んだ」証拠であって「線が描画されて見える」証拠ではない。ピクセルの正しさは Task 4 の realgui スクショでのみ誠実に確認する（memory `gui_offscreen_grab_text_tofu`）。

- [ ] **Step 1: 失敗するテストを書く（VM グリッド状態）**

`tests/gui/test_graph_panel_vm.py` に追記（既存の `_loaded_vm`/`subscribe` 作法に合わせる）:

```python
def test_grid_enabled_defaults_false(tmp_path):
    vm = _loaded_vm(tmp_path)
    assert vm.grid_enabled is False


def test_toggle_grid_updates_and_notifies(tmp_path):
    vm = _loaded_vm(tmp_path)
    seen: list[str] = []
    vm.subscribe(lambda change: seen.append(change))
    vm.toggle_grid(True)
    assert vm.grid_enabled is True
    assert "grid" in seen
    vm.toggle_grid(False)
    assert vm.grid_enabled is False
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k grid -v`
Expected: FAIL（`grid_enabled` 属性なし）

- [ ] **Step 3: VM に grid 状態を実装**

`graph_panel_vm.py` の `__init__`、`self.value_precision` 定義（:162 付近）の直後に:

```python
        # X 方向グリッド線の表示（パネルごと transient・PC-15/DP13）。
        self.grid_enabled: bool = False
```

`set_value_precision`（:1045 付近）の隣に:

```python
    def toggle_grid(self, on: bool) -> None:
        """Toggle the per-panel X-direction grid and notify the view to re-apply."""
        self.grid_enabled = on
        self._notify("grid")
```

- [ ] **Step 4: 通過を確認（VM グリッド）**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k grid -v`
Expected: PASS（2 件）

- [ ] **Step 5: 失敗するテストを書く（View グリッド反映）**

`tests/gui/test_graph_panel_view.py` に追記（既存の GraphPanelView 構築ヘルパに合わせる。単一パネル/軸の最小構成で可）:

```python
def test_grid_menu_toggles_x_axis_grid(qtbot, tmp_path):
    view = _make_panel_view(qtbot, tmp_path)  # 既存の最小 GraphPanelView 構築ヘルパ
    # メニューの「グリッド」項目
    menu = view.build_context_menu()
    grid_act = next(a for a in menu.actions() if a.text() == "グリッド")
    assert grid_act.isCheckable()
    assert grid_act.isChecked() is False
    # トグル ON → _x_axis に grid alpha が設定される
    grid_act.setChecked(True)
    assert view.vm.grid_enabled is True
    assert view._x_axis.grid  # AxisItem.grid は setGrid の値（False→alpha）
    # トグル OFF → grid 無効化
    grid_act.setChecked(False)
    assert view.vm.grid_enabled is False
    assert view._x_axis.grid is False


def test_grid_menu_reflects_current_state(qtbot, tmp_path):
    view = _make_panel_view(qtbot, tmp_path)
    view.vm.toggle_grid(True)
    menu = view.build_context_menu()
    grid_act = next(a for a in menu.actions() if a.text() == "グリッド")
    assert grid_act.isChecked() is True
```

（`_make_panel_view` は既存テストの GraphPanelView 構築ヘルパ名に合わせる。無ければ既存 `test_graph_panel_view.py` が使う構築パターン〔`GraphPanelVM` に 1 信号 add＋`GraphPanelView(vm)`＋`qtbot.addWidget`〕で小ヘルパを追加。`_x_axis` は `__init__` で生成済みなので軸再構築前でも grid 反映は可能だが、`build_context_menu` のトグルが確実に `_apply_grid` を通す経路〔`toggle_grid`→notify "grid"→`_on_vm_change`→`_apply_grid`〕を検証する。）

- [ ] **Step 6: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k grid -v`
Expected: FAIL（「グリッド」メニュー項目なし）

- [ ] **Step 7: View にグリッドメニュー＋反映を実装**

`graph_panel_view.py` モジュール先頭の定数付近に:

```python
_GRID_ALPHA = 60  # X グリッド線のアルファ（0-255・淡色）
```

`build_context_menu`（:2392 の「Reset All Axes」ブロック直後）に checkable「グリッド」を追加:

```python
        grid_act = menu.addAction("グリッド")
        grid_act.setCheckable(True)
        grid_act.setChecked(self.vm.grid_enabled)
        # setChecked BEFORE toggled.connect so the initial state-set does not fire the handler
        grid_act.toggled.connect(lambda checked: self.vm.toggle_grid(checked))
```

`_apply_grid` メソッドを追加（`_on_vm_change` の近く）:

```python
    def _apply_grid(self) -> None:
        """Reflect the VM's grid_enabled onto the shared X axis (vertical grid lines)."""
        self._x_axis.setGrid(_GRID_ALPHA if self.vm.grid_enabled else False)
```

`_on_vm_change`（:866）の分岐に "grid" を追加（cursor/delta 分岐の近くに、full rebuild を伴わない軽量反映として）:

```python
        if change == "grid":
            self._apply_grid()
            return
```

軸再構築メソッド末尾（`self._build_signature = signature` :1189 の直後）に、再構築後もグリッド状態を維持するため:

```python
        self._apply_grid()
```

- [ ] **Step 8: 通過を確認＋フルスイート**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k grid -v`
Expected: PASS（2 件）

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 9: コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_vm.py tests/gui/test_graph_panel_view.py
git commit -m "feat(gui): X 方向グリッド表示トグル（パネルごと・PC-15/DP13）"
```

---

## Task 2: チャンネルツールチップ（PC-19・DP14）— 遅延リッチツールチップ

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`（`tooltip_for(key)`＋`_signal_by_key`／`SignalItem.tooltip` 廃止・`signals` の `tooltip=` 削除／`_labels_tooltip` は `tooltip_for` から再利用）
- Modify: `src/valisync/gui/adapters/qt_signal_models.py`（ToolTipRole:137-138 を `self._vm.tooltip_for(item.key)` へ）
- Test: `tests/gui/test_channel_browser_vm.py`・`tests/gui/test_qt_signal_models.py`

**Interfaces:**
- Consumes（既存）: `self._app_vm.session.group_signals(active_key)`（active file の Signal 群・`sig.name` は namespaced key）・`Signal.metadata`（`unit`/`comment`/`channel_group_name`/`source_name`/`value_labels`）・`Signal.bus_type`・`Signal.timestamps`・既存 `_labels_tooltip`。
- Produces:
  - `ChannelBrowserVM.tooltip_for(key: str) -> str`（遅延・欠損行省略・空なら ""）
  - `SignalItem` から `tooltip` フィールド削除（`name`/`unit`/`key` のみ）
  - `SignalTableModel` ToolTipRole が `vm.tooltip_for(item.key)` を返す（`or None`）

**GUI テスト分析（gui-test-plan）:**
- 変更種別: 純 VM 組立（Layer A）＋モデル ToolTipRole 配線（Layer B）。
- 実質性: Layer A で `tooltip_for` が単位/サンプル数/由来/コメント/ラベルを含み、**欠損行を省略**することを assert（MDF 相当のフル metadata と CSV 相当の unit のみの 2 ケースで弁別）。Layer B で ToolTipRole がその文字列を返す。
- honest layering note: Qt 標準の ToolTipRole 自動表示なので実ホバーは A/B で十分（realgui 任意・Task 4 で扱わない）。`tooltip_for` は**遅延**（`signals` で eager 生成しない）＝ホバー時のみ算出を、model が `item.tooltip`（廃止）でなく `tooltip_for(item.key)` を呼ぶ形で担保する。

- [ ] **Step 1: 失敗するテストを書く（tooltip_for 組立）**

`tests/gui/test_channel_browser_vm.py` に追記（既存の VM 構築＋metadata 付き信号登録の作法に合わせる）:

```python
def test_tooltip_for_full_metadata(tmp_path):
    # MDF 相当: unit + comment + channel_group_name + source_name + value_labels
    vm = _cb_vm_with_signal(
        tmp_path,
        key_orig="gear",
        metadata={
            "unit": "-",
            "comment": "現在のギア段",
            "channel_group_name": "PT_CAN",
            "source_name": "ECU1",
            "value_labels": {0: "N", 1: "D"},
        },
        bus_type="CAN",
        n_samples=1234,
    )
    key = vm.signals[0].key
    tip = vm.tooltip_for(key)
    assert "単位: -" in tip
    assert "サンプル数: 1234" in tip
    assert "CAN" in tip and "PT_CAN" in tip and "ECU1" in tip  # 由来
    assert "現在のギア段" in tip  # コメント
    assert "N" in tip and "D" in tip  # value_labels (LD-07)


def test_tooltip_for_csv_omits_absent_rows(tmp_path):
    # CSV 相当: unit のみ、bus_type 空、comment/group/source/labels なし
    vm = _cb_vm_with_signal(
        tmp_path, key_orig="speed", metadata={"unit": "km/h"},
        bus_type="", n_samples=50,
    )
    key = vm.signals[0].key
    tip = vm.tooltip_for(key)
    assert "単位: km/h" in tip
    assert "サンプル数: 50" in tip
    assert "由来:" not in tip      # bus_type/group/source 全欠損 → 由来行なし
    assert "コメント:" not in tip  # comment なし
    assert "ラベル:" not in tip    # value_labels なし


def test_tooltip_for_unknown_key_empty(tmp_path):
    vm = _cb_vm_with_signal(tmp_path, key_orig="speed", metadata={"unit": "km/h"})
    assert vm.tooltip_for("nonexistent::key") == ""
```

（`_cb_vm_with_signal` は既存テストの ChannelBrowserVM 構築ヘルパに合わせる。無ければ `Session` に metadata/bus_type 付き `Signal`〔frozen・構築時 `metadata={...}`, `bus_type=...`, `timestamps=np.arange(n)` 等〕を register して `active_file_key` を立て、`ChannelBrowserVM(app_vm)` を返す小ヘルパを test モジュール先頭に追加。namespaced key の作り方は既存 `signals` プロパティの検証テストに倣う。）

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py -k tooltip_for -v`
Expected: FAIL（`tooltip_for` 未定義）

- [ ] **Step 3: `tooltip_for`＋`_signal_by_key` を実装し `SignalItem.tooltip` を廃止**

`channel_browser_vm.py` の `SignalItem`（:20-27）から `tooltip` フィールドを削除:

```python
@dataclass(frozen=True)
class SignalItem:
    """Represents a single signal entry in the browser list."""

    name: str  # Original name, e.g. "speed"
    unit: str  # Physical unit, e.g. "km/h"
    key: str  # Full namespaced key, e.g. "csv_1::speed"
```

`signals` プロパティ（:89-95）の `SignalItem(...)` から `tooltip=_labels_tooltip(sig.metadata)` を削除:

```python
            results.append(
                SignalItem(name=orig_name, unit=str(unit), key=sig.name)
            )
```

`Selection` 節の後（`selected` の下・:160 付近）に:

```python
    # ─── Tooltip (PC-19・DP14) ───────────────────────────────────────────────

    def _signal_by_key(self, key: str) -> Any | None:
        """Look up the active file's Signal whose namespaced name == key."""
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        try:
            for sig in self._app_vm.session.group_signals(active_key):
                if sig.name == key:
                    return sig
        except KeyError:
            return None
        return None

    def tooltip_for(self, key: str) -> str:
        """Lazily assemble a multi-line tooltip for *key* (PC-19).

        Sections (absent lines omitted for CSV/Derived): unit / sample count
        (raw recorded len) / origin (bus_type, channel_group_name, source_name) /
        comment / value_labels. Time range is intentionally excluded.
        """
        sig = self._signal_by_key(key)
        if sig is None:
            return ""
        md = sig.metadata or {}
        lines: list[str] = []
        unit = md.get("unit", "")
        if unit:
            lines.append(f"単位: {unit}")
        lines.append(f"サンプル数: {len(sig.timestamps)}")
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
            lines.append(f"由来: {origin}")
        comment = md.get("comment", "")
        if comment:
            lines.append(f"コメント: {comment}")
        labels = _labels_tooltip(md)  # "ラベル: ..." or ""
        if labels:
            lines.append(labels)
        return "\n".join(lines)
```

（`_labels_tooltip` は既存のまま残置し `tooltip_for` から呼ぶ。`signals` からは呼ばなくなる。）

- [ ] **Step 4: 通過を確認（tooltip_for）**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py -k tooltip_for -v`
Expected: PASS（3 件）

- [ ] **Step 5: ToolTipRole を tooltip_for へ配線し既存モデルテストを更新**

`qt_signal_models.py` の ToolTipRole（:137-138）を:

```python
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._vm.tooltip_for(item.key) or None
```

- [ ] **Step 6: 失敗するテストを書く／既存テストを更新（ToolTipRole）**

`tests/gui/test_qt_signal_models.py` の既存 ToolTipRole テスト（value_labels のみ期待）を、`tooltip_for` のリッチ内容へ更新。まず Run で赤箇所を特定:

Run: `uv run pytest tests/gui/test_qt_signal_models.py -k tooltip -v`
Expected: 旧期待（value_labels 文字列のみ）が FAIL → ToolTipRole が返す文字列に「サンプル数:」等が含まれる新期待へ更新（value_labels があるケースは「ラベル:」も含む＝LD-07 退行なし）。

同様に `tests/gui/test_channel_browser_vm.py` の `SignalItem.tooltip` を参照する既存テスト（:92-147 の value_labels 検証）を、`tooltip_for` 検証へ移行（`SignalItem` に `tooltip` 属性がなくなるため）。

- [ ] **Step 7: 通過を確認＋フルスイート**

Run: `uv run pytest tests/gui/test_qt_signal_models.py tests/gui/test_channel_browser_vm.py -v`
Expected: PASS

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors（`SignalItem.tooltip` の他消費者が残っていれば mypy/テストで露見 → `tooltip_for` へ寄せる）

- [ ] **Step 8: コミット**

```bash
git add src/valisync/gui/viewmodels/channel_browser_vm.py src/valisync/gui/adapters/qt_signal_models.py tests/gui/test_channel_browser_vm.py tests/gui/test_qt_signal_models.py
git commit -m "feat(gui): チャンネル一覧の遅延リッチツールチップ tooltip_for（単位/サンプル数/由来/コメント/ラベル・PC-19/DP14）"
```

---

## Task 3: 列ソート（PC-20・DP2）— QSortFilterProxyModel

**Files:**
- Modify: `src/valisync/gui/views/channel_browser_view.py`（`QSortFilterProxyModel` 挿入・`setSortingEnabled(True)`・`selected_signal_keys` の `mapToSource`）
- Test: `tests/gui/test_channel_browser_view.py`

**Interfaces:**
- Consumes（既存）: `SignalTableModel`（source・`signal_key_at`・`mimeData`）・`self.tree`（QTreeView）・`selected_signal_keys`（:161-168）。
- Produces:
  - `ChannelBrowserView.proxy: QSortFilterProxyModel`（source=SignalTableModel・sort 専用）
  - `self.tree.setModel(self.proxy)`＋`setSortingEnabled(True)`
  - `selected_signal_keys()` が proxy index を `mapToSource` して源 index の key を返す

**GUI テスト分析（gui-test-plan）:**
- 変更種別: ウィジェット構成（proxy 挿入）＋選択/D&D の index 経路（Layer B）。
- 実質性: Layer B で `proxy.sort(0)` 後の表示順が名前昇順／降順になる・`selected_signal_keys` がソート後も正しい key を返す（`mapToSource` 経由）ことを assert。**D&D の mimeData が proxy 経由でも源 index にマップされ正しい key を積む**ことを Layer B で確認し、**実 D&D 配送の無回帰は Task 4 の realgui**（合成再現不可）。
- **realgui 掴み点再監査は不要**（本タスクはゾーン境界を動かさない）。ただし **proxy 挿入で D&D のドラッグ元 index 経路が変わる**ため Task 4 で既存 realgui D&D を必ず再実行。
- honest layering note: `selected_signal_keys` の `mapToSource` を入れ忘れると、ソート後に**見た目と違う信号が選択/ドラッグされる**（ソート未適用時は proxy index==源 index で偶然通るため、テストは**必ずソートを適用してから**選択 key を検証すること＝false-green 回避）。

- [ ] **Step 1: 失敗するテストを書く（ソート順＋mapToSource 選択）**

`tests/gui/test_channel_browser_view.py` に追記（既存の ChannelBrowserView 構築＋複数信号登録の作法に合わせる。名前が非ソート順に並ぶ 3 信号を用意）:

```python
def test_default_order_is_source_order(qtbot, tmp_path):
    # ソート未クリックの既定は源順(登録順)を保つ(sortByColumn(-1) パススルー)。
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    names = [view.proxy.index(r, 0).data() for r in range(view.proxy.rowCount())]
    assert names == ["zed", "alpha", "mid"]  # 名前昇順に勝手に並び替えない


def test_header_click_sorts_by_name(qtbot, tmp_path):
    # 登録順 "zed","alpha","mid" → 名前昇順ソートで alpha,mid,zed
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    view.proxy.sort(0, Qt.SortOrder.AscendingOrder)  # Name 列 昇順
    names = [
        view.proxy.index(r, 0).data() for r in range(view.proxy.rowCount())
    ]
    assert names == ["alpha", "mid", "zed"]


def test_selected_keys_correct_after_sort(qtbot, tmp_path):
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    view.proxy.sort(0, Qt.SortOrder.AscendingOrder)
    # ソート後の視覚的先頭行(=alpha)を選択 → mapToSource で alpha の key が返る
    top = view.proxy.index(0, 0)
    view.tree.selectionModel().select(
        top, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    )
    keys = view.selected_signal_keys()
    assert len(keys) == 1
    assert keys[0].endswith("::alpha")  # 見た目どおり alpha（源 index ずれで zed にならない）


def test_dnd_mime_keys_correct_after_sort(qtbot, tmp_path):
    view = _cb_view_with_signals(qtbot, tmp_path, ["zed", "alpha", "mid"])
    view.proxy.sort(0, Qt.SortOrder.AscendingOrder)
    top = view.proxy.index(0, 0)
    view.tree.selectionModel().select(
        top, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    )
    md = view.mime_data_for_selection()
    from valisync.gui.adapters.qt_signal_models import decode_signal_keys

    keys = decode_signal_keys(md)
    assert keys and keys[0].endswith("::alpha")
```

（import: `from PySide6.QtCore import Qt, QItemSelectionModel`。`_cb_view_with_signals(qtbot, tmp_path, names)` は既存 ChannelBrowserView テストの構築ヘルパに合わせる。無ければ `AppViewModel`+`Session` に names の信号を register→`active_file_key` を立て→`ChannelBrowserVM`→`ChannelBrowserView` を作り `qtbot.addWidget` する小ヘルパを追加。フィルタは未使用〔proxy は sort 専用〕。）

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_channel_browser_view.py -k "sorts_by_name or after_sort" -v`
Expected: FAIL（`view.proxy` 未定義・または mapToSource 未適用で `selected_signal_keys` が源順の key を返す）

- [ ] **Step 3: QSortFilterProxyModel を挿入し selected_signal_keys を mapToSource 化**

`channel_browser_view.py` の import に `QSortFilterProxyModel` を追加:

```python
from PySide6.QtCore import (
    QEvent,
    QItemSelection,
    QMimeData,
    QObject,
    QPoint,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
```

`__init__` のモデル生成（:55 `self.model = SignalTableModel(vm)`）と tree への設定（:70 `self.tree.setModel(self.model)`）を proxy 経由へ:

```python
        self.model = SignalTableModel(vm)
        # PC-20: ソート専用の proxy を挟む(フィルタは現行どおり VM 真実 = proxy は
        # accept-all のまま)。ヘッダクリックで Name/Unit 列ソート。
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
```

`self.tree.setModel(self.model)`（:70）を:

```python
        self.tree.setModel(self.proxy)
        self.tree.setSortingEnabled(True)
        # setSortingEnabled(True) は「現在のソート指標」で即時 sortByColumn する。
        # 既定は源順(セッション/グループ順)を保ち、ヘッダクリックで初めてソート
        # する挙動にしたいので、proxy のソート列を -1(パススルー)へ戻す(spec DP2:
        # 「ヘッダクリックで名前/単位ソート」= 既定ソートは要求されていない)。
        self.tree.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
```

`selected_signal_keys`（:161-168）を proxy→source マップへ:

```python
    def selected_signal_keys(self) -> list[str]:
        """Return the namespaced keys of the currently-selected signal rows.

        Rows are proxy indexes (sort may reorder them), so each must be mapped
        back to the source model before resolving its key -- otherwise a sorted
        view would drag/select the wrong signal (PC-20).
        """
        keys: list[str] = []
        for index in self.tree.selectionModel().selectedRows(0):
            src = self.proxy.mapToSource(index)
            key = self.model.signal_key_at(src)
            if key is not None:
                keys.append(key)
        return keys
```

（D&D: `self.tree` は proxy モデルを持つため、Qt はドラッグ時に `proxy.mimeData(proxyIndexes)` を呼ぶ。`QSortFilterProxyModel.mimeData` は proxy index を源にマップして `SignalTableModel.mimeData` を源 index で呼ぶので、mimeData 経路は自動で正しい。`mime_data_for_selection` は `selected_signal_keys`〔mapToSource 済み〕を使うので追加修正不要。**この自動マップの無回帰実証は Task 4 の実 D&D**。）

- [ ] **Step 4: 通過を確認（ソート＋選択＋mime）**

Run: `uv run pytest tests/gui/test_channel_browser_view.py -k "sorts_by_name or after_sort" -v`
Expected: PASS（3 件）

- [ ] **Step 5: フィルタ無回帰を確認（proxy はソート専用）**

Run: `uv run pytest tests/gui/test_channel_browser_view.py -v`
Expected: 既存のフィルタ/選択/空状態/D&D mime テストが全 PASS（proxy 挿入でフィルタ経路〔VM set_filter→model reset〕が壊れていない）。赤があれば proxy にフィルタを設定していないか・selectionModel 参照が proxy 後も有効かを確認。

- [ ] **Step 6: フルスイート＋ゲート**

Run: `uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS / 0 errors

- [ ] **Step 7: コミット**

```bash
git add src/valisync/gui/views/channel_browser_view.py tests/gui/test_channel_browser_view.py
git commit -m "feat(gui): 信号列のヘッダソート（QSortFilterProxyModel・mapToSource 選択/D&D・PC-20/DP2）"
```

---

## Task 4: realgui 証拠（Layer C・実 OS 入力）

**Files:**
- Create: `tests/realgui/test_grid_realclick.py`（実右クリック→「グリッド」実クリック→縦グリッド線のスクショ）
- Test: 既存 `tests/realgui/test_signal_dnd_realclick.py` を①ゲートで再実行（proxy 挿入の D&D 無回帰）

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input`（`at`/`RDOWN`/`RUP`/`LDOWN`/`LUP`/`to_phys`/`skip_unless_real_display`）・既存パネル realgui の `_shown_panel`/`_open_menu_click_item`/`_menu_hang_watchdog` 作法（`test_axis_menu_offset.py` の忠実コピー）・View introspection `_x_axis.grid`。
- Produces: 実 OS 入力の証拠（pass/fail・スクショ）。

**GUI テスト分析（gui-test-plan）:**
- spec §11 増分4: グリッドの実描画スクショ判定（ピクセルの正しさは realgui のみ誠実）・**既存 ChannelBrowser 発 realgui D&D の再実行で無回帰証拠化**（proxy でドラッグ元 index 経路が変わる）・ツールチップは Qt 標準 ToolTipRole 自動表示で A/B 十分（realgui 任意・本タスクでは扱わない）。
- 実質性: 実右クリック→実「グリッド」クリックで `_x_axis.grid` が有効化＋**スクショに縦グリッド線が見える**（load-bearing はスクショ目視＋introspection）。D&D は既存 realgui の再 pass。
- 掴み点は可視プロット矩形内（memory `gui_realgui_offscreen_target_opens_os_system_menu`）。menu.exec ハング回避に `_menu_hang_watchdog` 併設。

- [ ] **Step 1: グリッド実描画の realgui を書く**

`tests/realgui/test_grid_realclick.py`（新規）。`_shown_panel` と `_open_menu_click_item`/`_menu_hang_watchdog` は `tests/realgui/test_axis_menu_offset.py`（lines 34-204）から module-local に忠実コピー（`_realgui_input` の import・`QEventLoop`/`QTimer`/`QMenu`/`threading`/`VK_ESCAPE`/`key as key_input` 込み）。プロット空白部を実右クリック→「グリッド」を実クリック:

```python
@pytest.mark.realgui
def test_real_grid_menu_draws_vertical_lines(qtbot, tmp_path):
    """空白実右クリック → 「グリッド」実クリック → _x_axis.grid 有効化＋縦線スクショ。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    for _ in range(3):
        QApplication.processEvents()
    assert view._x_axis.grid is False  # 既定 OFF
    # プロット矩形の空白部(信号・軸ゾーン外)を実右クリック
    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    sx = rect.x() + rect.width() * 0.5
    sy = rect.y() + rect.height() * 0.5
    px, py = to_phys(view, sx, sy)
    shot = tmp_path / "grid_on.png"
    captured = _open_menu_click_item(view, (px, py), "グリッド", shot)
    for _ in range(5):
        QApplication.processEvents()
    assert captured.get("type") == "QMenu"
    assert "グリッド" in (captured.get("actions") or [])
    assert view.vm.grid_enabled is True
    assert view._x_axis.grid  # setGrid が効いている(alpha)
    # スクショ(grid_on.png)に縦グリッド線が描画されていることを目視確認する
    #   (QT_QPA_PLATFORM=windows。ピクセルの正しさは realgui のみ誠実)
```

（`_shown_panel` はプロットが可視・空白右クリックが `build_context_menu` を出す最小構成。空白部でメニューが出るよう、掴み点は曲線・軸ゾーンを避けた中央寄りに取る。）

- [ ] **Step 2: グリッド realgui を①ゲートで実行**

Run: `QT_QPA_PLATFORM=windows uv run pytest --realgui tests/realgui/test_grid_realclick.py -v`
Expected: PASS（実ディスプレイ時）。スクショ `grid_on.png` に**縦グリッド線**が見えることを目視。
（実ディスプレイ無しなら `skip_unless_real_display()` でスキップ → 正直に報告。skip を緑と誤認しない。）

- [ ] **Step 3: ChannelBrowser D&D の無回帰を①ゲートで実行**

proxy 挿入でドラッグ元 index 経路が変わったため、既存のクロスウィジェット実 D&D を再実行して無回帰を実証:

Run: `uv run pytest --realgui tests/realgui/test_signal_dnd_realclick.py -v`
Expected: PASS（proxy 経由でも mimeData が源 index にマップされ、正しい信号がドロップされる）

- [ ] **Step 4: Layer C 契約ガード＋headless full**

Run: `uv run pytest tests/gui/test_realgui_layer_c_contract.py -v`
Expected: PASS（新規 realgui が実 OS 入力）

Run: `uv run pytest`
Expected: headless full 0 errors（realgui 自動スキップ）

- [ ] **Step 5: ①証拠ゲート判定（merge 前・`/gui-verify`）**
  - (a) headless full `uv run pytest` 0 errors
  - (b) realgui 証拠: 新規グリッド 1 本 pass＋スクショ（縦線目視）・既存 `test_signal_dnd_realclick.py` 無回帰 pass・Layer C 契約ガード pass
  - (c) CI 緑（push 後 PR で確認）

- [ ] **Step 6: コミット**

```bash
git add tests/realgui/test_grid_realclick.py
git commit -m "test(realgui): グリッド実描画＋ChannelBrowser D&D 無回帰の実 OS 入力検証（Layer C ①ゲート）"
```

---

## Self-Review

**1. Spec coverage（§9 増分4＝PC-15/PC-19/PC-20）:**

| spec 要件 | 担当タスク |
|---|---|
| グリッド checkable・X 方向・`GraphPanelVM.grid_enabled`（パネルごと transient）・`_x_axis` 描画（PC-15/DP13） | Task 1 |
| チャンネルツールチップ 遅延 `tooltip_for`（単位/サンプル数/由来/コメント/value_labels・欠損省略・時間範囲なし）（PC-19/DP14） | Task 2 |
| 列ソート `QSortFilterProxyModel`＋`setSortingEnabled`・フィルタは VM 真実・選択/D&D は `mapToSource`（PC-20/DP2） | Task 3 |
| グリッド実描画スクショ・ChannelBrowser D&D 無回帰（proxy 経路変化）・ツールチップは A/B 十分と文書化 | Task 4 |

**2. Placeholder scan:** 各コード step に実コードあり。realgui（Task 4）の `_open_menu_click_item`/`_menu_hang_watchdog` は既存 `test_axis_menu_offset.py` の確立パターンへの委譲（実装者は忠実 module-local コピー）。テスト構築ヘルパ（`_loaded_vm`/`_cb_vm_with_signal`/`_cb_view_with_signals`/`_make_panel_view`）は既存テストの構築作法に合わせる旨を明記（無ければ既存パターンで小ヘルパ追加）。

**3. Type consistency:**
- `grid_enabled: bool`（Task 1 定義）→ View が `_x_axis.setGrid(_GRID_ALPHA if self.vm.grid_enabled else False)` で消費・`toggle_grid(on: bool)` の型一致。
- `tooltip_for(key: str) -> str`（Task 2 定義）→ `SignalTableModel` ToolTipRole が `vm.tooltip_for(item.key)` で呼ぶ（`item.key: str`・戻り str）。
- `SignalItem` から `tooltip` 削除（Task 2）→ model の `item.tooltip` 参照を `tooltip_for(item.key)` へ同時変更（残存参照は mypy/テストで露見）。
- `proxy: QSortFilterProxyModel`（Task 3）→ `selected_signal_keys` が `self.proxy.mapToSource(index)`→`self.model.signal_key_at(src)`。`self.model` は源 `SignalTableModel` のまま保持（`signal_key_at`/`mimeData` を源として使う）。

**4. 依存順:** 3 機能は独立（Task 1 グリッド・Task 2 ツールチップ・Task 3 ソートは相互依存なし）。Task 4（realgui）は Task 1（グリッド描画）と Task 3（proxy による D&D 経路変化）の後に実施し、両者の実 OS 証拠と無回帰をまとめて取る。各タスクは独立テスト可能な成果物で終わる。

**5. honest layering:** グリッドは Layer A（VM）＋Layer B（menu/`_x_axis.grid` 反映）で状態遷移を、Layer C（Task 4・スクショ）で**実際に縦線が見える**ピクセルを検証（`_x_axis.grid` 値は「setGrid を呼んだ」証拠に過ぎない）。ツールチップは Qt 標準 ToolTipRole で A/B 十分（realgui 任意）。ソートは Layer B で `mapToSource` の正しさを**必ずソート適用後に**検証（未ソートは proxy index==源 index で false-green）＋Layer C で実 D&D 無回帰（合成再現不可）。
