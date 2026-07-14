# FU-09 軸メニュー中心基準ズーム＋X軸メニュー整備 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Y軸/X軸の右クリックメニューに中心基準の離散ズーム（イン half*0.9 / アウト half*1.1 = 10%）を追加し、X軸メニュー（`build_x_axis_menu`）を Y と対等（autofit/範囲指定/zoom in/out）に新設する。

**Architecture:** VM（`graph_panel_vm.py`）に純関数 `_scaled_range` と `zoom_axis`/`zoom_x` を追加（既存 `set_axis_range`/`set_x_range` へ委譲＝X-sync fan-out 相乗り）。View（`graph_panel_view.py`）は `build_axis_menu` に zoom 2項目を追加、新 `build_x_axis_menu` と `_prompt_x_range` を追加、`_default_range_dialog` に X タイトル分岐（`axis_index=-1` センチネル）、`contextMenuEvent` に ZONE_X ブランチを追加。

**Tech Stack:** PySide6/pyqtgraph, MVVM, pytest-qt。

## Global Constraints

- 変更は `gui/viewmodels/`（VM ロジック）と `gui/views/`（メニュー/ルーティング）に閉じる。core は Qt 非依存維持。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過（unscoped・repo ルートで実行し出力そのまま報告）。
- Python コメント/文字列に全角約物 `()：+=` 禁止（RUF001/002/003）。ASCII を使う。例外: メニューラベル `"ズームアウト（引き）"` の全角括弧は UI 日本語ラベルゆえ `# noqa: RUF001` を付ける（既存 `menu.addAction("サブカーソル（Δ）")  # noqa: RUF001` に倣う）。X 範囲ダイアログのタイトルは全角括弧を避けるため `"X軸の範囲を指定"`（既存 `"Y軸の範囲を指定"` と同形・parens なし）を使う。
- 倍率: イン=`0.9`（half*0.9）/ アウト=`1.1`（half*1.1）。中心保持。Y/X 共通。
- `zoom_x` は `set_x_range` 経由で既存 X-sync fan-out に相乗り（`_x_range_is_auto=False`＋`notify("range")`）。
- 入力経路（メニュー項目追加＋ZONE_X ルーティング）変更ゆえ merge 前に gui-verify ①（realgui 実メニュー項目クリック＋journey smoke）。

---

### Task 1: VM — `_scaled_range` 純関数 ＋ `zoom_axis` ＋ `zoom_x`

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`import math` は既存・`set_axis_range` 付近 `:624` と `set_x_range` `:606` を再利用）
- Test: `tests/gui/test_graph_panel_vm.py`（末尾に追加。既存ヘルパ `_loaded_session(tmp_path, n_rows=...)`・`GraphPanelVM`・`import pytest` はファイル内に既存）

**Interfaces:**
- Consumes: 既存 `set_axis_range(axis_index, lo, hi)`・`set_x_range(lo, hi)`・`axes[i].y_range: tuple|None`・`x_range: tuple|None`。
- Produces: モジュール関数 `_scaled_range(lo: float, hi: float, factor: float) -> tuple[float, float] | None`・メソッド `zoom_axis(axis_index: int, factor: float) -> None`・`zoom_x(factor: float) -> None`。

- [ ] **Step 1: 失敗テストを追加**

`tests/gui/test_graph_panel_vm.py` 末尾に追加:

