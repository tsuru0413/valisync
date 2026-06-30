# realgui click_to_activate_axis Implementation Plan (Phase 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 非アクティブな Y 軸スパイン上の**実 OS 純クリック**（press+release・移動なし＝ドラッグ閾値未満）が pyqtgraph の click/drag 判別を経て `_AlignedAxisItem.mouseClickEvent`→`set_active_axis` を発火させ、当該軸がアクティブ化（`_active_axis_index` 更新＋アンバーフレーム）し、**後続の実グリップドラッグが当該軸に効く**ことを realgui で検証する。

**Architecture:** 全軸操作モデルの唯一の入口（実クリックでの活性化）は既存 realgui 4本が `view.set_active_axis(0)` 直叩きで前提化＝実入力で未検証。本プランは**実 OS 純クリックでの活性化**を realgui で証明する（production 配線は既存で、Layer B 合成 scene dispatch では `test_axis_interaction.py` が確認済みだが、実 OS の click/drag 判別＝閾値未満で drag でなく click と分類される経路は実入力でのみ証明可能）。production 変更は無し（honest RED は活性化呼びの一時 neuter で実証）。

**Tech Stack:** PySide6 / pyqtgraph / pytest / pytest-qt / ctypes(Win32)。共有 realgui 入力ヘルパ `tests/realgui/_realgui_input.py`（`at`/`LDOWN`/`MOVE`/`LUP`/`to_phys`/`skip_unless_real_display`）。

## Global Constraints

- 設計 spec: `docs/superpowers/specs/2026-06-30-realgui-coverage-expansion-design.md`（§クラス3 = lines 58-63）。一次根拠: `docs/realgui-coverage-audit.md`（H8）。
- **MVVM**: viewmodels に Qt/pyqtgraph を import しない。本プランは tests のみ追加（production 変更なし）。
- **純クリック技法**: `at(x,y,LDOWN)` → `at(x,y,LUP)` を**同一物理点**で（間に MOVE を入れない）。pyqtgraph は `_moveDistance=5` scene px / `minDragTime=0.5s` で click/drag 判別（GraphicsScene）。移動 0 → `mouseClickEvent`（`mouseDragEvent` でない）。
- **honest 検証の核**: `mouseDragEvent`→`_begin_axis_drag`（graph_panel_view.py:476）は `_vm_axis_index != _active_axis_index` のとき False＝**非アクティブ軸へのドラッグは拒否**。よって「クリックで活性化→当該軸のグリップドラッグが height_ratio を変える」が活性化の behavioral 証明。honest RED は `mouseClickEvent` の `set_active_axis` 呼び（graph_panel_view.py:437）を一時 neuter→活性化せず両テスト RED（コントローラ①ゲートで実 win32 実証）。
- realgui(Layer C) は `@pytest.mark.realgui`＋`--realgui` opt-in、配置 `tests/realgui/`。実装サブエージェントは headless のため `--realgui` を実行しない（収集＋フルゲートまで）。
- コミットメッセージ末尾に必須トレーラ（`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k`）。
- コミット前ゲート: `uv run pytest`（headless 0 errors）/ `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。worktree なら先に `uv sync --extra dev`。

## File Structure

- Create: `tests/realgui/test_click_activate_axis.py` — 実 OS 純クリックでの軸活性化 realgui（活性化状態＋後続グリップ）。

**参照（不変・読むだけ）**: `tests/realgui/test_active_axis_resize.py`（make_two_axis_panel 構築＋spine/grip 物理座標＋グリップドラッグの正準パターン lines 24-90）、`tests/realgui/_realgui_input.py`（at/LDOWN/MOVE/LUP/to_phys/skip_unless_real_display）。検証済みアンカー: `_AlignedAxisItem.mouseClickEvent`=graph_panel_view.py:422-438（437行で set_active_axis 呼び）、`set_active_axis`=1044-1056（`_active_axis_index` 設定＋全軸 update）、`_begin_axis_drag` 非アクティブ拒否=476、`_active_axis_index` 初期 None=653、`make_two_axis_panel`=tests/gui/_panel_factory.py:52。

---

### Task 1: 実 OS 純クリックでの軸活性化 realgui（状態＋後続グリップ）

**Files:**
- Create: `tests/realgui/test_click_activate_axis.py`

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input.py` の `at, LDOWN, MOVE, LUP, to_phys, skip_unless_real_display`。`tests/gui/_panel_factory.make_two_axis_panel`（既存 realgui と同じ構築）。

