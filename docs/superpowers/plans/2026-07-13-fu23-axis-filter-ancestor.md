# FU-23 axis filter ancestor-bubble fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: 実行は inline（executing-plans）。journey smoke は realgui（実ディスプレイ＋実マウス）で親が駆動・検証する。Steps use checkbox (`- [ ]`) syntax.

**Goal:** FU-15 の app フィルタが祖先バブル配送を「subtree 外」と誤判定して軸ジェスチャを全滅させる退行を、`eventFilter` の1条件（祖先除外）で解消し、honest-RED の journey smoke を常設ゲート化する。

**Architecture:** `GraphAreaView.eventFilter` の内側判定に `target.isAncestorOf(self)` 除外を追加（祖先へのバブル痕跡を click-away と誤認しない）。テストは Layer B（祖先非発火の regression-lock・headless）＋ Layer C journey smoke（実クリック活性化→実 grip ドラッグ→高さ変化・現 HEAD で RED）。

**Tech Stack:** PySide6・pyqtgraph・pytest・pytest-qt・realgui（Win32 実入力）。

## Global Constraints
（spec `docs/superpowers/specs/2026-07-13-fu23-axis-filter-ancestor-bubble-design.md`）
- `eventFilter` の1条件のみ変更。`clear_active_axis`・空プロット面解除・FU-15 click-away 意図・ゾーン幾何・VM は不変。
- グローバル介入変更＝両方向（発火＝正当な click-away は解除／非発火＝subtree 内・祖先バブルでは非解除）＋実 `MainWindow` 組立てハーネスが必須（更新後 gui-test-plan）。
- 「ジェスチャ完遂」= 活性化に続く操作がユーザー可視の効果を生むまで（活性化復帰では不足）。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- realgui 証拠は実 OS 入力＋スクショ（合成 `notify` は非発火側の end-to-end 証明にならない・1配送のみ）。

---

### Task 1: journey smoke（honest-RED・Layer C 常設ゲート）