```python
# ─── FU-09: center-based zoom ────────────────────────────────────────────────


def test_scaled_range_zoom_in_shrinks_around_center() -> None:
    from valisync.gui.viewmodels.graph_panel_vm import _scaled_range

    # (0, 100): center 50, half 50; factor 0.9 -> half 45 -> (5, 95)
    assert _scaled_range(0.0, 100.0, 0.9) == pytest.approx((5.0, 95.0))


def test_scaled_range_zoom_out_expands_around_center() -> None:
    from valisync.gui.viewmodels.graph_panel_vm import _scaled_range

    # factor 1.1 -> half 55 -> (-5, 105)
    assert _scaled_range(0.0, 100.0, 1.1) == pytest.approx((-5.0, 105.0))


def test_scaled_range_none_for_degenerate_or_nonfinite() -> None:
    from valisync.gui.viewmodels.graph_panel_vm import _scaled_range

    assert _scaled_range(5.0, 5.0, 0.9) is None  # half == 0
    assert _scaled_range(math.inf, 1.0, 0.9) is None  # non-finite input
    assert _scaled_range(0.0, 1.0, math.inf) is None  # non-finite result


def test_zoom_axis_scales_y_range_around_center(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    vm.add_signal(session.signals()[0].name)
    vm.set_axis_range(0, 0.0, 100.0)
    vm.zoom_axis(0, 0.9)
    assert vm.axes[0].y_range == pytest.approx((5.0, 95.0))


def test_zoom_axis_noop_when_degenerate_or_bad_index(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    vm.zoom_axis(0, 0.9)  # no axes yet -> no-op, no error
    vm.add_signal(session.signals()[0].name)
    vm.set_axis_range(0, 7.0, 7.0)  # degenerate span
    vm.zoom_axis(0, 0.9)
    assert vm.axes[0].y_range == pytest.approx((7.0, 7.0))  # unchanged


def test_zoom_x_scales_x_range_via_set_x_range(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    vm.add_signal(session.signals()[0].name)
    vm.set_x_range(0.0, 100.0)
    events: list[str] = []
    vm.subscribe(events.append)
    vm.zoom_x(1.1)
    assert vm.x_range == pytest.approx((-5.0, 105.0))
    assert "range" in events  # went through set_x_range (X-sync fan-out entry point)


def test_zoom_x_noop_when_x_range_none(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    assert vm.x_range is None
    vm.zoom_x(0.9)  # no-op, no error
    assert vm.x_range is None
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "scaled_range or zoom_axis or zoom_x" -v`
Expected: FAIL（`_scaled_range`/`zoom_axis`/`zoom_x` 未定義）。

- [ ] **Step 3: 実装**

`graph_panel_vm.py`。モジュールレベル（他のモジュール関数 `_padded_range` 付近）に純関数を追加:

```python
def _scaled_range(lo: float, hi: float, factor: float) -> tuple[float, float] | None:
    """Scale a range around its center by *factor* (FU-09 center-based zoom).

    factor < 1 shrinks (zoom in), > 1 expands (zoom out). Returns None for a
    degenerate (zero-width) span or any non-finite input/result, so callers
    treat it as a no-op rather than producing an unusable range.
    """
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return None
    center = (lo + hi) / 2.0
    half = (hi - lo) / 2.0 * factor
    if half == 0.0:
        return None
    new_lo, new_hi = center - half, center + half
    if not (math.isfinite(new_lo) and math.isfinite(new_hi)):
        return None
    return (new_lo, new_hi)
```

`GraphPanelVM` に `set_axis_range` の近くへメソッドを追加:

```python
    def zoom_axis(self, axis_index: int, factor: float) -> None:
        """Zoom one Y-axis around its center by *factor* (FU-09). No-op when the
        axis has no concrete range or the span is degenerate/non-finite."""
        if not (0 <= axis_index < len(self._axes)):
            return
        rng = self._axes[axis_index].y_range
        if rng is None:
            return
        scaled = _scaled_range(rng[0], rng[1], factor)
        if scaled is not None:
            self.set_axis_range(axis_index, scaled[0], scaled[1])

    def zoom_x(self, factor: float) -> None:
        """Zoom the X range around its center by *factor* (FU-09), via set_x_range
        so the existing X-sync fan-out applies. No-op when x_range is unset or the
        span is degenerate/non-finite."""
        if self.x_range is None:
            return
        scaled = _scaled_range(self.x_range[0], self.x_range[1], factor)
        if scaled is not None:
            self.set_x_range(scaled[0], scaled[1])
```

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm.py -k "scaled_range or zoom_axis or zoom_x" -v`
Expected: 全 PASS。

- [ ] **Step 5: 品質ゲート（unscoped）＋コミット**

Run: `uv run pytest`; `uv run ruff check`; `uv run ruff format --check`; `uv run mypy src/`

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm.py
git commit -m "feat(fu09): VM に中心基準ズーム(_scaled_range/zoom_axis/zoom_x)を追加"
```

---

### Task 2: View — 軸メニューへの zoom 追加＋X軸メニュー新設＋ZONE_X ルーティング

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`build_axis_menu` `:2470`・`_default_range_dialog` `:2503`・`contextMenuEvent` `:2549`。定数 `ZONE_X_INNER`/`ZONE_X_OUTER` は同ファイル `:82-83` に既存）
- Test: `tests/gui/test_graph_panel_view.py`（`_build_panel_view_with_axes(qtbot)`・`_spy_menus`・`TestAxisMenuRouting`・`_ctx_event` は既存。`from unittest.mock import Mock`・`from types import SimpleNamespace`・`ZONE_X_INNER` の import 追加要）

