"""Layer C: Global_Cursor を実 OS 入力で検証(R15/R16)。--realgui で実行。

新規経路(前例なし): InfiniteLine 実ドラッグ(A 線単独・B 線2線ヒット分離)。
再利用: tests/gui/_panel_factory.make_two_axis_panel、test_active_axis_zoom_pan.py 同形の _to_phys/_at。
"""

from __future__ import annotations

import contextlib
import time

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    MOVE,
    at,
    skip_unless_real_display,
    to_phys,
)

pytestmark = pytest.mark.realgui


def _shown_panel(qtbot: QtBot):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    qtbot.addWidget(view)
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


def _scene_center(view) -> tuple[float, float, float]:
    """(scene_x, scene_y, expected_data_x) at the plot's horizontal centre."""
    from PySide6.QtCore import QPointF

    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    sx = rect.x() + rect.width() * 0.5
    sy = rect.y() + rect.height() * 0.5
    return sx, sy, vb.mapSceneToView(QPointF(sx, sy)).x()


def _x_span(view) -> float:
    rng = view.vm.x_range
    return abs(rng[1] - rng[0]) if rng else 1.0


def test_real_drag_cursor_line_moves_it(qtbot: QtBot, tmp_path) -> None:
    """A 線をトグルで設置→線を右へ実ドラッグ → 描画 x(line.value)が増加(②: 実ドラッグ結果)。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    # 設置はトグル経由(空クリック設置は撤去済み)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible()
    x_before = view.cursor_line_value()
    # A 線の現在位置を起点に右へ実ドラッグ(線上を掴む)
    sx, sy, _ = _scene_center(view)

    rect = view._view_boxes[0].sceneBoundingRect()
    target_sx = rect.x() + rect.width() * 0.75
    gx, gy = to_phys(view, sx, sy)
    tx, _ = to_phys(view, target_sx, sy)
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        at(gx + (tx - gx) * k // steps, gy, MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    at(tx, gy, LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "cursor_dragged.png")
        )
    assert view.cursor_line_value() > x_before


def test_real_drag_sub_cursor_moves_only_b(qtbot: QtBot, tmp_path) -> None:
    """main+delta 表示 → B 線(75%)を実ドラッグ → B が動き A は不変(②: 実ヒットテスト)。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)  # A=50%
    view.vm.toggle_delta(True)  # B=75%
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible() and view.delta_line_visible()
    a_before = view.cursor_line_value()
    b_before = view.delta_line_value()

    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    # B(75%)の画面位置を起点に、さらに右(85%)へ実ドラッグ
    b_scene_x = rect.x() + rect.width() * 0.75
    sy = rect.y() + rect.height() * 0.5
    tgt_scene_x = rect.x() + rect.width() * 0.85
    gx, gy = to_phys(view, b_scene_x, sy)
    tx, _ = to_phys(view, tgt_scene_x, sy)
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        at(gx + (tx - gx) * k // steps, gy, MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    at(tx, gy, LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "sub_cursor_dragged.png")
        )
    assert view.delta_line_value() > b_before  # B は右へ動いた
    assert view.cursor_line_value() == pytest.approx(a_before)  # A は不変


def test_real_drag_b_cursor_stats_live_recalc(qtbot: QtBot, tmp_path) -> None:
    """B 線実ドラッグ → CursorReadout 範囲統計がライブ再計算される(R17 ②証拠)。

    A+B 両線設置 → B 線(75%)を 85%へ実ドラッグ。
    - mid-drag: row_texts() が数値統計を含む(「範囲外」/「データなし」でない)
    - before/after でテキストが異なる(ドラッグに追従してライブ再計算された証拠)
    - 最後に primaryScreen.grabWindow(0) → stats_live.png(判読可能フォント確認用)

    honest RED gate: view._cursor_line_b.sigPositionChanged.disconnect(
        view._on_cursor_line_b_dragged)  # graph_panel_view.py L1122
    を挿入すると B ドラッグ後も統計が更新されず texts_before != texts_after が RED になる。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)  # A: 50%
    view.vm.toggle_delta(True)  # B: 75%
    for _ in range(5):
        QApplication.processEvents()
    assert view.cursor_line_visible() and view.delta_line_visible()
    assert view.readout_visible()

    # Initial readout at B=75% — used to prove stats CHANGED after drag
    texts_before = view._readout.row_texts()
    assert texts_before, "delta-mode readout should have at least one signal row"

    # Drag B line from 75% → 85% with real OS mouse input
    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    b_scene_x = rect.x() + rect.width() * 0.75
    sy = rect.y() + rect.height() * 0.5
    tgt_scene_x = rect.x() + rect.width() * 0.85
    gx, gy = to_phys(view, b_scene_x, sy)
    tx, _ = to_phys(view, tgt_scene_x, sy)

    texts_mid: list[tuple[str, str]] = []
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    steps = max(4, (abs(tx - gx) + 7) // 8)
    mid = steps // 2
    for k in range(1, steps + 1):
        at(gx + (tx - gx) * k // steps, gy, MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
        if k == mid:
            texts_mid = view._readout.row_texts()
    at(tx, gy, LUP)
    for _ in range(5):
        QApplication.processEvents()

    texts_after = view._readout.row_texts()

    # (1) mid-drag: readout rows are present and contain no placeholder text
    _PLACEHOLDERS = {"範囲外", "データなし", ""}
    assert texts_mid, (
        "mid-drag readout has no rows — delta mode may not be active mid-drag"
    )
    for _name, cell_text in texts_mid:
        for token in cell_text.split():
            assert token not in _PLACEHOLDERS, (
                f"mid-drag readout has placeholder {token!r} in row {_name!r}: {cell_text!r}"
            )

    # (2) stats changed between B=75% (before) and B=85% (after) — proves live recalc
    # [A,B] range expanded → sample count and aggregates differ
    assert texts_before != texts_after, (
        "range stats unchanged after dragging B cursor — live recalc may be broken. "
        f"before={texts_before!r}  after={texts_after!r}"
    )

    # Screenshot for /verify: readable font on real Windows display (offscreen → tofu)
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "stats_live.png")
        )
