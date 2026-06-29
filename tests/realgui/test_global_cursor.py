"""Layer C: Global_Cursor を実 OS 入力で検証(R15/R16)。--realgui で実行。

新規経路(前例なし): InfiniteLine 実ドラッグ(A 線単独・B 線2線ヒット分離)。
再利用: tests/gui/_panel_factory.make_two_axis_panel、test_active_axis_zoom_pan.py 同形の _to_phys/_at。
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
import time

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

pytestmark = pytest.mark.realgui
_MOVE, _LDOWN, _LUP = 0x0001, 0x0002, 0x0004


def _skip_unless_real_display() -> None:
    if sys.platform != "win32":
        pytest.skip("real OS input is Windows-only")
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() == "offscreen":
        pytest.skip(
            "requires a real display — run: uv run pytest --realgui tests/realgui/"
        )


def _to_phys(view, sx: float, sy: float) -> tuple[int, int]:
    from PySide6.QtCore import QPoint

    vp = view.plot_widget.mapFromScene(QPoint(int(sx), int(sy)))
    g = view.plot_widget.viewport().mapToGlobal(vp)
    dpr = view.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _at(x: float, y: float, flag: int) -> None:
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(flag, 0, 0, 0, 0)


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
    _skip_unless_real_display()
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
    gx, gy = _to_phys(view, sx, sy)
    tx, _ = _to_phys(view, target_sx, sy)
    _at(gx, gy, _LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        _at(gx + (tx - gx) * k // steps, gy, _MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    _at(tx, gy, _LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "cursor_dragged.png")
        )
    assert view.cursor_line_value() > x_before


def test_real_drag_sub_cursor_moves_only_b(qtbot: QtBot, tmp_path) -> None:
    """main+delta 表示 → B 線(75%)を実ドラッグ → B が動き A は不変(②: 実ヒットテスト)。"""
    _skip_unless_real_display()
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
    gx, gy = _to_phys(view, b_scene_x, sy)
    tx, _ = _to_phys(view, tgt_scene_x, sy)
    _at(gx, gy, _LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        _at(gx + (tx - gx) * k // steps, gy, _MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    _at(tx, gy, _LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "sub_cursor_dragged.png")
        )
    assert view.delta_line_value() > b_before  # B は右へ動いた
    assert view.cursor_line_value() == pytest.approx(a_before)  # A は不変
