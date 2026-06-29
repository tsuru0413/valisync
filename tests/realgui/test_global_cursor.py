"""Layer C: Global_Cursor を実 OS 入力で検証(R15)。--realgui で実行。

新規経路(前例なし): プロット内クリック設置 / InfiniteLine 実ドラッグ。
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


def test_real_click_places_cursor_at_clicked_x(qtbot: QtBot, tmp_path) -> None:
    """実クリック → InfiniteLine がクリックのデータ x 近傍に描画される(②: 実経路の描画位置)。"""
    _skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    sx, sy, expected_x = _scene_center(view)
    px, py = _to_phys(view, sx, sy)
    _at(px, py, _LDOWN)
    time.sleep(0.03)
    _at(px, py, _LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "cursor_placed.png")
        )
    assert view.cursor_line_visible()
    assert abs(view.cursor_line_value() - expected_x) <= _x_span(view) * 0.05
    assert view.readout_visible()


def test_real_drag_cursor_line_moves_it(qtbot: QtBot, tmp_path) -> None:
    """中央に設置→線を右へ実ドラッグ → 描画 x(line.value)が増加(②: 実ドラッグ結果)。"""
    _skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    sx, sy, _ = _scene_center(view)
    px, py = _to_phys(view, sx, sy)
    _at(px, py, _LDOWN)
    time.sleep(0.03)
    _at(px, py, _LUP)
    for _ in range(5):
        QApplication.processEvents()
    assert view.cursor_line_visible()
    x_before = view.cursor_line_value()

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