**Interfaces:**
- Consumes: Task 1 の `vm.zoom_axis(axis_index, factor)`・`vm.zoom_x(factor)`・既存 `vm.reset_x()`・`vm.set_x_range(lo, hi)`・`vm.x_range`・`vm.axes[i].y_range`・`self._range_dialog_fn`。
- Produces: `build_x_axis_menu() -> QMenu`・`_prompt_x_range() -> None`。`build_axis_menu`/`contextMenuEvent`/`_default_range_dialog` の挙動拡張。

- [ ] **Step 1: 失敗テストを追加**

`tests/gui/test_graph_panel_view.py` に追加（`_spy_menus` に X スタブを1行追加＋新規テスト群）。

まず `_spy_menus`（`:1125`）に `build_x_axis_menu` スタブを追加（既存3スタブの後）:

```python
    view.build_x_axis_menu = lambda: (  # type: ignore[method-assign,attr-defined]
        calls.append(("x_axis", None)) or SimpleNamespace(exec=lambda *a: None)
    )
```

ファイル冒頭の import に `ZONE_X_INNER` を追加（既存 `ZONE_Y_INNER` を import している行へ）。新規テスト:

```python
class TestAxisZoomMenu:
    """FU-09: build_axis_menu/build_x_axis_menu の zoom 項目とルーティング。"""

    def test_y_axis_menu_has_zoom_actions_routed_to_zoom_axis(
        self, qtbot: QtBot
    ) -> None:
        from unittest.mock import Mock, call

        panel = _build_panel_view_with_axes(qtbot)
        panel.vm.set_axis_range(0, 0.0, 100.0)  # ensure a concrete range
        panel.vm.zoom_axis = Mock()  # spy
        menu = panel.build_axis_menu(0)
        acts = {a.text(): a for a in menu.actions()}
        assert "ズームイン" in acts and "ズームアウト（引き）" in acts  # noqa: RUF001
        assert acts["ズームイン"].isEnabled()
        acts["ズームイン"].trigger()
        acts["ズームアウト（引き）"].trigger()  # noqa: RUF001
        assert panel.vm.zoom_axis.call_args_list == [call(0, 0.9), call(0, 1.1)]

    def test_y_axis_zoom_disabled_when_range_none(self, qtbot: QtBot) -> None:
        panel = _build_panel_view_with_axes(qtbot)
        panel.vm.axes[0].set_range(None, None)  # clear the range
        menu = panel.build_axis_menu(0)
        acts = {a.text(): a for a in menu.actions()}
        assert not acts["ズームイン"].isEnabled()
        assert not acts["ズームアウト（引き）"].isEnabled()  # noqa: RUF001

    def test_x_axis_menu_has_four_actions(self, qtbot: QtBot) -> None:
        from unittest.mock import Mock, call

        panel = _build_panel_view_with_axes(qtbot)
        panel.vm.set_x_range(0.0, 100.0)
        panel.vm.reset_x = Mock()
        panel.vm.zoom_x = Mock()
        menu = panel.build_x_axis_menu()
        texts = [a.text() for a in menu.actions()]
        assert texts == [
            "X軸をオートフィット",
            "範囲を指定…",
            "ズームイン",
            "ズームアウト（引き）",  # noqa: RUF001
        ]
        acts = {a.text(): a for a in menu.actions()}
        acts["X軸をオートフィット"].trigger()
        acts["ズームイン"].trigger()
        acts["ズームアウト（引き）"].trigger()  # noqa: RUF001
        assert panel.vm.reset_x.called
        assert panel.vm.zoom_x.call_args_list == [call(0.9), call(1.1)]

    def test_x_axis_zoom_disabled_when_x_range_none(self, qtbot: QtBot) -> None:
        panel = _build_panel_view_with_axes(qtbot)
        panel.vm.x_range = None
        menu = panel.build_x_axis_menu()
        acts = {a.text(): a for a in menu.actions()}
        assert not acts["ズームイン"].isEnabled()
        assert not acts["ズームアウト（引き）"].isEnabled()  # noqa: RUF001

    def test_context_menu_routes_x_axis_on_x_zone(self, qtbot: QtBot) -> None:
        panel = _build_panel_view_with_axes(qtbot)
        panel._curve_at = lambda pos: None  # type: ignore[method-assign]
        panel._zone_at = lambda pos: ZONE_X_INNER  # type: ignore[method-assign]
        calls = _spy_menus(panel)
        panel.contextMenuEvent(_ctx_event())  # type: ignore[attr-defined]
        assert calls == [("x_axis", None)]

    def test_prompt_x_range_applies_set_x_range(self, qtbot: QtBot) -> None:
        from unittest.mock import Mock

        panel = _build_panel_view_with_axes(qtbot)
        panel._range_dialog_fn = lambda axis_index, current: (2.0, 8.0)  # stub dialog
        panel.vm.set_x_range = Mock()
        panel._prompt_x_range()
        panel.vm.set_x_range.assert_called_once_with(2.0, 8.0)
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "TestAxisZoomMenu" -v`
Expected: FAIL（`build_x_axis_menu`/`_prompt_x_range` 未定義・zoom アクション不在・ZONE_X ルーティング未実装）。

