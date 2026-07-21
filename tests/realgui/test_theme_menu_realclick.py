"""Layer C: View>テーマ radio の実 OS クリック (r4・spec §11.6)。

検証: (1) 実クリックで「ライト」を選ぶと QSettings に light が保存される
      (2) ステータスバーに「再起動で反映」が出る
      (3) 画面は即変化しない (active() 不変 = 再起動反映)
実マウスでメニューバー View → テーマ → ライト を辿る。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def _click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    time.sleep(0.05)
    at(x, y, LUP)


def _phys_center(widget, rect) -> tuple[int, int]:
    dpr = widget.devicePixelRatioF()
    gp = widget.mapToGlobal(rect.center())
    return round(gp.x() * dpr), round(gp.y() * dpr)


def test_theme_radio_real_click_saves_without_repaint(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.app import build_main_window
    from valisync.gui.theme import apply as theme_apply
    from valisync.gui.theme.tokens import ThemeMode, active

    window = build_main_window()
    qtbot.addWidget(window)
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(screen.x() + 60, screen.y() + 60, 1120, 760)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    for _ in range(3):
        QApplication.processEvents()

    before_active = active()
    assert theme_apply.load_theme_mode() is ThemeMode.AUTO  # 隔離済み初期状態

    # View メニューを実クリックで開く
    menubar = window.menuBar()
    view_action = next(a for a in menubar.actions() if "View" in a.text())
    _click(*_phys_center(menubar, menubar.actionGeometry(view_action)))
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None, timeout=3000)
    view_menu = QApplication.activePopupWidget()

    # テーマ submenu を実クリックで開く
    theme_action = next(a for a in view_menu.actions() if a.text() == "テーマ")
    _click(*_phys_center(view_menu, view_menu.actionGeometry(theme_action)))
    theme_menu = theme_action.menu()
    qtbot.waitUntil(lambda: theme_menu.isVisible(), timeout=3000)

    # 「ライト」を実クリック
    light_action = next(a for a in theme_menu.actions() if a.text() == "ライト")
    _click(*_phys_center(theme_menu, theme_menu.actionGeometry(light_action)))
    qtbot.waitUntil(
        lambda: theme_apply.load_theme_mode() is ThemeMode.LIGHT, timeout=3000
    )

    for _ in range(3):
        QApplication.processEvents()
    assert active() is before_active, "再起動反映のはずが active が即変化した"
    assert "再起動" in window.status_message()  # 右ラベルへ移設 (spec §2.4)
    with __import__("contextlib").suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "theme_menu.png")
        )
