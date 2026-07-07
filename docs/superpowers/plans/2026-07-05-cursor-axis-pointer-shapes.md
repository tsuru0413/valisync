# カーソル UX 増分②（ポインタ形状 PC-22/PC-13/PC-14＋オフセット誤発火）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** X/Y 軸ゾーンとカーソル線に操作を示す差別化されたポインタ形状を与え、プロット領域の曲線オフセットドラッグにアフォーダンスを付ける。拡張可能なカーソルレジストリを土台にする。

**Architecture:** `gui/views/cursor_shapes.py`（新規）に `CursorKind` enum ＋ `cursor(kind)` 遅延キャッシュ ＋ カスタムズーム QCursor 生成を集約。`cursor_for_zone`/`_AlignedAxisItem.cursor_for_local` は純粋な `CursorKind` を返し、view/axis のホバーハンドラが `cursor(kind)` で解決して `setCursor` する。

**Tech Stack:** Python 3.12/3.13・PySide6 6.x（QCursor/QPixmap/QPainter）・pytest・pytest-qt。

## Global Constraints

- 品質ゲート（コミット前に全通過・pipe で exit code を隠さない）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- コメント/docstring は WHY。全角括弧/記号（（）＋−・⚠ 等）は半角化するか `# noqa: RUF00x`。
- QCursor/QPixmap 生成は QApplication 必須 → レジストリは**遅延生成**（初回 `cursor()` 呼び出し時）。モジュール import 時に生成しない。
- `cursor_for_zone`/`cursor_for_local` は**純粋関数**（`CursorKind` を返す・QApplication 不要）に保つ。QCursor 化は `cursor()` のみ。
- オフセットドラッグの**発火条件は変更しない**（アフォーダンス提示のみ）。
- オブジェクト同一性検証は `is`（`id()` 不使用）。

---

### Task 1: カーソルレジストリ `cursor_shapes.py`

**Files:**
- Create: `src/valisync/gui/views/cursor_shapes.py`
- Test: `tests/gui/test_cursor_shapes.py`

**Interfaces:**
- Produces:
  - `class CursorKind(enum.Enum)`: メンバ `ARROW, PAN_H, PAN_V, ZOOM_H, ZOOM_V, RESIZE_V, MOVE, ACTIVATE, DRAG_H`。
  - `cursor(kind: CursorKind) -> QCursor`（遅延キャッシュ・同一 kind は同一 QCursor）。

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_cursor_shapes.py
"""カーソルレジストリ: CursorKind -> QCursor 解決とキャッシュ（増分②）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.views.cursor_shapes import CursorKind, cursor


def test_standard_kinds_resolve_to_expected_shape(qtbot: QtBot):
    assert cursor(CursorKind.ARROW).shape() == Qt.CursorShape.ArrowCursor
    assert cursor(CursorKind.PAN_H).shape() == Qt.CursorShape.SizeHorCursor
    assert cursor(CursorKind.PAN_V).shape() == Qt.CursorShape.SizeVerCursor
    assert cursor(CursorKind.RESIZE_V).shape() == Qt.CursorShape.SizeVerCursor
    assert cursor(CursorKind.MOVE).shape() == Qt.CursorShape.SizeAllCursor
    assert cursor(CursorKind.ACTIVATE).shape() == Qt.CursorShape.PointingHandCursor
    assert cursor(CursorKind.DRAG_H).shape() == Qt.CursorShape.SizeHorCursor


def test_zoom_kinds_are_custom_bitmap_cursors(qtbot: QtBot):
    for k in (CursorKind.ZOOM_H, CursorKind.ZOOM_V):
        c = cursor(k)
        assert c.shape() == Qt.CursorShape.BitmapCursor
        assert not c.pixmap().isNull()  # 実 pixmap が描かれている


def test_same_kind_is_cached(qtbot: QtBot):
    assert cursor(CursorKind.ZOOM_H) is cursor(CursorKind.ZOOM_H)
    assert cursor(CursorKind.PAN_H) is cursor(CursorKind.PAN_H)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_cursor_shapes.py -q`
Expected: FAIL（`ModuleNotFoundError: valisync.gui.views.cursor_shapes`）

- [ ] **Step 3: Write minimal implementation**

```python
# src/valisync/gui/views/cursor_shapes.py
"""カーソルレジストリ: ゾーン判定が返す CursorKind を QCursor に解決する単一地点。