**背景**: `make_two_axis_panel()` は 2 軸（各 ~0.5 高）の GraphPanelView を返す。`_active_axis_index` 初期 None。テストはまず `set_active_axis(0)`（軸0 アクティブ＝軸1 非アクティブ）にしてから、軸1 スパインを実純クリック→活性化が **0→1 に切り替わる**ことを証明する。スパイン中央は任意点で活性化（mouseClickEvent はゾーン制限なし）。

- [ ] **Step 1: realgui テストを作成**

`tests/realgui/test_click_activate_axis.py`:

```python
"""Layer C: a real OS pure-click on a non-active axis spine activates that axis.

Opt-in — run with ``--realgui`` on Windows + a real display. The whole active-axis
gesture model has one entry point — clicking an axis spine to activate it — that the
existing realgui suite bypasses by calling view.set_active_axis(0) directly. This test
drives a genuine left press+release (no movement → below pyqtgraph's drag threshold →
mouseClickEvent, not mouseDragEvent) on a non-active spine and asserts it activates
(via _AlignedAxisItem.mouseClickEvent → set_active_axis) and that a subsequent real
grip drag then acts on the now-active axis. See docs/gui-testing-layers.md (Layer C).
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    MOVE,
    at,
    skip_unless_real_display,
    to_phys,
)

pytestmark = pytest.mark.realgui


def _show_two_axis_panel(qtbot: QtBot):
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    qtbot.addWidget(view)
    from PySide6.QtCore import Qt

    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(300, 300, 800, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return view


def _spine_center_phys(view, axis_index: int) -> tuple[int, int]:
    spine = view._y_axes[axis_index].sceneBoundingRect()
    return to_phys(view, spine.center().x(), spine.center().y())


def test_real_click_activates_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """Pure click on axis 1's spine switches the active axis 0 → 1."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _show_two_axis_panel(qtbot)
    view.set_active_axis(0)  # start with axis 0 active so the click must SWITCH to 1
    QApplication.processEvents()
    assert view._active_axis_index == 0

    cx, cy = _spine_center_phys(view, 1)
    at(cx, cy, LDOWN)
    time.sleep(0.05)
    at(cx, cy, LUP)  # same point, no MOVE → pure click → mouseClickEvent
    for _ in range(4):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "activate.png"))

    assert view._active_axis_index == 1, (
        "real click on axis 1 spine did not activate it "
        f"(got {view._active_axis_index}). screenshot: {tmp_path / 'activate.png'}"
    )


def test_click_activation_enables_grip_resize(qtbot: QtBot, tmp_path: Path) -> None:
    """After a real click activates axis 1, a real grip drag resizes axis 1 —
    impossible unless the click activated it (_begin_axis_drag rejects non-active)."""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _show_two_axis_panel(qtbot)
    view.set_active_axis(0)  # axis 1 is NOT active
    QApplication.processEvents()

    R = view._view_boxes[0].sceneBoundingRect()

    def strip_h(i: int) -> float:
        return view._y_axes[i].sceneBoundingRect().height() / R.height()

    h1_before = strip_h(1)

    # Pure click on axis 1 spine → activate it.
    cx, cy = _spine_center_phys(view, 1)
    at(cx, cy, LDOWN)
    time.sleep(0.05)
    at(cx, cy, LUP)
    for _ in range(4):
        QApplication.processEvents()
    assert view._active_axis_index == 1, "click did not activate axis 1"

    # Subsequent real grip drag: axis 1's TOP grip dragged DOWN shrinks axis 1
    # (model B: neighbour untouched, gap absorbs). Small uniform steps keep the
    # first threshold crossing inside the grip band (see test_active_axis_resize).
    spine1 = view._y_axes[1].sceneBoundingRect()
    gx, gy = to_phys(view, spine1.center().x(), spine1.top() + 2)
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    for k in range(1, 6):  # drag DOWN ~60px
        at(gx, gy + k * 12, MOVE)
        QApplication.processEvents()
        time.sleep(0.03)
    at(gx, gy + 60, LUP)
    for _ in range(4):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "resize.png"))

    h1_after = strip_h(1)
    assert h1_after < h1_before - 0.03, (
        "axis 1 did not shrink — click-activation did not enable the grip gesture "
        f"(before={h1_before:.3f} after={h1_after:.3f}). screenshot: {tmp_path / 'resize.png'}"
    )
```

