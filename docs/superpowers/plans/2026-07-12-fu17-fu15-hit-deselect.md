# FU-17（Sync X ヒット域）＋ FU-15（アクティブ Y 軸クロスエリア解除）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tier 1 の小 UX バグ2件を解消する — FU-17（「Sync X」チェックボックスの右余白 dead クリック域）と FU-15（アクティブ Y 軸を解除する手段がない → プロット外クリックで解除）。

**Architecture:** FU-17 はレイアウトの alignment 1行。FU-15 は centralized click-away protocol＝`GraphAreaView` が `QApplication` に `MouseButtonPress` イベントフィルタを設置し、押下がプロット subtree 外なら全パネルの `set_active_axis(None)`（＋パネル内の空プロット面クリックはローカル解除）。VM は不変（active axis は view-transient・core Qt 非依存維持）。

**Tech Stack:** PySide6（QCheckBox/QVBoxLayout・QApplication イベントフィルタ）、pytest-qt（Layer A/B）＋ realgui（Layer C）。

## Global Constraints

- **core は Qt 非依存**。active axis は view-transient（`GraphPanelView._active_axis_index`）で VM 非関与。`graph_panel_vm.py`/`graph_area_vm.py` は変更しない。
- **active panel（`GraphAreaVM.active_panel_index`・PC-07）は変更しない**。press での panel 活性化（`activate_requested.emit()`）は不変。
- **FU-15 の解除は単一 `GraphAreaView.clear_active_axis()` に集約**（将来 active 曲線等を同じ click-away 契約へ載せる拡張点）。
- **イベントフィルタは観測のみ**＝常に `return False`（イベント非消費）。`MouseButtonPress` 以外は即 `return False`（O(1) 型ゲート）。
- **押下対象が非 QWidget / 解決不能なら解除しない**（誤解除より安全側）。
- 品質ゲート（コミット前に全通過）: `uv run pytest`（該当 tests）／`uv run ruff check`／`uv run ruff format --check`／`uv run mypy src/`。
- コミットメッセージ末尾に必ず2行:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01E8wnw3K8drcSwF8gBQ2wUy`

## E2E 十分性（gui-test-plan・タスクへ織込済み）

- **ジャーニー**: 開く→信号をプロット→軸をアクティブ化→**別エリア（ChannelBrowser 等）や空プロット面をクリックしてアクティブ枠を外す**／「Sync X」の余白を誤クリックしても X 同期がトグルされない。
- **observable**: FU-17=ヒット域（`childAt`/checkbox 幅）が内容幅に固定（Layer B・決定的）。FU-15=クリック後に `_active_axis_index is None`（Layer B）＋**実 ChannelBrowser クリックでアクティブ枠が消える**（realgui・クロスウィジェット実配送＝headless は兄弟合成でしか触れない）。
- **prod スケール不要**（ヒット/選択のジオメトリはスケール非依存）。
- **ゾーン境界**: 本変更はゾーン寸法を動かさない（ヒットテスト/グリップ非改変）。FU-17 は checkbox 幅のみ縮小。realgui 掴み点の再監査は不要だが、FU-15 realgui で zone/掴み点への副作用がないこと（アクティブ枠クリア以外に描画変化なし）を無回帰確認。

## File Structure

- `src/valisync/gui/views/graph_area_view.py` — FU-17（`addWidget` alignment）／FU-15（`installEventFilter`＋`eventFilter`＋`clear_active_axis()`＋`removeEventFilter` on destroy）。
- `src/valisync/gui/views/graph_panel_view.py` — FU-15（`mousePressEvent` 空プロット分岐 `:1919` に `set_active_axis(None)`）。
- `tests/gui/test_graph_area_view.py` — FU-17 ヒット域・FU-15 フィルタ/クリア Layer B。
- `tests/gui/test_graph_panel_view.py` — FU-15 空プロット解除 Layer B。
- `tests/realgui/test_fu15_axis_deselect.py`（新規）— 実 ChannelBrowser クリックでアクティブ枠が消えるクロスウィジェット realgui。

---

### Task 1: FU-17 「Sync X」ヒット域を内容幅に固定

**Files:**
- Modify: `src/valisync/gui/views/graph_area_view.py:130-133`
- Test: `tests/gui/test_graph_area_view.py`

**Interfaces:**
- Consumes: 既存 `GraphAreaView.sync_checkbox`（`:104`）。
- Produces: なし（レイアウト挙動のみ）。

- [ ] **Step 1: 失敗テストを書く** — `tests/gui/test_graph_area_view.py` に追加（既存 `_make_area` ヘルパを使用）:

```python
class TestSyncCheckboxHitArea:
    def test_sync_checkbox_not_stretched_to_full_width(self, qtbot: QtBot) -> None:
        """FU-17: Sync X チェックボックスは内容幅に固定され、右余白が
        クリック判定に含まれない（全幅ストレッチしない）。"""
        from PySide6.QtWidgets import QCheckBox

        view = _make_area(qtbot)
        view.resize(900, 600)  # type: ignore[attr-defined]
        view.show()  # type: ignore[attr-defined]
        qtbot.waitExposed(view)  # type: ignore[arg-type]

        cb = view.sync_checkbox  # type: ignore[attr-defined]
        # 内容幅（sizeHint）近傍に固定＝全幅 900 まで伸びない。
        assert cb.width() <= cb.sizeHint().width() + 8, (
            f"checkbox stretched to {cb.width()} (sizeHint {cb.sizeHint().width()})"
        )
        # content 端よりはるか右の余白は checkbox 本体を返さない（dead margin 消失）。
        far_right = view.width() - 20  # type: ignore[attr-defined]
        hit = view.childAt(far_right, cb.y() + cb.height() // 2)  # type: ignore[attr-defined]
        assert not isinstance(hit, QCheckBox), "right margin still hits the checkbox"
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_area_view.py::TestSyncCheckboxHitArea -q`
Expected: FAIL（現状 alignment 未指定で checkbox が 900px 全幅・`cb.width()` が 900 近辺／`childAt(far_right)` が checkbox を返す）

- [ ] **Step 3: 最小実装** — `graph_area_view.py` の現 `layout.addWidget(self.sync_checkbox)`（`:132`）を左寄せ・stretch=0 に:

```python
        layout.addWidget(self.sync_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_graph_area_view.py::TestSyncCheckboxHitArea -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_view.py
git commit -m "fix(gui): FU-17 Sync X チェックボックスを内容幅に固定（右余白 dead クリック域を解消）"
```

---

### Task 2: FU-15a パネル内の空プロット面クリックでアクティブ軸を解除

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py:1919`
- Test: `tests/gui/test_graph_panel_view.py`

**Interfaces:**
- Consumes: 既存 `GraphPanelView.set_active_axis(index: int | None)`（`:1230`・None で解除・repaint・冪等）／`mousePressEvent`（`:1896`）の ZONE_PLOT no-curve 分岐（`:1919`）。
- Produces: なし（既存挙動の拡張）。

- [ ] **Step 1: 失敗テストを書く** — `tests/gui/test_graph_panel_view.py` に追加（既存の mount/クリック合成ヘルパに倣う。空プロット面 press をパネルの `mousePressEvent` に直接送るか、既存の ZONE_PLOT クリックテストと同じ経路を使う）:

```python
def test_empty_plot_click_deselects_active_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """FU-15: 曲線のない空プロット面をクリックするとアクティブ Y 軸が解除される
    (_active_axis_index -> None)。曲線活性化のクリアと同経路(:1919)に軸解除を追加。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    # _loaded_session/_make_view は既存ヘルパ(test_graph_panel_view.py 内)。
    session, _ = _loaded_session(tmp_path, n_signals=1)
    keys = sorted(_keys(session))
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])
    view = _make_view(qtbot, vm)
    view.resize(800, 600)
    view.show()
    qtbot.waitExposed(view)
    view.refresh()

    view.set_active_axis(0)
    assert view._active_axis_index == 0

    # 曲線のないプロット面の一点(データの外れ・ZONE_PLOT no-curve)を左クリック。
    # 既存の空プロットクリックが _deactivate_curve に届く経路と同じ座標系を使う。
    plot_rect = view._view_boxes[0].sceneBoundingRect()
    empty_pt = QPoint(int(plot_rect.center().x()), int(plot_rect.top()) + 3)
    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        empty_pt.toPointF() if hasattr(empty_pt, "toPointF") else empty_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.mousePressEvent(ev)

    assert view._active_axis_index is None, "空プロットクリックで軸が解除されていない"
```

> 注: テストの座標/イベント合成は既存の `test_graph_panel_view.py` の空プロット/ZONE_PLOT クリックテストのパターンに合わせて実装者が整合させる（`_curve_at` が None を返す空点を選ぶ・既存の zone 合成ヘルパがあれば流用）。要点は「空プロット press 後に `_active_axis_index is None`」。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_view.py::test_empty_plot_click_deselects_active_axis -q`
Expected: FAIL（現状 `:1919` は `_deactivate_curve()` のみ＝軸は 0 のまま）

- [ ] **Step 3: 最小実装** — `graph_panel_view.py` の空プロット分岐（現 `:1918-1919`）に軸解除を追加:

```python
                else:
                    self._deactivate_curve()  # empty-plot click -> deactivate
                    self.set_active_axis(None)  # FU-15: 空白クリックで軸選択も解除
```

- [ ] **Step 4: 通過を確認＋無回帰**

Run: `uv run pytest tests/gui/test_graph_panel_view.py -q`
Expected: PASS（新規＋既存の曲線活性化/zone クリック無回帰）

- [ ] **Step 5: コミット**

```bash
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_view.py
git commit -m "fix(gui): FU-15 空プロット面クリックでアクティブ Y 軸を解除（ローカル）"
```

---

### Task 3: FU-15b GraphAreaView の centralized click-away フィルタ（プロット外クリックで解除）

**Files:**
- Modify: `src/valisync/gui/views/graph_area_view.py`（`__init__`・新規 `eventFilter`/`clear_active_axis`・`destroyed` で removeEventFilter）
- Test: `tests/gui/test_graph_area_view.py`

**Interfaces:**
- Consumes: `self._panel_views`（`:101`＝`list[tuple[int, int, GraphPanelView]]`）／各 `GraphPanelView.set_active_axis(None)`（Task 2 で確認済み）。
- Produces: `GraphAreaView.clear_active_axis() -> None`（全パネル解除・FU-15 の単一解除点）／`GraphAreaView.eventFilter(obj, event) -> bool`。

- [ ] **Step 1: 失敗テストを書く** — `tests/gui/test_graph_area_view.py` に追加:

```python
class TestClickAwayDeselect:
    def _panels(self, view: object) -> list:
        return [w for _t, _p, w in view._panel_views]  # type: ignore[attr-defined]

    def test_press_outside_plot_subtree_clears_active_axis(self, qtbot: QtBot) -> None:
        """FU-15: プロット subtree 外のウィジェットへの MouseButtonPress で全パネルの
        アクティブ軸が解除される（clear_active_axis 経由）。"""
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication, QWidget

        view = _make_area(qtbot)
        panels = self._panels(view)
        assert panels, "no panel views"
        for p in panels:
            p.set_active_axis(0)
        assert any(p._active_axis_index == 0 for p in panels)

        # プロット subtree 外の兄弟ウィジェットへ press を配送。
        outsider = QWidget()
        qtbot.addWidget(outsider)
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPoint(1, 1).toPointF() if hasattr(QPoint(1, 1), "toPointF") else QPoint(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        # app フィルタ経路を駆動（GraphAreaView.eventFilter(outsider, ev)）。
        QApplication.instance().notify(outsider, ev)

        assert all(p._active_axis_index is None for p in panels), (
            "プロット外クリックで軸が解除されていない"
        )

    def test_press_inside_plot_subtree_does_not_clear(self, qtbot: QtBot) -> None:
        """誤解除ガード: subtree 内(パネル自身/子)への press では解除しない
        (パネル/軸/曲線の既存ハンドラがローカル処理する)。"""
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        view = _make_area(qtbot)
        panels = self._panels(view)
        panels[0].set_active_axis(0)

        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPoint(1, 1).toPointF() if hasattr(QPoint(1, 1), "toPointF") else QPoint(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        # subtree 内オブジェクト(パネル widget)への press。
        QApplication.instance().notify(panels[0], ev)

        assert panels[0]._active_axis_index == 0, "subtree 内 press で誤って解除された"

    def test_event_filter_is_observation_only(self, qtbot: QtBot) -> None:
        """フィルタはイベントを消費しない（常に False を返す）。"""
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QWidget

        view = _make_area(qtbot)
        outsider = QWidget()
        qtbot.addWidget(outsider)
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPoint(1, 1).toPointF() if hasattr(QPoint(1, 1), "toPointF") else QPoint(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        assert view.eventFilter(outsider, ev) is False  # type: ignore[attr-defined]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_area_view.py::TestClickAwayDeselect -q`
Expected: FAIL（`eventFilter`/`clear_active_axis` 未実装＝`AttributeError` か、フィルタ未設置で解除されない）

- [ ] **Step 3: 実装** — `graph_area_view.py`。

(a) imports に `QEvent`, `QObject`（QtCore）と `QApplication`（QtWidgets）を追加（既存 import 群へ）。

(b) `__init__` の既存 `unsubscribe`/`destroyed` 配線（`:135-139` 付近）の近くにフィルタ設置:

```python
        # FU-15: centralized click-away — プロット subtree 外の押下でアクティブ Y 軸を
        # 解除する。単一介入点なので新ドック/エリアはゼロ配線で対応。app にフィルタを
        # 設置し、破棄時に外す（QApplication は widget より長命ゆえ明示 remove が必要）。
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self.destroyed.connect(
                lambda *_: QApplication.instance()
                and QApplication.instance().removeEventFilter(self)
            )
```

(c) メソッド追加:

```python
    def clear_active_axis(self) -> None:
        """全パネルのアクティブ Y 軸(view-transient)を解除する。FU-15 の単一解除点。"""
        for _tab, _panel, widget in self._panel_views:
            if isinstance(widget, GraphPanelView):
                widget.set_active_axis(None)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """FU-15: プロット subtree 外の左押下でアクティブ軸を解除する(観測のみ)。

        MouseButtonPress 以外は即スルー。押下対象ウィジェットを解決し、self
        (GraphAreaView)自身またはその子孫でなければ subtree 外とみなし
        clear_active_axis()。押下対象が非 QWidget/解決不能なら誤解除を避けて何もしない。
        常に False を返しイベントを消費しない。
        """
        if event.type() == QEvent.Type.MouseButtonPress:
            # obj = イベント配送先。実クリックでは押下対象ウィジェット(その viewport)で
            # あり、合成テストでも notify(target, ev) の target になるため主経路に使う。
            # widgetAt は obj が非 QWidget のときの fallback(globalPos はここでのみ触る)。
            target = obj if isinstance(obj, QWidget) else None
            if target is None:
                target = QApplication.widgetAt(
                    event.globalPosition().toPoint()  # type: ignore[attr-defined]
                )
            if isinstance(target, QWidget) and not (
                target is self or self.isAncestorOf(target)
            ):
                self.clear_active_axis()
        return False
```

> 注: `obj` を主経路にすることで、実クリック（obj=押下ウィジェット）でも合成テスト（`notify(target, ev)` の target=obj）でも決定論的に対象が定まる。`widgetAt`/`globalPosition()` は obj が非 QWidget の稀ケースの fallback のみ（`MouseButtonPress` 分岐内でのみ触れる）。

- [ ] **Step 4: 通過を確認＋sabotage＋無回帰**

Run: `uv run pytest tests/gui/test_graph_area_view.py -q`
Expected: PASS（新規 3件＋既存 GraphAreaView 無回帰・特に `test_unsubscribes_when_destroyed` 系の破棄ライフサイクル）
sabotage: 一時的に ancestor 判定を反転（`not (...)` を外す）→ `test_press_inside_...` が RED になることを確認して戻す（報告に記録）。

- [ ] **Step 5: 全 headless GUI ＋ゲート**

Run: `uv run pytest tests/gui/ -q && uv run ruff check && uv run ruff format --check && uv run mypy src/`
Expected: 全 PASS

- [ ] **Step 6: コミット**

```bash
git add src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_view.py
git commit -m "fix(gui): FU-15 プロット外クリックでアクティブ Y 軸を解除（GraphAreaView centralized click-away フィルタ・単一解除点）"
```

---

### Task 4: FU-15 realgui ①ゲート（実 ChannelBrowser クリックで解除）

**Files:**
- Create: `tests/realgui/test_fu15_axis_deselect.py`

**Interfaces:**
- Consumes: 既存 realgui の MainWindow mount パターン（`tests/realgui/test_channel_browser_realclick.py` / `test_signal_dnd_realclick.py` を参照＝ChannelBrowser と GraphArea を同時に持つ MainWindow を実ディスプレイに mount するヘルパ）／`_realgui_input`（実 OS クリック）／`skip_unless_real_display`。

**分類**: 入力経路 E2E（クロスウィジェット実配送）。observable = アクティブ軸フレームの消失（`_active_axis_index` が None かつ実描画で枠が消える）。

- [ ] **Step 1: realgui テストを書く** — `tests/realgui/test_fu15_axis_deselect.py`。既存 MainWindow realgui テストの mount を踏襲し、(1) プロットに信号を1本置いて軸をアクティブ化（軸クリック or `set_active_axis(0)`）、(2) **実 OS クリックで ChannelBrowser の可視領域を左クリック**、(3) アクティブ軸が解除される（`_active_axis_index is None`）ことをアサート＋実描画スクショで枠消失を裏取り。合成入力の偽装をしない（memory [[gui_realgui_synthetic_click_mislabeled_layer_c]]）— 実 `_realgui_input` で ChannelBrowser の実座標をクリック。

```python
"""Layer C (realgui): FU-15 — 実 ChannelBrowser クリックでプロットのアクティブ Y 軸が
解除される(クロスウィジェット実配送)。headless では兄弟合成でしか触れない app フィルタ
経路を、実 OS クリック(ChannelBrowser の実座標)で裏取りする。"""

from __future__ import annotations

import pytest

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_channelbrowser_click_deselects_active_axis(qtbot) -> None:  # type: ignore[no-untyped-def]
    skip_unless_real_display()
    # 既存 MainWindow realgui mount(test_channel_browser_realclick.py 参照)で
    # ChannelBrowser + GraphArea を実ディスプレイに出し、信号を1本プロット、軸を
    # アクティブ化する。実装者は既存ヘルパの実在名に合わせる。
    ...
    # 1) 軸をアクティブ化して枠が出ている前提を確立
    #    (軸を実クリック or panel.set_active_axis(0) 後 refresh)
    # 2) ChannelBrowser の可視アイテム/空白の実座標を _realgui_input で実クリック
    # 3) 全パネルの _active_axis_index is None を assert + 実スクショ保存
```

> 実装者へ: fixture/ヘルパの実在名は `tests/realgui/test_channel_browser_realclick.py`・`tests/realgui/conftest.py`・`_realgui_input.py` を読んで合わせる。ブリーフのスケルトンの `...` は既存パターンで具体化する（存在しない名前を仮定しない）。実ディスプレイが無ければ `skip_unless_real_display` で skip。

- [ ] **Step 2: realgui 実行**

Run: `uv run pytest tests/realgui/test_fu15_axis_deselect.py --realgui -q`
Expected: PASS（実ディスプレイで実 ChannelBrowser クリック→軸解除）または skip（実ディスプレイ無し）。sabotage（app フィルタ未設置）で honest-RED（クリックしても軸が解除されない）を確認して報告。

- [ ] **Step 3: 収集確認＋契約ガード＋ゲート**

Run: `uv run pytest tests/realgui/test_fu15_axis_deselect.py --collect-only -q && uv run pytest tests/gui/test_realgui_layer_c_contract.py -q && uv run ruff check && uv run mypy src/`
Expected: 収集 OK・Layer C 契約ガード緑（実入力 or grabWindow を使う）・ruff/mypy clean

- [ ] **Step 4: コミット**

```bash
git add tests/realgui/test_fu15_axis_deselect.py
git commit -m "test(realgui): FU-15 実 ChannelBrowser クリックでアクティブ Y 軸が解除される(クロスウィジェット実配送)"
```

---

## Self-Review

**1. Spec coverage:**
- FU-17 ヒット域固定 → Task 1 ✓
- FU-15 空プロット解除 → Task 2 ✓
- FU-15 centralized click-away フィルタ＋単一 `clear_active_axis()` → Task 3 ✓
- FU-15 クロスウィジェット realgui（実 ChannelBrowser クリック）→ Task 4 ✓
- 負の契約（VM/active panel 不変・フィルタ観測のみ・誤解除しない安全側）→ Global Constraints＋Task 3（誤解除ガード test・sabotage）✓
- エッジ（subtree 内非解除・非 QWidget 非解除）→ Task 3 Step1/3 ✓

**2. Placeholder scan:** Task 4 の realgui スケルトンは `...` を含むが「既存 MainWindow realgui mount の実在名で具体化」と明示（realgui は実 fixture 依存ゆえ実装者が実在名合わせ）。他はプレースホルダなし。`QMouseEvent` の `toPointF` 分岐は PySide6 バージョン差の防御（実装者が環境に合わせて単純化可）。

**3. Type consistency:** `clear_active_axis() -> None`（Task 3 定義）／`set_active_axis(index: int | None)`（既存・Task 2/3 消費）／`eventFilter(obj: QObject, event: QEvent) -> bool`（Qt override シグネチャ）。`_panel_views: list[tuple[int,int,GraphPanelView]]`（既存・Task 3 で iterate）。

**4. 完了後メモリ/doc（プラン外・merge 後にユーザー確認）**: catalog の FU-17/FU-15 → ✅化。centralized click-away protocol は再利用価値ある知見（app イベントフィルタで subtree 外クリック検出＝将来 active 曲線等へ拡張）— memory 化を検討。
