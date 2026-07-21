"""Layer C: Shift+実クリックでカーソル B を直接設置 (UX-13・spec §2.2 優先規則)。

計測 IA 刷新で B の設置は「A 設置済み → プロット上を Shift+クリック」の新ジェスチャに
一本化された (spec §2.2)。Shift 押下の左 press は ZONE_PLOT 全域で計測ジェスチャとして
最優先で分岐し、曲線ヒット (DP16 press 候補) やカーソル線 10px ヒット帯より先に確定する。

ここでは実 OS の「Shift 押下 → 左クリック → Shift 解放」で B が目標時刻近傍に設置され、
暗黙 delta が立ち、B 破線が実描画されることを検証する。honest RED:
- (対照) 同座標を **Shift なし** でクリックすると B は設置されない (plain click は
  曲線非活性化のみ)。
- (sabotage・実施記録は task-9-report.md) graph_panel_view.py の Shift 分岐条件を
  一時無効化すると Shift+クリックでも B が不発になることを1度実証し revert。

曲線上座標の1ケースも含める (優先規則: Shift 押下は曲線ヒットより先に分岐するため、
曲線の真上を Shift+クリックしても press 候補/オフセットドラッグに奪われず B が置ける)。
"""

from __future__ import annotations

import contextlib
import time

import pytest
from PySide6.QtCore import QPointF
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    VK_SHIFT,
    at,
    click_with_modifier,
    skip_unless_real_display,
    to_phys,
)

pytestmark = pytest.mark.realgui


def _shown_single_panel(qtbot: QtBot):  # type: ignore[no-untyped-def]
    """実ディスプレイに表示した単一線形信号 (v=t) の GraphPanelView。

    v=t は予測可能な対角曲線 — 任意の列 (scene-x) で曲線の data-y が data-x に等しく、
    曲線上/曲線外の物理座標を決定的に算出できる。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_single_signal_panel

    view = make_single_signal_panel()
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    view.setGeometry(screen.x() + 60, screen.y() + 60, 820, 600)
    view.show()
    view.raise_()
    view.activateWindow()
    qtbot.waitExposed(view)
    qtbot.waitUntil(
        lambda: (
            bool(view._view_boxes)
            and view._view_boxes[0].sceneBoundingRect().height() > 100
        ),
        timeout=3000,
    )
    for _ in range(3):
        QApplication.processEvents()
    return view


def _place_cursor_a(view) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    view.vm.x_range = view.vm.x_range or (0.0, 0.98)
    view.vm.toggle_main_cursor(True)  # A を 50% に設置
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible(), "A カーソルが設置されていない"


def _plain_click(x: int, y: int) -> None:
    from PySide6.QtWidgets import QApplication

    at(x, y, LDOWN)
    QApplication.processEvents()
    time.sleep(0.03)
    at(x, y, LUP)
    for _ in range(4):
        QApplication.processEvents()
        time.sleep(0.02)


def test_shift_click_places_cursor_b(qtbot: QtBot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A 設置済み → 曲線から離れた点を Shift+実クリック → B が目標時刻近傍に設置。

    対照 (honest RED): 直前に同座標を Shift なしでクリックしても B は設置されない。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_single_panel(qtbot)
    _place_cursor_a(view)

    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    # 70% 列・曲線から離れた下端寄り (v=t の曲線 data-y≈0.686 に対し ここは data-y≈0.13)。
    sx = rect.x() + rect.width() * 0.70
    sy = rect.y() + rect.height() * 0.85
    expected_x = vb.mapSceneToView(QPointF(sx, sy)).x()
    span = view.vm.x_range[1] - view.vm.x_range[0]
    px, py = to_phys(view, sx, sy)

    # 対照: Shift なしの plain click は B を設置しない (曲線非活性化のみ)。
    _plain_click(px, py)
    assert view.vm.cursor_t_b is None, (
        f"Shift なしクリックで B が設置された (対照失敗): cursor_t_b={view.vm.cursor_t_b!r}"
    )

    # 本番: Shift+実クリックで B を設置。
    click_with_modifier(px, py, VK_SHIFT)
    for _ in range(6):
        QApplication.processEvents()
        time.sleep(0.02)

    shot = tmp_path / "shift_click_b.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot))

    assert view.vm.cursor_t_b is not None, (
        "Shift+実クリックで B が設置されない (Shift 分岐が実経路で機能していない)。"
        f" screenshot: {shot}"
    )
    assert view.vm.cursor_t_b == pytest.approx(expected_x, abs=span * 0.05), (
        f"B が目標時刻近傍に無い: cursor_t_b={view.vm.cursor_t_b!r} "
        f"expected≈{expected_x!r}. screenshot: {shot}"
    )
    assert view.vm.delta_enabled is True, "B 設置で暗黙 delta が立っていない"
    assert view.delta_line_visible(), (
        f"B 破線が実描画されていない (delta_line 非表示)。screenshot: {shot}"
    )


def test_shift_click_on_curve_places_cursor_b(qtbot: QtBot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """曲線の真上を Shift+実クリック → 優先規則で B が設置される (曲線ヒットに奪われない)。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_single_panel(qtbot)
    _place_cursor_a(view)

    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    # 70% 列の曲線上の点: data-x をその列で取り、v=t なので data-y=data-x の点へ写像。
    sx_col = rect.x() + rect.width() * 0.70
    data_x = vb.mapSceneToView(QPointF(sx_col, rect.y())).x()
    curve_scene = vb.mapViewToScene(QPointF(data_x, data_x))  # 曲線上の scene 点
    span = view.vm.x_range[1] - view.vm.x_range[0]

    # 事前確認: この widget 座標が実際に曲線ヒット圏内 (優先規則が意味を持つ前提)。
    widget_pos = view.plot_widget.mapFromScene(curve_scene)
    assert view._curve_at(QPointF(widget_pos)) is not None, (
        "算出点が曲線上に無い — この検証は曲線ヒット帯の上を Shift+クリックしてこそ意味がある"
    )

    px, py = to_phys(view, curve_scene.x(), curve_scene.y())
    click_with_modifier(px, py, VK_SHIFT)
    for _ in range(6):
        QApplication.processEvents()
        time.sleep(0.02)

    shot = tmp_path / "shift_click_on_curve_b.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot))

    assert view.vm.cursor_t_b is not None, (
        "曲線上の Shift+実クリックで B が設置されない — press 候補/オフセットドラッグに"
        f" 奪われた可能性 (優先規則の破れ)。screenshot: {shot}"
    )
    assert view.vm.cursor_t_b == pytest.approx(data_x, abs=span * 0.05), (
        f"B が目標時刻近傍に無い: cursor_t_b={view.vm.cursor_t_b!r} expected≈{data_x!r}. "
        f"screenshot: {shot}"
    )
    assert view.vm.delta_enabled is True, "曲線上 B 設置で暗黙 delta が立っていない"
    assert view.delta_line_visible(), f"B 破線が実描画されていない。screenshot: {shot}"