カスタムズームカーソル(QPixmap 描画)を遅延生成・キャッシュし、ゾーン判定側
(cursor_for_zone / cursor_for_local)は QApplication 非依存の純粋関数に保つ。
新カーソルは CursorKind に1つ足し、_STANDARD か _build_zoom_cursor に対応を追加するだけ。
"""

from __future__ import annotations

import enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap


class CursorKind(enum.Enum):
    ARROW = "arrow"
    PAN_H = "pan_h"
    PAN_V = "pan_v"
    ZOOM_H = "zoom_h"
    ZOOM_V = "zoom_v"
    RESIZE_V = "resize_v"
    MOVE = "move"
    ACTIVATE = "activate"
    DRAG_H = "drag_h"


_STANDARD: dict[CursorKind, Qt.CursorShape] = {
    CursorKind.ARROW: Qt.CursorShape.ArrowCursor,
    CursorKind.PAN_H: Qt.CursorShape.SizeHorCursor,
    CursorKind.PAN_V: Qt.CursorShape.SizeVerCursor,
    CursorKind.RESIZE_V: Qt.CursorShape.SizeVerCursor,
    CursorKind.MOVE: Qt.CursorShape.SizeAllCursor,
    CursorKind.ACTIVATE: Qt.CursorShape.PointingHandCursor,
    CursorKind.DRAG_H: Qt.CursorShape.SizeHorCursor,
}

_CACHE: dict[CursorKind, QCursor] = {}


def cursor(kind: CursorKind) -> QCursor:
    """Resolve a CursorKind to a cached QCursor (lazy; needs a running QApplication)."""
    c = _CACHE.get(kind)
    if c is not None:
        return c
    if kind in _STANDARD:
        c = QCursor(_STANDARD[kind])
    elif kind is CursorKind.ZOOM_H:
        c = _build_zoom_cursor(horizontal=True)
    elif kind is CursorKind.ZOOM_V:
        c = _build_zoom_cursor(horizontal=False)
    else:
        c = QCursor(Qt.CursorShape.ArrowCursor)  # defensive fallback
    _CACHE[kind] = c
    return c


def _build_zoom_cursor(horizontal: bool) -> QCursor:
    """Draw a two-end-bars + inward-arrows zoom cursor ([|->-<|] / vertical変種).

    白ハロー(太)＋黒線(細)の二重描画で明暗どちらの背景でも視認できる。垂直版は
    水平版を90度入れ替えた座標で描く。ホットスポットは中心。
    """
    size = 32
    c = size // 2  # center / hotspot
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    def draw(pen: QPen) -> None:
        p.setPen(pen)
        # 主軸に沿った座標: a=主軸(水平なら x)、b=副軸(水平なら y)
        near, far = 4, size - 4  # 端バー位置(主軸)
        b0, b1 = c - 8, c + 8  # 端バーの副軸方向の長さ
        arr_out, arr_in = c - 9, c - 2  # 左/上矢印: 外→内(主軸)
        head = 4  # 矢じりの長さ
        if horizontal:
            p.drawLine(near, b0, near, b1)  # 左バー
            p.drawLine(far, b0, far, b1)  # 右バー
            p.drawLine(arr_out, c, arr_in, c)  # 左矢印の軸(→)
            p.drawLine(arr_in, c, arr_in - head, c - head)  # 矢じり上
            p.drawLine(arr_in, c, arr_in - head, c + head)  # 矢じり下
            rx0, rx1 = size - arr_out, size - arr_in  # 右矢印(←) 反転
            p.drawLine(rx0, c, rx1, c)
            p.drawLine(rx1, c, rx1 + head, c - head)
            p.drawLine(rx1, c, rx1 + head, c + head)
        else:
            p.drawLine(b0, near, b1, near)  # 上バー
            p.drawLine(b0, far, b1, far)  # 下バー
            p.drawLine(c, arr_out, c, arr_in)  # 上矢印(↓)
            p.drawLine(c, arr_in, c - head, arr_in - head)
            p.drawLine(c, arr_in, c + head, arr_in - head)
            ry0, ry1 = size - arr_out, size - arr_in  # 下矢印(↑)
            p.drawLine(c, ry0, c, ry1)
            p.drawLine(c, ry1, c - head, ry1 + head)
            p.drawLine(c, ry1, c + head, ry1 + head)

    draw(QPen(QColor(255, 255, 255), 3))  # 白ハロー(太)
    draw(QPen(QColor(0, 0, 0), 1))  # 黒線(細)
    p.end()
    return QCursor(pm, c, c)  # hotspot at center
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gui/test_cursor_shapes.py -q`
Expected: PASS（3 テスト）

- [ ] **Step 5: Gate & commit**

```bash
uv run ruff check src/valisync/gui/views/cursor_shapes.py tests/gui/test_cursor_shapes.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/cursor_shapes.py tests/gui/test_cursor_shapes.py
uv run mypy src/valisync/gui/views/cursor_shapes.py
git add src/valisync/gui/views/cursor_shapes.py tests/gui/test_cursor_shapes.py
git commit -m "feat(gui): カーソルレジストリ CursorKind＋cursor() 遅延キャッシュ（カスタムズーム QCursor）"
```

---

### Task 2: PC-14 — `cursor_for_zone` を CursorKind 返却化（X zoom/pan 区別）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py:238-246`（`cursor_for_zone`）
- Test: `tests/gui/test_graph_panel_zoom.py:133-139`（更新）

**Interfaces:**
- Consumes: `CursorKind`（Task 1）。
- Produces: `cursor_for_zone(zone: str) -> CursorKind`（返り値型変更）。

- [ ] **Step 1: Update the failing test**

`tests/gui/test_graph_panel_zoom.py` の該当 import と assert を更新:

```python
# import 節（既存 cursor_for_zone import の近く）に追加
from valisync.gui.views.cursor_shapes import CursorKind
```

```python
# 旧 4 行（ZONE_X_INNER/OUTER == SizeHorCursor 等）を置換
assert cursor_for_zone(ZONE_X_INNER) == CursorKind.ZOOM_H
assert cursor_for_zone(ZONE_X_OUTER) == CursorKind.PAN_H
assert cursor_for_zone(ZONE_Y_INNER) == CursorKind.ARROW
assert cursor_for_zone(ZONE_Y_OUTER) == CursorKind.ARROW
assert cursor_for_zone(ZONE_PLOT) == CursorKind.ARROW
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_graph_panel_zoom.py -q -k cursor`
Expected: FAIL（現行は `Qt.CursorShape` を返すため `CursorKind` と不一致）

- [ ] **Step 3: Write minimal implementation**

`graph_panel_view.py` の import に `from valisync.gui.views.cursor_shapes import CursorKind, cursor` を追加（既存 view import の近く）。`cursor_for_zone` を置換:

```python
def cursor_for_zone(zone: str) -> CursorKind:
    """Map a zone to the hover cursor kind that hints its gesture (PC-14).

    X inner = range-select zoom (custom horizontal zoom bracket), X outer = pan
    (SizeHor). Y zones fall through to ARROW: _AlignedAxisItem owns the Y hover
    cursor, so the widget must not impose a competing cursor there.
    """
    if zone == ZONE_X_INNER:
        return CursorKind.ZOOM_H
    if zone == ZONE_X_OUTER:
        return CursorKind.PAN_H
    return CursorKind.ARROW
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gui/test_graph_panel_zoom.py -q -k cursor`
Expected: PASS

- [ ] **Step 5: Commit**（残りの呼び出し側は Task 5 で配線するため、ここでは純粋関数のみ確定）

```bash
uv run ruff check src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_zoom.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_zoom.py
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_zoom.py
git commit -m "feat(gui): cursor_for_zone を CursorKind 返却化（X inner=ZOOM_H/outer=PAN_H・PC-14）"
```

---

### Task 3: PC-13 — `cursor_for_local` を CursorKind 返却化＋Y 形状統一

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py:303-326`（`_AlignedAxisItem.cursor_for_local`）
- Test: `tests/gui/test_axis_interaction.py:258-276`（更新）

**Interfaces:**
- Consumes: `CursorKind`（Task 1）。
- Produces: `_AlignedAxisItem.cursor_for_local(lx, ly, h) -> CursorKind`（返り値型変更）。

- [ ] **Step 1: Update the failing test**

`tests/gui/test_axis_interaction.py` の import に `from valisync.gui.views.cursor_shapes import CursorKind` を追加し、mapping アサートを更新:

```python
assert it.cursor_for_local(30.0, 2.0, h) == CursorKind.RESIZE_V   # grip
assert it.cursor_for_local(2.0, 60.0, h) == CursorKind.MOVE       # frame
assert it.cursor_for_local(45.0, 60.0, h) == CursorKind.ZOOM_V    # zoom(内=右)
assert it.cursor_for_local(15.0, 60.0, h) == CursorKind.PAN_V     # pan(外=左)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_axis_interaction.py -q -k cursor_for_local`
Expected: FAIL（現行は Cross/OpenHand の `Qt.CursorShape`）

- [ ] **Step 3: Write minimal implementation**

`cursor_for_local` の戻り値辞書を `CursorKind` へ置換（シグネチャの戻り型も変更）:

```python
    def cursor_for_local(self, lx: float, ly: float, h: float) -> CursorKind:
        """Return the hover cursor kind for item-local point (lx, ly) on a spine of height h.

        Pure (h is passed explicitly) so it is headless-testable. Delegates zone
        classification to ``classify_axis_zone``; zoom/pan use the unified custom
        vertical bracket / SizeVer to match the X axis scheme (PC-13).
        """
        z = classify_axis_zone(
            lx,
            ly,
            self.width(),
            h,
            grip_w=self.GRIP_W,
            grip_h=self.GRIP_H,
            frame=self.FRAME,
            tol=self.TOL,
        )
        return {
            AXZONE_GRIP_TOP: CursorKind.RESIZE_V,
            AXZONE_GRIP_BOTTOM: CursorKind.RESIZE_V,
            AXZONE_FRAME: CursorKind.MOVE,
            AXZONE_ZOOM: CursorKind.ZOOM_V,
            AXZONE_PAN: CursorKind.PAN_V,
        }[z]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gui/test_axis_interaction.py -q -k cursor_for_local`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/valisync/gui/views/graph_panel_view.py tests/gui/test_axis_interaction.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/graph_panel_view.py tests/gui/test_axis_interaction.py
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_axis_interaction.py
git commit -m "feat(gui): cursor_for_local を CursorKind 返却化＋Y zoom/pan を垂直カスタム/SizeVer に統一（PC-13）"
```

---

### Task 4: PC-13 — `hoverMoveEvent` 活性化ゲート（非アクティブ軸=PointingHand）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py:339-357`（`_AlignedAxisItem.hoverMoveEvent`）
- Test: `tests/gui/test_axis_cursor_gate.py`（新規・Layer B）

**Interfaces:**
- Consumes: `cursor()`・`CursorKind`（Task 1）・`cursor_for_local`（Task 3）。
- Produces: なし（挙動変更のみ）。

- [ ] **Step 1: Write the failing test**

```python
# tests/gui/test_axis_cursor_gate.py
"""PC-13: Y 軸ホバーのカーソル — アクティブ軸=ゾーン別・非アクティブ軸=活性化ヒント。"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView


def _view(qtbot: QtBot, tmp_path: Path) -> GraphPanelView:
    csv_file = tmp_path / "d.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "s1"])
        for i in range(50):
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
    session.load(csv_file, fmt)
    vm = GraphPanelVM(session)
    vm.add_signal(session.signals()[0].name)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.resize(800, 500)
    return view


def _hover(axis, lx, ly):
    ev = MagicMock()
    ev.pos.return_value = type("P", (), {"x": lambda self: lx, "y": lambda self: ly})()
    axis.hoverMoveEvent(ev)


def test_non_active_axis_hover_shows_pointing_hand(qtbot: QtBot, tmp_path: Path) -> None:
    view = _view(qtbot, tmp_path)
    axis = view._y_axes[0]
    view._active_axis_index = None  # どの軸もアクティブでない
    _hover(axis, 15.0, 60.0)
    assert axis.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_active_axis_hover_shows_zone_cursor(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    view = _view(qtbot, tmp_path)
    axis = view._y_axes[0]
    view._active_axis_index = axis._vm_axis_index  # この軸をアクティブに
    # ゲート挙動に集中(boundingRect 高さ依存の zone 判定を避ける): cursor_for_local を固定
    from valisync.gui.views.cursor_shapes import CursorKind

    monkeypatch.setattr(axis, "cursor_for_local", lambda lx, ly, h: CursorKind.PAN_V)
    _hover(axis, 15.0, 60.0)
    assert axis.cursor().shape() == Qt.CursorShape.SizeVerCursor
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_axis_cursor_gate.py -q`
Expected: FAIL（非アクティブは `unsetCursor` で ArrowCursor のまま → PointingHand 不一致）

- [ ] **Step 3: Write minimal implementation**

`hoverMoveEvent` の cursor 適用部を置換（`cursor()` 解決＋非アクティブは ACTIVATE）:

```python
        view.set_hover_axis(self._vm_axis_index)
        if self._vm_axis_index == view._active_axis_index:
            p = ev.pos()
            self.setCursor(
                cursor(self.cursor_for_local(p.x(), p.y(), self.boundingRect().height()))
            )
        else:
            # 非アクティブ軸: 「クリックで活性化」を示す(操作は活性化必須・PC-13)。
            self.setCursor(cursor(CursorKind.ACTIVATE))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/gui/test_axis_cursor_gate.py -q`
Expected: PASS（2 テスト）

- [ ] **Step 5: Commit**

```bash
uv run ruff check src/valisync/gui/views/graph_panel_view.py tests/gui/test_axis_cursor_gate.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/graph_panel_view.py tests/gui/test_axis_cursor_gate.py
uv run mypy src/valisync/gui/views/graph_panel_view.py
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_axis_cursor_gate.py
git commit -m "feat(gui): 非アクティブ Y 軸ホバーは PointingHand で活性化を示す（PC-13 ゲート緩和）"
```

---

### Task 5: PC-22＋オフセットアフォーダンス＋X ホバー配線（`_hover_cursor`・`_make_cursor_line`）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`（`_make_cursor_line:1116-1128`・`eventFilter:1639`・`mouseMoveEvent:1648`・`_hover_cursor` 新設）
- Test: `tests/gui/test_x_hover_cursor.py`（更新）＋ `tests/gui/test_plot_offset_cursor.py`（新規）

**Interfaces:**
- Consumes: `cursor()`・`CursorKind`・`cursor_for_zone`（Task 2）・`self._zone_at`・`self._curve_at`。
- Produces: `GraphPanelView._hover_cursor(pos: QPointF) -> CursorKind`。

- [ ] **Step 1: Write the failing test（オフセットアフォーダンス＋カーソル線）**

```python
# tests/gui/test_plot_offset_cursor.py
"""PC-22＋オフセット誤発火: カーソル線=SizeHor、プロット曲線上ホバー=SizeHor(ドラッグ可)。"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.cursor_shapes import CursorKind
from valisync.gui.views.graph_panel_view import GraphPanelView


def _view(qtbot: QtBot, tmp_path: Path) -> GraphPanelView:
    csv_file = tmp_path / "d.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "s1"])
        for i in range(50):
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
    session.load(csv_file, fmt)
    vm = GraphPanelVM(session)
    vm.add_signal(session.signals()[0].name)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.resize(800, 500)
    return view


def test_cursor_line_has_sizehor_cursor(qtbot: QtBot, tmp_path: Path) -> None:
    view = _view(qtbot, tmp_path)
    assert view._cursor_line.cursor().shape() == Qt.CursorShape.SizeHorCursor
    assert view._cursor_line_b.cursor().shape() == Qt.CursorShape.SizeHorCursor


def test_hover_cursor_over_curve_is_drag_h(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    view = _view(qtbot, tmp_path)
    # プロット領域内の点で _curve_at が命中する状況を固定
    monkeypatch.setattr(view, "_zone_at", lambda pos: "plot")
    monkeypatch.setattr(view, "_curve_at", lambda pos: "csv_1::s1")
    assert view._hover_cursor(QPointF(100.0, 100.0)) == CursorKind.DRAG_H


def test_hover_cursor_over_empty_plot_is_arrow(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    view = _view(qtbot, tmp_path)
    monkeypatch.setattr(view, "_zone_at", lambda pos: "plot")
    monkeypatch.setattr(view, "_curve_at", lambda pos: None)
    assert view._hover_cursor(QPointF(100.0, 100.0)) == CursorKind.ARROW
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/gui/test_plot_offset_cursor.py -q`
Expected: FAIL（`_hover_cursor` 未定義・カーソル線に setCursor 無し）

- [ ] **Step 3: Write minimal implementation**

(a) `_make_cursor_line` の生成直後（return 前）に setCursor を追加。まず該当箇所を確認して `line` を返す直前へ:

```python
        line.setCursor(cursor(CursorKind.DRAG_H))
```

(b) `_hover_cursor` を view に新設（`mousePressEvent` の近く・`_zone_at` 定義後）:

```python
    def _hover_cursor(self, pos: QPointF) -> CursorKind:
        """Hover cursor kind for a panel-local point.

        Plot area over an offset-draggable curve -> DRAG_H (SizeHor) so the
        offset gesture is discoverable and not a surprise; otherwise the X-zone
        cursor. Y zones are owned by _AlignedAxisItem (ARROW here).
        """
        zone = self._zone_at(pos)
        if zone == ZONE_PLOT and self._curve_at(pos) is not None:
            return CursorKind.DRAG_H
        return cursor_for_zone(zone)
```

(c) `eventFilter` のカーソル適用行を `_hover_cursor` 経由に:

```python
            self.setCursor(cursor(self._hover_cursor(QPointF(pos_in_panel))))
```

(d) `mouseMoveEvent` の `_drag_zone is None` 分岐のカーソル適用行を:

```python
            self.setCursor(cursor(self._hover_cursor(event.position())))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/gui/test_plot_offset_cursor.py -q`
Expected: PASS（3 テスト）

- [ ] **Step 5: Update X hover regression test**

`tests/gui/test_x_hover_cursor.py` は `view.cursor().shape()` を検証しており QCursor 経由でも動くが、X inner が **BitmapCursor**（カスタムズーム）になった点を反映。inner をホバーする既存アサートがあれば:

```python
# X inner(zoom) は BitmapCursor、X outer(pan)/plot away は従来 shape
# 既存アサートの該当行を確認し、inner の期待を更新:
assert view.cursor().shape() == Qt.CursorShape.BitmapCursor  # X inner=zoom
```
plot 領域を曲線から離れた点でホバーするテストは Arrow のまま（曲線非命中）。ホバー点が曲線に近い場合は SizeHor になるため、テストのホバー座標が曲線から `CURVE_HIT_TOL_PX` 超離れていることを確認（必要なら y を端に寄せる）。

Run: `uv run pytest tests/gui/test_x_hover_cursor.py -q`
Expected: PASS

- [ ] **Step 6: Gate & commit**

```bash
uv run ruff check src/valisync/gui/views/graph_panel_view.py tests/gui/test_plot_offset_cursor.py tests/gui/test_x_hover_cursor.py; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/graph_panel_view.py tests/gui/test_plot_offset_cursor.py tests/gui/test_x_hover_cursor.py
uv run mypy src/valisync/gui/views/graph_panel_view.py
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_plot_offset_cursor.py tests/gui/test_x_hover_cursor.py
git commit -m "feat(gui): カーソル線=SizeHor＋プロット曲線ホバーにオフセットドラッグ可アフォーダンス＋X ホバー配線（PC-22/誤発火）"
```

---

### Task 6: realgui（任意実行）＋docs 更新＋全ゲート

**Files:**
- Create: `tests/realgui/test_axis_cursor_shapes.py`（realgui・ローカル `--realgui` のみ）
- Modify: `docs/audit-findings-catalog.md`（PC-22/PC-13/PC-14 ✅解消）・`docs/roadmap.md`・`docs/structure.md`（`cursor_shapes.py` 追記）

**Interfaces:** なし。

- [ ] **Step 1: realgui スケルトン（実 OS ホバーでカーソル形状確認）**

`tests/realgui/` の既存ヘルパ規約に合わせ、実ウィンドウを `QT_QPA_PLATFORM=windows` で表示し、X inner/outer・Y 非アクティブ・カーソル線にカーソルを小刻みスイープで移動して `widget.cursor().shape()`（または実 OS カーソル）を検証するスケルトンを作成。realgui は既存 `tests/realgui/conftest.py` の `--realgui` gate に従い、未指定時は skip。

（既存 realgui テストの1本を雛形にし、`memory: gui_realgui_hover_needs_incremental_move` に従いカーソルは対象アイテム上を小刻みスイープ＋リトライで設定する。）

- [ ] **Step 2: catalog 解消注記**

`docs/audit-findings-catalog.md` の PC-22/PC-13/PC-14 行頭に「✅解消（2026-07-05・増分②・PR #<n>）: カーソルレジストリ（CursorKind＋cursor()）＋X zoom/pan 区別・Y 統一・非アクティブ軸 PointingHand・カーソル線 SizeHor・プロット曲線オフセットアフォーダンス」を追記。

- [ ] **Step 3: roadmap 更新**

`docs/roadmap.md` の `gui-plot-analysis-controls` 行の「PC-13/14/22 軸/カーソル形状は増分②（別 spec 予定）」を「✅解消（増分②）」へ更新。

- [ ] **Step 4: structure 更新**

`docs/structure.md` の `gui/views/` に `cursor_shapes.py`（カーソルレジストリ・CursorKind→QCursor）を1行追記。

- [ ] **Step 5: 全ゲート**

```bash
uv run pytest -q; echo "pytest exit: ${PIPESTATUS[0]}"
uv run ruff check; echo "check exit: ${PIPESTATUS[0]}"
uv run ruff format --check; echo "format exit: ${PIPESTATUS[0]}"
uv run mypy src/
```
Expected: 全 PASS（realgui は `--realgui` 無しで skip）。

- [ ] **Step 6: Commit**

```bash
git add docs/audit-findings-catalog.md docs/roadmap.md docs/structure.md tests/realgui/test_axis_cursor_shapes.py
git commit -m "docs＋realgui: カーソル UX 増分②（PC-22/PC-13/PC-14）解消を反映＋realgui スケルトン"
```

---

## Self-Review

**1. Spec coverage:**
- §2 カーソルレジストリ → Task 1。✓
- §3 PC-14（X cursor_for_zone）→ Task 2。✓
- §4 PC-13（Y cursor_for_local 統一）→ Task 3、活性化ゲート → Task 4。✓
- §5 PC-22（カーソル線 setCursor）→ Task 5。✓
- §6 オフセットアフォーダンス（_hover_cursor）→ Task 5。✓
- §9 テスト（Layer A レジストリ／Layer B ゲート・アフォーダンス／Layer C realgui／無回帰）→ Task 1/4/5/6。✓
- §10 ファイル構成 → Task 1（新規 cursor_shapes.py＋test）・Task 2-5 変更・Task 6 docs/realgui。✓

**2. Placeholder scan:** 各コード step は完全コード掲載。Task 6 Step 1 の realgui は「既存 realgui 雛形に合わせて作成」と手順を具体化（既存規約参照）。TBD/TODO なし。

**3. Type consistency:** `CursorKind`（Task 1）を Task 2/3/4/5 が一貫使用。`cursor_for_zone(zone) -> CursorKind`（Task 2）・`cursor_for_local(...) -> CursorKind`（Task 3）・`cursor(kind) -> QCursor`（Task 1）・`_hover_cursor(pos) -> CursorKind`（Task 5）整合。`hoverMoveEvent`（Task 4）は `cursor(cursor_for_local(...))`／`cursor(CursorKind.ACTIVATE)`。

## 非ゴール
オフセット発火条件の変更（アフォーダンスのみ）・PC-03 別解決・テーマ連動配色。