- [ ] **Step 3: 実装**

3-1. `build_axis_menu`（`:2470`）に zoom 2項目を「範囲を指定…」の後・「軸を削除」の前へ挿入:

```python
    def build_axis_menu(self, axis_index: int) -> QMenu:
        """Right-click menu for one Y-axis (spec §4.3: オートフィット/範囲指定/削除/曲線一覧)."""
        menu = QMenu(self)
        menu.addAction("この軸をオートフィット").triggered.connect(
            lambda *_: self.vm.reset_axis_y(axis_index)
        )
        menu.addAction("範囲を指定…").triggered.connect(
            lambda *_: self._prompt_axis_range(axis_index)
        )
        # FU-09: center-based discrete zoom. Disabled when the axis has no
        # concrete range (nothing to scale around).
        has_range = (
            0 <= axis_index < len(self.vm.axes)
            and self.vm.axes[axis_index].y_range is not None
        )
        zin = menu.addAction("ズームイン")
        zin.setEnabled(has_range)
        zin.triggered.connect(lambda *_: self.vm.zoom_axis(axis_index, 0.9))
        zout = menu.addAction("ズームアウト（引き）")  # noqa: RUF001
        zout.setEnabled(has_range)
        zout.triggered.connect(lambda *_: self.vm.zoom_axis(axis_index, 1.1))
        menu.addAction("軸を削除").triggered.connect(
            lambda *_: self.vm.remove_axis(axis_index)
        )
        menu.addSeparator()
        for entry_id, name, _color, visible in self.vm.entries_on_axis(axis_index):
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(visible)  # BEFORE toggled.connect (no spurious fire)
            act.toggled.connect(
                lambda _checked, eid=entry_id: self.vm.toggle_entry_visibility(eid)
            )
        return menu

    def build_x_axis_menu(self) -> QMenu:
        """Right-click menu for the X (time) axis (FU-09): autofit / range / zoom."""
        menu = QMenu(self)
        menu.addAction("X軸をオートフィット").triggered.connect(
            lambda *_: self.vm.reset_x()
        )
        menu.addAction("範囲を指定…").triggered.connect(
            lambda *_: self._prompt_x_range()
        )
        has_range = self.vm.x_range is not None
        zin = menu.addAction("ズームイン")
        zin.setEnabled(has_range)
        zin.triggered.connect(lambda *_: self.vm.zoom_x(0.9))
        zout = menu.addAction("ズームアウト（引き）")  # noqa: RUF001
        zout.setEnabled(has_range)
        zout.triggered.connect(lambda *_: self.vm.zoom_x(1.1))
        return menu
```

3-2. `_prompt_x_range` を `_prompt_axis_range`（`:2492`）の後に追加:

```python
    def _prompt_x_range(self) -> None:
        """Open the range dialog for the X (time) axis and apply the chosen [lo, hi].

        Reuses the single range-dialog DI hook: axis_index == -1 is the X-axis
        sentinel (see _default_range_dialog's title branch)."""
        fn = self._range_dialog_fn or self._default_range_dialog
        result = fn(-1, self.vm.x_range)
        if result is not None:
            lo, hi = result
            self.vm.set_x_range(lo, hi)
```

3-3. `_default_range_dialog`（`:2503`）のタイトル行（`:2519` `dlg.setWindowTitle("Y軸の範囲を指定")`）を分岐へ:

```python
        # axis_index == -1 is the X (time) axis sentinel (FU-09); ASCII-safe title
        # (no full-width parens) mirrors the Y title so RUF001 stays clean.
        dlg.setWindowTitle(
            "X軸の範囲を指定" if axis_index == -1 else "Y軸の範囲を指定"
        )
```

