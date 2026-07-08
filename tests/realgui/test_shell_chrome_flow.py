"""Layer C: シェル chrome の実 OS 入力 (SH-11/12)。

`--realgui` opt-in・実ディスプレイ+Windows 必須。物理カーソルを動かし Win32
`mouse_event` で本物のクリックを発行する(合成 QTest イベントではない)ため、
実行中は約1-2秒マウスを占有し、画面にウィンドウとカーソル移動が映る。OS→Qt の
ヒットテスト/配送まで含めて検証する唯一の層 — 詳細は docs/gui-testing-layers.md。

判定は自動 assert に加え、各操作後のスクリーンショットを人/AI が目視確認する
(スクショパスは失敗時メッセージと実行ログに出力)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui

# QSettings 隔離 (実 ValiSync 設定汚染/テスト間漏れ防止) は tests/realgui/conftest.py の
# autouse fixture が全 realgui テストへ横断適用する。


def _shown_mw(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    mw.recent_files = mw.recent_files.__class__(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(mw)
    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    # _restore_state() が実レジストリから復元しうる最大化状態を解除し既知の
    # ジオメトリに固定する。最大化のままだと座標計算とクリック着弾がずれる。
    mw.showNormal()
    mw.setGeometry(120, 120, 1200, 760)
    mw.raise_()
    mw.activateWindow()
    qtbot.waitExposed(mw)
    qtbot.waitUntil(lambda: not mw.isMaximized() and mw.width() > 1000, timeout=3000)
    QApplication.processEvents()
    return mw


def _phys(widget) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """widget 中心の物理スクリーンピクセル(DPR スケール)を「呼び出し時点で」算出。"""
    c = widget.rect().center()
    g = widget.mapToGlobal(c)
    dpr = widget.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _real_click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    at(x, y, LUP)


def _toolbar_toggle_button(mw):  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QToolBar, QToolButton

    toolbar = mw.findChild(QToolBar, "main_toolbar")
    btn = toolbar.widgetForAction(mw.file_dock.toggleViewAction())
    assert isinstance(btn, QToolButton)
    return btn


def test_toolbar_dock_toggle_real_os_click(qtbot: QtBot, tmp_path: Path) -> None:
    """SH-12: ツールバーの file_dock トグルボタンを物理クリック → ドックが隠れる。"""
    skip_unless_real_display()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    mw = _shown_mw(qtbot, tmp_path)
    btn = _toolbar_toggle_button(mw)
    qtbot.waitUntil(lambda: btn.isVisible() and btn.width() > 0, timeout=3000)
    assert mw.file_dock.isVisible()
    shot = tmp_path / "sh12_after_toggle.png"
    captured: dict[str, object] = {}

    def do_click() -> None:
        # クリック直前に現在位置から座標を再計算(最大化解除後の実位置)。
        _real_click(*_phys(btn))

    def check() -> None:
        QApplication.primaryScreen().grabWindow(0).save(str(shot))
        captured["visible_after"] = mw.file_dock.isVisible()
        loop.quit()

    loop = QEventLoop()
    QTimer.singleShot(500, do_click)
    QTimer.singleShot(1100, check)
    QTimer.singleShot(4000, loop.quit)  # safety net
    loop.exec()

    print(
        f"[SH-12] file_dock.isVisible after real click = {captured.get('visible_after')}"
    )
    print(f"[SH-12] screenshot: {shot}")
    assert captured.get("visible_after") is False, (
        f"物理クリックでツールバートグルが効かずドックが隠れない。screenshot: {shot}"
    )


def test_reset_layout_recovers_hidden_dock_real_os(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """SH-11: 実クリックで file_dock を隠す → View>Reset Layout を実クリック → 復帰。

    Reset Layout の用途(崩れた配置からの復旧)を全て実 OS 入力で再現し、復帰を
    スクショで確認する。
    """
    skip_unless_real_display()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    mw = _shown_mw(qtbot, tmp_path)
    btn = _toolbar_toggle_button(mw)
    qtbot.waitUntil(lambda: btn.isVisible() and btn.width() > 0, timeout=3000)
    assert mw.file_dock.isVisible()
    shot_hidden = tmp_path / "sh11_after_hide.png"
    shot_reset = tmp_path / "sh11_after_reset.png"
    cap: dict[str, object] = {}

    def hide_dock() -> None:
        _real_click(*_phys(btn))  # トグルで file_dock を隠す

    def after_hide() -> None:
        QApplication.primaryScreen().grabWindow(0).save(str(shot_hidden))
        cap["hidden"] = not mw.file_dock.isVisible()

    def open_view_menu() -> None:
        # menubar の "&View" を実クリックしてメニューを開く。
        menubar = mw.menuBar()
        view_action = next(
            a for a in menubar.actions() if a.text().replace("&", "") == "View"
        )
        vr = menubar.actionGeometry(view_action)
        dpr = mw.devicePixelRatioF()
        gv = menubar.mapToGlobal(vr.center())
        _real_click(round(gv.x() * dpr), round(gv.y() * dpr))

    def click_reset() -> None:
        popup = QApplication.activePopupWidget()
        if isinstance(popup, QMenu):
            cap["menu_opened"] = True
            reset = next(
                (a for a in popup.actions() if a.text() == "Reset Layout"), None
            )
            if reset is not None:
                r = popup.actionGeometry(reset)
                dpr = mw.devicePixelRatioF()
                gr = popup.mapToGlobal(r.center())
                _real_click(round(gr.x() * dpr), round(gr.y() * dpr))
        else:
            cap["menu_opened"] = False

    def check() -> None:
        QApplication.primaryScreen().grabWindow(0).save(str(shot_reset))
        cap["visible_after_reset"] = mw.file_dock.isVisible()
        loop.quit()

    loop = QEventLoop()
    QTimer.singleShot(500, hide_dock)
    QTimer.singleShot(1000, after_hide)
    QTimer.singleShot(1400, open_view_menu)
    QTimer.singleShot(2000, click_reset)
    QTimer.singleShot(2600, check)
    QTimer.singleShot(6000, loop.quit)  # safety net
    loop.exec()

    print(f"[SH-11] hidden after toggle = {cap.get('hidden')}")
    print(f"[SH-11] View menu opened = {cap.get('menu_opened')}")
    print(f"[SH-11] visible after reset = {cap.get('visible_after_reset')}")
    print(f"[SH-11] screenshots: {shot_hidden} , {shot_reset}")
    assert cap.get("hidden") is True, (
        f"実クリックで file_dock を隠せなかった。screenshot: {shot_hidden}"
    )
    assert cap.get("menu_opened") is True, (
        f"View メニューが実クリックで開かなかった。screenshot: {shot_reset}"
    )
    assert cap.get("visible_after_reset") is True, (
        f"Reset Layout 実クリック後に file_dock が復帰しない。screenshot: {shot_reset}"
    )
