"""Layer C: タブ操作アフォーダンスの実 OS 入力 (SH-02/04/13)。

合成 qtbot ではなく実クリック/実ダブルクリック/実キー入力でコーナー + と
タブ改名を駆動する。実ダブルクリックは同一点の press/release 2組を MOVE 無しで
GetDoubleClickTime 窓内に発行し、各イベント間で event loop を pump する
(test_diagnostics_dock_realinput.py の確立パターン。間隔ゼロの連打では OS が
dblclick と認識しない)。視覚結果(タブ増加・改名)はスクショで目視判定する。
"""

from __future__ import annotations

import ctypes
import time

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    VK_RETURN,
    at,
    key,
    skip_unless_real_display,
)

pytestmark = pytest.mark.realgui

_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None


def _double_click(x: int, y: int) -> None:
    """物理(x, y)で本物の OS ダブルクリック。同一点の press/release 2組を MOVE 無しで
    GetDoubleClickTime 窓内に発行し、各イベント間で event loop を pump する。OS が
    2組目の press を WM_LBUTTONDBLCLK に合体させる(Qt: MouseButtonDblClick)。
    """
    from PySide6.QtWidgets import QApplication

    ms = _user32.GetDoubleClickTime() if _user32 is not None else 500
    interval_s = min(ms / 2, 150) / 1000
    at(x, y, LDOWN)
    QApplication.processEvents()
    time.sleep(0.03)
    at(x, y, LUP)
    QApplication.processEvents()
    time.sleep(interval_s)
    at(x, y, LDOWN)
    QApplication.processEvents()
    time.sleep(0.03)
    at(x, y, LUP)
    for _ in range(4):
        QApplication.processEvents()
        time.sleep(0.02)


def _real_click(x: int, y: int) -> None:
    from PySide6.QtWidgets import QApplication

    at(x, y, LDOWN)
    QApplication.processEvents()
    time.sleep(0.03)
    at(x, y, LUP)
    for _ in range(4):
        QApplication.processEvents()
        time.sleep(0.02)


def _make_shown_area(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.graph_area_view import GraphAreaView

    vm = GraphAreaVM(AppViewModel(Session()))
    view = GraphAreaView(vm, panel_factory=lambda _vm: QLabel())
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # availableGeometry 内へ配置(オフスクリーンだと物理クリックが着弾しない)。
    screen = QApplication.primaryScreen().availableGeometry()
    view.setGeometry(screen.x() + 80, screen.y() + 80, 640, 440)
    view.show()
    view.raise_()
    view.activateWindow()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    return view


def _phys_center(w, local_center) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    gp = w.mapToGlobal(local_center)
    dpr = w.devicePixelRatioF()
    return round(gp.x() * dpr), round(gp.y() * dpr)


def test_corner_button_click_adds_tab(qtbot: QtBot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication, QToolButton

    view = _make_shown_area(qtbot)
    # spec §2.3: corner は「+」と読み値トグルの横並びコンテナに変わった。コンテナ中心を
    # 掴むとボタン境界/読み値トグルに落ちて実挙動を破壊するので、new_tab_button 自体の
    # 矩形中心を掴む (test-lock 追随 — cornerWidget().objectName() 単一ボタン前提は撤廃)。
    corner = view.tabs.cornerWidget()
    btn = corner.findChild(QToolButton, "new_tab_button")
    assert btn is not None, "corner コンテナ内に new_tab_button が無い"
    qtbot.waitUntil(lambda: btn.isVisible() and btn.width() > 0, timeout=3000)
    x, y = _phys_center(btn, btn.rect().center())
    _real_click(x, y)
    qtbot.waitUntil(lambda: view.tabs.count() == 2, timeout=2000)
    shot = tmp_path / "tab_added.png"
    QApplication.primaryScreen().grabWindow(0).save(str(shot))
    print(f"[tab] count={view.tabs.count()} screenshot={shot}")
    assert view.tabs.count() == 2, (
        f"コーナー + の実クリックで新規タブが増えない。screenshot: {shot}"
    )


def test_double_click_tab_renames(qtbot: QtBot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _make_shown_area(qtbot)
    bar = view.tabs.tabBar()
    qtbot.waitUntil(lambda: bar.tabRect(0).width() > 0, timeout=3000)
    x, y = _phys_center(bar, bar.tabRect(0).center())
    shot = tmp_path / "tab_renamed.png"
    _double_click(x, y)
    try:
        qtbot.waitUntil(lambda: view._rename_editor is not None, timeout=2000)
    except Exception as exc:
        QApplication.primaryScreen().grabWindow(0).save(str(shot))
        raise AssertionError(
            f"実ダブルクリックで改名エディタが開かない(dblclick 不成立)。screenshot: {shot}"
        ) from exc
    QApplication.processEvents()
    # 実キーで "renamed" を打鍵(既存名は選択状態なので置換される) → Return で確定。
    for ch in "renamed":
        key(ord(ch.upper()))
        QApplication.processEvents()
    key(VK_RETURN)
    try:
        qtbot.waitUntil(lambda: view.vm.tabs()[0].name == "renamed", timeout=2000)
    except Exception as exc:
        QApplication.primaryScreen().grabWindow(0).save(str(shot))
        raise AssertionError(
            f"実キー入力がエディタに届かず改名されない(name={view.vm.tabs()[0].name})。"
            f"screenshot: {shot}"
        ) from exc
    QApplication.primaryScreen().grabWindow(0).save(str(shot))
    print(f"[tab] name={view.vm.tabs()[0].name} screenshot={shot}")
    assert view.vm.tabs()[0].name == "renamed", (
        f"実ダブルクリック+実キーでタブ改名されない。screenshot: {shot}"
    )