3-4. `contextMenuEvent`（`:2549`）に ZONE_X ブランチを Y軸分岐の後・空白フォールバックの前へ追加:

```python
        if self._zone_at(pos) in (ZONE_Y_INNER, ZONE_Y_OUTER):
            self.build_axis_menu(self._axis_index_at(pos)).exec(event.globalPos())
            return
        if self._zone_at(pos) in (ZONE_X_INNER, ZONE_X_OUTER):
            self.build_x_axis_menu().exec(event.globalPos())
            return
        self.build_context_menu().exec(event.globalPos())
```

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -k "TestAxisZoomMenu or TestAxisMenuRouting" -v`
Expected: 全 PASS（新規＋既存ルーティング無回帰）。

- [ ] **Step 5: 品質ゲート（unscoped）＋コミット**

Run: `uv run pytest`; `uv run ruff check`; `uv run ruff format --check`; `uv run mypy src/`

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_view.py
git commit -m "feat(fu09): 軸メニューに中心基準ズーム追加＋X軸メニュー新設(ZONE_X ルーティング)"
```

---

### Task 3: gui-verify ①ゲート（realgui 実メニュー項目クリック＋journey smoke）＝メインセッション駆動

**Files:**
- Modify（必要時）: `tests/realgui/`（Y軸/X軸メニューの実メニュー項目クリックで zoom を実証する realgui を追加/更新）。
- Scratch（非コミット）: real-display 確認。

- [ ] **Step 1: 変更経路の realgui 対応付け**

`git diff --name-only main...HEAD -- src/valisync/gui/` で変更ファイル列挙。`grep -rl "build_axis_menu\|build_x_axis_menu\|axis_menu\|zoom" tests/realgui/` で軸メニュー realgui の有無を確認。メニュー項目追加（入力経路）ゆえ、Y軸/X軸ストリップの実右クリック→zoom 項目実クリック→レンジ縮小を実証する realgui を用意する（既存の軸メニュー realgui があれば拡張、無ければ新設）。実メニュー項目クリックは `QMenu.exec` ネストループ内で行い ESC watchdog を付ける（memory: gui_realgui_offscreen_target_opens_os_system_menu・FU-05/06 の実メニュー項目クリック方式を踏襲）。対象は共通 auto-fit レンジ内の交差線＋off-center hit にする。

- [ ] **Step 2: realgui（Y軸・X軸ズーム）＋既存軸メニュー無回帰＋journey smoke（実ディスプレイ）**

Run:
```bash
QT_QPA_PLATFORM=windows uv run pytest --realgui tests/realgui/test_journey_smoke.py -v
```
Y軸/X軸 zoom の新規/更新 realgui を実行（実右クリック→「ズームイン」実クリック→軸レンジが縮小することを VM 状態＋スクショで実証）。既存の軸メニュー/軸ジェスチャ realgui（掴み点・ゾーン）の無回帰も確認。

- [ ] **Step 3: headless full＋証拠集約＋ゲート判定**

Run: `uv run pytest`（0 errors）。
集約: headless full 結果・realgui pass/スクショ・contract 照合（Y軸ズーム=入力経路 realgui／X軸ズーム=入力経路 realgui／X-sync fan-out は同期 ON で全パネル連動＝実測or Layer A で担保／既存メニュー無回帰）。

---

## Self-Review

- **Spec coverage**: 倍率 10%（Task 1 `_scaled_range` in 0.9/out 1.1）・Y軸 zoom（Task 2 build_axis_menu）・X軸メニュー autofit/range/zoom（Task 2 build_x_axis_menu + _prompt_x_range + reset_x/set_x_range）・ZONE_X ルーティング（Task 2 contextMenuEvent）・X-sync fan-out 相乗り（Task 1 zoom_x→set_x_range）・gui-verify（Task 3）＝spec 全項目。
- **Placeholder scan**: 全 step に実コード/実コマンド。TBD/TODO なし。
- **Type consistency**: `_scaled_range(lo,hi,factor)->tuple|None`・`zoom_axis(axis_index,factor)`・`zoom_x(factor)`（Task 1）を Task 2 が `vm.zoom_axis(axis_index, 0.9/1.1)`・`vm.zoom_x(0.9/1.1)` で参照。`build_x_axis_menu()->QMenu`・`_prompt_x_range()->None`・`_default_range_dialog(axis_index=-1, ...)` センチネルで一貫。
- **YAGNI**: 倍率設定 UI・カーソル基準ズーム・X軸メニューの削除/曲線一覧は作らない。
