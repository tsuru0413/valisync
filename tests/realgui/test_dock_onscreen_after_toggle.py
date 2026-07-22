"""Layer C: FU-04 — 超長 Recent パス登録時でも Diagnostics 実トグルで
File/Channel Browser ドックが画面内に留まる。

`--realgui` opt-in・実ディスプレイ+Windows 必須。この受け入れは Layer A/B で
再チェック不能: offscreen では geometry が実配置にならず、最小幅制約→OS の
画面幅クランプ→再レイアウトでドックが画面外へ押し出される連鎖は実ウィンドウ
マネージャ下でしか起きない (memory: gui_isvisible_true_for_offscreen_hidden_dock)。

判定は自動 assert (visibleRegion + 画面内グローバル矩形。isVisible() は画面外
でも True を返す FU-04 の偽陰性計器なので「画面内」の証拠に使わない) に加え、
各操作後のスクリーンショットを人/AI が目視確認する。

honest-RED: Task 2 Step 2 で elide を一時的に外し (btn.setText(path))、本テストが
実際に FAIL する (ウィンドウ最小幅が画面幅超過→ドック画面外) ことを実証済み。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


class _FakeRecent:
    """existing() だけの duck-stub。超長パスは MAX_PATH(260) で実ファイル化
    できないため文字列を直接注入する (入力=実 OS クリックは無傷のまま)。"""

    def __init__(self, paths: list[str]) -> None:
        self._paths = paths

    def existing(self) -> list[str]:
        return list(self._paths)


def _onscreen(dock) -> bool:  # type: ignore[no-untyped-def]
    """画面内判定: visibleRegion 非空 + グローバル矩形が screen 内 + 実幅。

    isVisible() は画面外/タブ裏でも True (FU-04 の偽陰性計器) のため使わない。
    """
    from PySide6.QtWidgets import QApplication

    scr = QApplication.primaryScreen().geometry()
    tl = dock.mapToGlobal(dock.rect().topLeft())
    br = dock.mapToGlobal(dock.rect().bottomRight())
    return (
        scr.contains(tl)
        and scr.contains(br)
        and not dock.visibleRegion().isEmpty()
        and dock.width() > 5
    )


def _phys(widget) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """widget 中心の物理スクリーンピクセル (DPR スケール) を呼び出し時点で算出。"""
    c = widget.rect().center()
    g = widget.mapToGlobal(c)
    dpr = widget.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _real_click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    at(x, y, LUP)


def _shown_mw_with_long_recent(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    # どの画面幅でも修正前は必ず膨張するよう、画面幅の ~2 倍の描画幅を要求する
    # パス長を画面幅から導出する (1 文字 ~6px の保守見積)。
    screen_w = QApplication.primaryScreen().geometry().width()
    n_chars = max(400, (screen_w * 2) // 6)
    long_path = "C:/" + "d" * n_chars + "/measurement.mf4"
    mw.welcome_view._recent = _FakeRecent([long_path])  # type: ignore[assignment]
    mw.welcome_view.refresh()

    mw.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    mw.showNormal()
    # availableGeometry 内配置 (オフスクリーン配置は誤着地の既知罠)。
    ag = QApplication.primaryScreen().availableGeometry()
    mw.setGeometry(
        ag.x() + 40,
        ag.y() + 40,
        min(1100, ag.width() - 80),
        min(640, ag.height() - 80),
    )
    mw.raise_()
    mw.activateWindow()
    qtbot.waitExposed(mw)
    QApplication.processEvents()
    return mw


def test_docks_stay_onscreen_with_long_recent_after_real_diagnostics_toggle(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-04 受け入れ: 超長 Recent 登録 + Diagnostics 実トグル (hide→show) の
    前後で File/Channel Browser ドックが画面内に留まる。"""
    skip_unless_real_display()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

    mw = _shown_mw_with_long_recent(qtbot)
    screen = QApplication.primaryScreen().geometry()

    # 修正の核: 超長 Recent 登録後もウィンドウ最小幅が画面幅未満に収まる。
    # 修正前はここで画面幅の ~2 倍に膨張して即 FAIL する (honest-RED の第一関門)。
    min_w = mw.minimumSizeHint().width()
    assert min_w < screen.width(), (
        f"FU-04 再発: 超長 Recent でウィンドウ最小幅 {min_w}px が"
        f"画面幅 {screen.width()}px を超えて膨張している"
    )

    # トグル前からブラウザドックは画面内 (修正前は膨張ウィンドウで既に画面外)。
    assert _onscreen(mw.file_dock), "file_dock がトグル前から画面外"
    assert _onscreen(mw.channel_dock), "channel_dock がトグル前から画面外"
    assert mw.diagnostics_dock.isVisible()  # トグル対象の初期状態

    toolbar = mw.findChild(QToolBar, "main_toolbar")
    # D-3/UX-45: toggleViewAction は掲載されなくなった (三態カスタム QAction へ
    # 置換 — docs/superpowers/specs/2026-07-22-d3-tristate-icons-design.md §2.3)。
    btn = toolbar.widgetForAction(mw._dock_actions["diagnostics_dock"])
    assert isinstance(btn, QToolButton)
    qtbot.waitUntil(lambda: btn.isVisible() and btn.width() > 0, timeout=3000)

    shot_hidden = tmp_path / "fu04_after_hide.png"
    shot_reshown = tmp_path / "fu04_after_reshow.png"
    cap: dict[str, object] = {}

    def click_hide() -> None:
        # クリック直前に現在位置から座標を再計算 (再レイアウト後の実位置)。
        _real_click(*_phys(btn))

    def after_hide() -> None:
        QApplication.primaryScreen().grabWindow(0).save(str(shot_hidden))
        # not isVisible() は「隠れた」方向の証拠としては健全 (罠は True 側のみ)。
        cap["diag_hidden"] = not mw.diagnostics_dock.isVisible()
        cap["file_on_after_hide"] = _onscreen(mw.file_dock)
        cap["chan_on_after_hide"] = _onscreen(mw.channel_dock)

    def click_reshow() -> None:
        _real_click(*_phys(btn))

    def check() -> None:
        QApplication.primaryScreen().grabWindow(0).save(str(shot_reshown))
        cap["file_on_after_reshow"] = _onscreen(mw.file_dock)
        cap["chan_on_after_reshow"] = _onscreen(mw.channel_dock)
        loop.quit()

    loop = QEventLoop()
    QTimer.singleShot(500, click_hide)
    QTimer.singleShot(1200, after_hide)
    QTimer.singleShot(1600, click_reshow)
    QTimer.singleShot(2400, check)
    QTimer.singleShot(6000, loop.quit)  # safety net
    loop.exec()

    print(f"[FU-04] diag hidden after real click = {cap.get('diag_hidden')}")
    print(
        f"[FU-04] onscreen after hide: file={cap.get('file_on_after_hide')} "
        f"channel={cap.get('chan_on_after_hide')}"
    )
    print(
        f"[FU-04] onscreen after reshow: file={cap.get('file_on_after_reshow')} "
        f"channel={cap.get('chan_on_after_reshow')}"
    )
    print(f"[FU-04] screenshots: {shot_hidden} , {shot_reshown}")

    assert cap.get("diag_hidden") is True, (
        f"実クリックで Diagnostics トグルが効いていない (操作不達)。"
        f"screenshot: {shot_hidden}"
    )
    assert cap.get("file_on_after_hide") is True, (
        f"FU-04 再発: Diagnostics 非表示化で file_dock が画面外へ。{shot_hidden}"
    )
    assert cap.get("chan_on_after_hide") is True, (
        f"FU-04 再発: Diagnostics 非表示化で channel_dock が画面外へ。{shot_hidden}"
    )
    assert cap.get("file_on_after_reshow") is True, (
        f"FU-04 再発: Diagnostics 再表示で file_dock が画面外へ。{shot_reshown}"
    )
    assert cap.get("chan_on_after_reshow") is True, (
        f"FU-04 再発: Diagnostics 再表示で channel_dock が画面外へ。{shot_reshown}"
    )