**Files:**
- Create: `tests/realgui/test_journey_smoke.py`

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input`（`at`/`LDOWN`/`LUP`/`MOVE`/`to_phys`/`skip_unless_real_display`）・`MainWindow`・`AppViewModel`・実 grip 座標算出（`test_active_axis_resize.py` 準拠）。
- Produces: 基本ジャーニーの非発火側（活性化→ドラッグ完遂）を実 OS 入力で検証する常設スモーク。

- [ ] **Step 1: journey smoke を書く**

`tests/realgui/test_journey_smoke.py`:

```python
"""Layer C 常設ジャーニースモーク（gui-verify ゲート (e)）。

実 MainWindow＋実 OS 入力で基本ジャーニーを一気通貫し、グローバル介入
(app click-away フィルタ)下でも「軸クリック活性化に続くジェスチャが
ユーザー可視の効果を生む」ことを検証する。FU-23: 祖先バブル誤発火で
grip ドラッグが無効化される退行を捕まえる honest-RED。相互作用バグは
diff スコープ選定が構造的に取りこぼすため、機構盲目の無条件チェックで受ける。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, MOVE, at, skip_unless_real_display, to_phys

pytestmark = pytest.mark.realgui


def test_axis_activate_then_grip_resize_takes_effect(qtbot: QtBot, tmp_path: Path) -> None:
    """実クリックで軸を活性化 → 実 grip ドラッグで軸の高さが実際に変わる。

    現 HEAD（祖先バブル誤発火）では RED: 押下直後に clear_active_axis が
    誤発火して _active_axis_index=None に落ち、_begin_axis_drag が拒否 →
    高さ不変。FU-23 修正で GREEN。
    """
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    csv = tmp_path / "sig.csv"
    rows = ["t,speed"]
    for i in range(24):
        rows.append(f"{i * 0.1:.3f},{10.0 + i * 0.8:.4f}")
    csv.write_text("\n".join(rows) + "\n")
    fmt = FormatDefinition(
        name="smoke_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    outcome = window.app_vm.session.load(csv, fmt)
    window._on_loaded(outcome)  # 登録＋活性化＋ChannelBrowser 反映＋workbench 表示

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(
        screen.x() + 60, screen.y() + 60,
        min(1120, screen.width() - 120), min(760, screen.height() - 120),
    )
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    for _ in range(3):
        QApplication.processEvents()

    # 信号を最初のパネルに 2軸へプロット（2軸で grip 対象を作る）。
    model = window.channel_browser_view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=3000)
    signal_key = model.signal_key_at(model.index(0, 0))
    assert signal_key is not None
    for panel_vm in window.graph_area_vm.panels(0):
        panel_vm.add_signal(signal_key)
    for _ in range(3):
        QApplication.processEvents()

    panel = [w for _t, _p, w in window.graph_area_view._panel_views][0]
    qtbot.waitUntil(
        lambda: panel._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )

    R = panel._view_boxes[0].sceneBoundingRect()

    def strip_h(i: int) -> float:
        return panel._y_axes[i].sceneBoundingRect().height() / R.height()

    # --- 実クリックで軸0を活性化（純クリック：同一点 press→release, 移動なし）。
    spine0 = panel._y_axes[0].sceneBoundingRect()
    cx, cy = to_phys(panel, spine0.center().x(), spine0.center().y())
    at(cx, cy, LDOWN)
    time.sleep(0.05)
    at(cx, cy, LUP)
    for _ in range(4):
        QApplication.processEvents()
    assert panel._active_axis_index == 0, "実クリックで軸0が活性化しない"

    h0_before = strip_h(0)

    # --- 活性化に続く実 grip ドラッグ（軸0の下グリップを上へ→縮む）。小刻み均一ステップ。
    gx, gy = to_phys(panel, spine0.center().x(), spine0.bottom() - 2)
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    for k in range(1, 6):
        at(gx, gy - k * 12, MOVE)
        QApplication.processEvents()
        time.sleep(0.03)
    at(gx, gy - 60, LUP)
    for _ in range(4):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "smoke_resize.png"))

    h0_after = strip_h(0)
    assert h0_after < h0_before - 0.03, (
        "活性化に続く grip ドラッグが軸高さを変えない＝ジェスチャ未完遂"
        f"（before={h0_before:.3f} after={h0_after:.3f}・app フィルタ誤発火の疑い）。"
        f" screenshot: {tmp_path / 'smoke_resize.png'}"
    )
```

- [ ] **Step 2: 現 HEAD で RED を確認（honest-RED）**

Run: `uv run pytest --realgui tests/realgui/test_journey_smoke.py -v`
Expected: **FAIL**（`h0_after` が `h0_before` から縮まない＝実バグ再現）。スクショ添付。RED を確認できたら Task 3 の修正まで RED のまま。

- [ ] **Step 3: コミット（RED テストを記録）**

```bash
git add tests/realgui/test_journey_smoke.py
git commit -m "test(fu23): journey smoke（実クリック活性化→実 grip ドラッグ・現 HEAD で RED）"
```

---

### Task 2: Layer B 祖先非発火テスト（headless regression-lock）

**Files:**
- Modify: `tests/gui/test_graph_area_view.py`（`TestClickAwayDeselect` に追加）

**Interfaces:**
- Consumes: `_make_area(qtbot)`（standalone GraphAreaView を返す）。
- Produces: 祖先へのバブル配送で `clear_active_axis` しない regression-lock（案1 の非発火を headless で lock）。

- [ ] **Step 1: 祖先非発火テストを書く**

`tests/gui/test_graph_area_view.py` の `TestClickAwayDeselect` クラス内（`test_press_inside_plot_subtree_does_not_clear` の後）に追加:

```python
    def test_press_on_ancestor_bubble_does_not_clear(self, qtbot: QtBot) -> None:
        """FU-23: 実クリックは未 accept 時に GraphAreaView の祖先へバブルする。
        その祖先配送を click-away と誤認して解除してはならない(軸ジェスチャ全滅の真因)。
        """
        from PySide6.QtCore import QEvent, QPoint, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

        view = _make_area(qtbot)
        panels = self._panels(view)
        panels[0].set_active_axis(0)

        # GraphAreaView を container の子にして祖先関係を作る。
        container = QWidget()
        qtbot.addWidget(container)
        layout = QVBoxLayout(container)
        layout.addWidget(view)  # type: ignore[arg-type]
        assert container.isAncestorOf(view)  # type: ignore[arg-type]

        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPoint(1, 1).toPointF()
            if hasattr(QPoint(1, 1), "toPointF")
            else QPoint(1, 1),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        # 祖先(container)への配送＝バブル痕跡。解除してはならない。
        QApplication.instance().notify(container, ev)

        assert panels[0]._active_axis_index == 0, (
            "祖先へのバブル配送で誤って軸が解除された(FU-23 退行)"
        )
```

- [ ] **Step 2: RED を確認**

Run: `uv run pytest tests/gui/test_graph_area_view.py::TestClickAwayDeselect::test_press_on_ancestor_bubble_does_not_clear -v`
Expected: **FAIL**（現 `eventFilter` は container を「非 self・非子孫」として `clear_active_axis` → `_active_axis_index` が None）。

---

### Task 3: 修正（eventFilter に祖先除外）＋全 GREEN

**Files:**
- Modify: `src/valisync/gui/views/graph_area_view.py`（`eventFilter` の条件）

**Interfaces:**
- Consumes: Task 1（journey smoke）・Task 2（Layer B 祖先非発火）を GREEN 化。
- Produces: 祖先バブル配送を内側扱いにする1条件（`clear_active_axis`/click-away 意図は不変）。

- [ ] **Step 1: eventFilter に祖先除外を追加**

`src/valisync/gui/views/graph_area_view.py` の `eventFilter` の条件を変更:

```python
            if isinstance(target, QWidget) and not (
                target is self
                or self.isAncestorOf(target)
                or target.isAncestorOf(self)  # FU-23: 未 accept press の祖先バブル配送は click-away でない
            ):
                self.clear_active_axis()
```

併せて docstring の該当箇所に「祖先へバブルした同一物理イベントの配送は subtree 外でなく内側扱い（FU-23）」の1文を追記（WHY）。

- [ ] **Step 2: Layer B 祖先非発火が GREEN**

Run: `uv run pytest tests/gui/test_graph_area_view.py::TestClickAwayDeselect -v`
Expected: PASS（祖先非発火の新規＋既存 発火/subtree 内非発火/観測のみ 全て）。

- [ ] **Step 3: journey smoke が GREEN**

Run: `uv run pytest --realgui tests/realgui/test_journey_smoke.py -v`
Expected: PASS（活性化→grip ドラッグで軸高さが縮む）。スクショ添付。

- [ ] **Step 4: 品質ゲート＋コミット**

```bash
uv run pytest
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_view.py
git commit -m "fix(gui): FU-23 app フィルタの祖先バブル誤発火を解消（軸ジェスチャ復活）"
```

---

### Task 4: ①ゲート（更新後スキル）＋ catalog 折込

**Files:**
- Modify: `docs/audit-findings-catalog.md`（FU-23 登録）

- [ ] **Step 1: 軸 realgui クラスタ無回帰＋実組立て**

Run（該当のみ・実マウスを奪うので順次）:
`uv run pytest --realgui tests/realgui/test_journey_smoke.py tests/realgui/test_fu15_axis_deselect.py tests/realgui/test_click_activate_axis.py tests/realgui/test_active_axis_resize.py tests/realgui/test_active_axis_zoom_pan.py tests/realgui/test_active_panel_flow.py tests/realgui/test_cross_panel_axis_realclick.py -v`
Expected: 全 PASS（発火側 click-away・活性化・grip/zoom/pan・クロスパネル軸移動が無回帰）。

- [ ] **Step 2: headless full**

Run: `uv run pytest`
Expected: 0 errors。

- [ ] **Step 3: catalog に FU-23 登録＋コミット**

`docs/audit-findings-catalog.md` に FU-23 行（真因・修正・実測 honest-RED→GREEN・関連 FU-15）を追加。Tier 記述の該当箇所も更新。

```bash
git add docs/audit-findings-catalog.md
git commit -m "docs(fu23): 祖先バブル誤発火の解消を catalog 登録"
```

## Self-Review
- **Spec coverage**: 案1 祖先除外→Task 3・journey smoke honest-RED→Task 1・Layer B 祖先非発火→Task 2・無回帰クラスタ→Task 4・catalog→Task 4。✅
- **Placeholder scan**: `_build_window` 草案残骸は Step で削除と明記。他に TBD なし。✅
- **Type consistency**: `target.isAncestorOf(self)`・`_active_axis_index`・`strip_h`・`_y_axes[i].sceneBoundingRect()` は既存 API と一致。✅