- [ ] **Step 2: ヘッドレス収集を確認**

Run: `uv run pytest tests/realgui/test_click_activate_axis.py --collect-only -q`
Expected: 2 tests collected・import エラー無し（実行すれば offscreen で skip）。

注意: `make_two_axis_panel` / `view._y_axes` / `view._view_boxes` / `view._active_axis_index` / `set_active_axis` は既存 realgui（test_active_axis_resize.py）が使う実 API。差異があれば実コードに合わせ調整（realgui は headless skip ゆえ collection で属性誤りを検出できない＝READ で確認）。

- [ ] **Step 3: フルゲート**

Run: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`
Expected: headless 全 pass・0 errors（新 realgui は skip）、lint/format/type クリーン。

- [ ] **Step 4: Commit**

```bash
git add tests/realgui/test_click_activate_axis.py
git commit -m "test(realgui): 実 OS 純クリックでの軸活性化＋後続グリップ（H8）"
```

---

## コントローラ ①ゲート（実 win32・honest RED→GREEN）

実装完了後、コントローラが `/gui-verify` を実 win32 実行。**カーソル占有のためユーザーに席を外す確認を取る**。純クリック→グリップは drive_qdrag を使わない手動 at() のため、外部 watchdog 付きで実行（万一の停滞に備え）。

1. **GREEN**: `uv run pytest --realgui tests/realgui/test_click_activate_axis.py -v` → 2 件 pass・ハング無し。証拠ログ＋スクショ（activate.png/resize.png）。
2. **honest RED**: `graph_panel_view.py:437` の `self._panel_view.set_active_axis(self._vm_axis_index)` を一時 neuter（`pass  # REDPROOF`）→ 2 件とも RED（活性化せず `_active_axis_index` 不変／後続グリップも非アクティブ拒否で height_ratio 不変）を確認 → `git checkout` 復元。
3. **全 realgui 無回帰**: `uv run pytest --realgui tests/realgui/ -v` → Phase 1/2/3 の 20 件＋本 Phase 2 件＝**22 件 pass・ハング無し**。

ゲート判定: (a) headless full 0 errors (b) realgui 証拠（GREEN＋RED） (c) CI 緑。3点充足で finishing（push + PR）。

---

## Self-Review

**1. Spec coverage（§クラス3 / H8）**: test_real_click_activates_axis＝「非アクティブ軸スパイン純クリック→set_active_axis」、test_click_activation_enables_grip_resize＝「後続実ジェスチャ（グリップ）が当該軸に効く」。アンバーフレームは `_active_axis_index==1` の決定的帰結（paint が参照）＝状態 assert で担保（スクショは /verify 観測）。honest RED＝437 neuter。✔

**2. Placeholder scan**: realgui 全文記載。`make_two_axis_panel`/`_y_axes`/`set_active_axis` は既存 realgui の実 API（調整余地は注記）。✔

**3. Type 整合**: `at(x,y,flag)` / `to_phys(view,sx,sy)` / `view._active_axis_index: int|None` 一貫。純クリック=同点 LDOWN→LUP（move なし）。グリップは既存 test_active_axis_resize の 12px ステップパターン流用。✔

**4. リスク**: (a) 純クリックが本当に mouseClickEvent になるか＝move なしで distance 0<5px ゆえ click 確定（調査で GraphsScene ロジック確認済み）。(b) スパインへのクリックが他 scene item に横取りされないか＝既存グリップ/ズーム realgui が同スパインで mouseDragEvent 到達済み＝press は AxisItem に届く（実機ゲートで最終確認）。(c) 活性化と後続グリップの間に refresh が走ると `_active_axis_index` リセットの恐れ→テストは間に refresh を起こさない（注記）。✔
