# ruff: noqa: RUF002
"""Layer C: 「X軸同期（タブ内全パネル）」を右クリックメニューから実 OS で ON にする (spec §2.3)。

計測 IA 刷新 v3 決定4 でタブ行の Sync X チェックボックスは撤去され、X 軸同期は
空白右クリックメニューの checkable 項目のみになった。ここでは 2 パネルのエリアで
X-sync を OFF にした状態から、**実右クリック→「X軸同期（タブ内全パネル）」を実クリック**
して ON にし、続けて片パネルを **実 OS で X ズーム** すると兄弟パネルの x_range が
追随することを数値で検証する (メニュー項目が実際に VM を駆動し伝播する実経路の証明)。

空白右クリックメニューは contextMenuEvent の ``menu.exec()`` で開くモーダルネスト
ループなので、_open_menu_click_item (test_axis_menu_offset.py 確立パターンの
module-local コピー) で駆動する。X ズームは test_x_axis_zoom_pan.py の _x_strip_drag
と同型 (X ストリップ内側ゾーンの実ドラッグ = 範囲選択ズーム)。
"""

from __future__ import annotations

import contextlib
import tempfile
import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    MOVE,
    RDOWN,
    RUP,
    VK_ESCAPE,
    at,
    skip_unless_real_display,
    to_phys,
)
from tests.realgui._realgui_input import key as key_input

pytestmark = pytest.mark.realgui

_SYNC_LABEL = "X軸同期（タブ内全パネル）"


# ─── modal-menu harness (faithful module-local copy of test_axis_menu_offset.py) ─


def _menu_hang_watchdog(stop: threading.Event) -> None:
    """Escape で詰まった ``QMenu.exec()`` を強制クローズ (clean-fail に倒す)。

    右クリックがメニューを開けなかった/行クリックが外れた場合、contextMenuEvent の
    ネスト exec() が永久にブロックする。QMenu は Escape を「閉じる」に解釈するので、
    デッドライン後に VK_ESCAPE を送る。ハングしたかの真実は呼び出し側の loop.exec()
    が返ったか — 返れば直後に stop がセットされ、正常系ではこのスレッドは発火しない。
    """
    deadline = time.time() + 4.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.1)
    if not stop.is_set():
        key_input(VK_ESCAPE)


def _open_menu_click_item(dpr_widget, phys, item_text: str, shot_menu: Path):  # type: ignore[no-untyped-def]
    """*phys* を実右クリック→popup を撮影→行 *item_text* を実クリック。captured を返す。"""
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    px, py = phys
    captured: dict[str, object] = {}
    loop = QEventLoop()

    def _do_right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)

    def _capture_and_click() -> None:
        popup = QApplication.activePopupWidget()
        captured["type"] = type(popup).__name__ if popup is not None else None
        with contextlib.suppress(Exception):
            QApplication.primaryScreen().grabWindow(0).save(str(shot_menu))
        if isinstance(popup, QMenu):
            captured["actions"] = [a.text() for a in popup.actions()]
            act = next((a for a in popup.actions() if a.text() == item_text), None)
            if act is not None:
                r = popup.actionGeometry(act)
                dpr = dpr_widget.devicePixelRatioF()
                gp = popup.mapToGlobal(r.center())
                hx, hy = round(gp.x() * dpr), round(gp.y() * dpr)
                at(hx, hy, LDOWN)
                at(hx, hy, LUP)
                captured["clicked"] = True
        loop.quit()

    stop = threading.Event()
    watchdog = threading.Thread(target=_menu_hang_watchdog, args=(stop,), daemon=True)
    watchdog.start()

    QTimer.singleShot(300, _do_right_click)
    QTimer.singleShot(900, _capture_and_click)
    QTimer.singleShot(5000, loop.quit)  # outer safety net
    loop.exec()

    stop.set()
    watchdog.join(timeout=2.0)
    return captured


# ─── two-panel area builder + X-strip drag (mirrors test_x_axis_zoom_pan.py) ─────


def _two_panel_area(qtbot: QtBot):  # type: ignore[no-untyped-def]
    """実表示の GraphAreaView (1 タブ・2 パネル・各 v=t 線形信号)。既定ファクトリなので
    X-sync getter/setter が注入され、空白メニューに「X軸同期」項目が出る。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.graph_area_view import GraphAreaView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    d = Path(tempfile.mkdtemp())
    csv = d / "lin.csv"
    rows = ["t,lin"] + [f"{i / 50.0:.4f},{i / 50.0:.4f}" for i in range(50)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    session = Session()
    session.load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    signal_key = sorted(s.name for s in session.signals())[0]
    area_vm = GraphAreaVM(AppViewModel(session))
    area_vm.add_panel(0)  # tab 0 → 2 panels
    for p in area_vm.panels(0):
        p.add_signal_to_axis(signal_key, 0)

    view = GraphAreaView(area_vm)
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    view.setGeometry(screen.x() + 50, screen.y() + 40, 940, 800)
    view.show()
    view.raise_()
    view.activateWindow()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()

    splitter = view.tabs.widget(0)
    panels = [
        splitter.widget(i)
        for i in range(splitter.count())
        if isinstance(splitter.widget(i), GraphPanelView)
    ]
    assert len(panels) == 2
    qtbot.waitUntil(
        lambda: all(
            p._view_boxes[0].sceneBoundingRect().height() > 100 for p in panels
        ),
        timeout=3000,
    )
    return view, panels


def _x_strip_drag(panel, y_frac: float) -> None:  # type: ignore[no-untyped-def]
    """panel の X ストリップ上を左→右に実ドラッグ (y_frac=0.25 → 内側=範囲選択ズーム)。"""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    plot_rect = panel._plot_rect_in_widget()
    bottom = plot_rect.bottom()
    strip_h = float(panel.height()) - bottom
    wy = bottom + strip_h * y_frac
    left_wx = plot_rect.left() + plot_rect.width() * 0.30
    right_wx = plot_rect.left() + plot_rect.width() * 0.70

    dpr = panel.devicePixelRatioF()
    gp_start = panel.mapToGlobal(QPoint(int(left_wx), int(wy)))
    gp_end = panel.mapToGlobal(QPoint(int(right_wx), int(wy)))
    gx_start = round(gp_start.x() * dpr)
    gy = round(gp_start.y() * dpr)
    gx_end = round(gp_end.x() * dpr)

    at(gx_start, gy, LDOWN)
    time.sleep(0.05)
    steps = max(3, abs(gx_end - gx_start) // 8)
    for k in range(1, steps + 1):
        at(gx_start + (gx_end - gx_start) * k // steps, gy, MOVE)
        QApplication.processEvents()
        time.sleep(0.03)
    at(gx_end, gy, LUP)
    for _ in range(5):
        QApplication.processEvents()
        time.sleep(0.02)


# ─── test ────────────────────────────────────────────────────────────────────


def test_x_sync_menu_enables_then_zoom_propagates(qtbot: QtBot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """X-sync OFF 確認 → 実右クリック「X軸同期」ON → 片パネル実ズーム → 兄弟が追随。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view, panels = _two_panel_area(qtbot)
    p0, p1 = panels[0], panels[1]

    # X-sync を明示 OFF にして「OFF から」始める (既定 True の逆を起点)。
    view.vm.set_x_sync(0, False)
    for _ in range(3):
        QApplication.processEvents()
    assert view.vm.tabs()[0].x_sync_enabled is False, "起点で X-sync が OFF でない"

    assert p0.vm.x_range is not None and p1.vm.x_range is not None
    lo0_init, hi0_init = p0.vm.x_range
    orig_span = hi0_init - lo0_init

    # 空白右クリックメニューから「X軸同期」を実クリックして ON。
    vb0 = p0._view_boxes[0]
    rect = vb0.sceneBoundingRect()
    # 曲線 (v=t 対角) から離れた左上寄りの空白点 (data-y 高 / data-x 低)。
    sx = rect.x() + rect.width() * 0.25
    sy = rect.y() + rect.height() * 0.15
    phys = to_phys(p0, sx, sy)

    shot_menu = tmp_path / "x_sync_menu.png"
    captured = _open_menu_click_item(p0, phys, _SYNC_LABEL, shot_menu)

    for _ in range(4):
        QApplication.processEvents()
        time.sleep(0.02)

    assert captured.get("type") == "QMenu", (
        "空白実右クリックで build_context_menu が開かない (曲線/軸メニューに逸れた?): "
        f"{captured.get('type')!r}. screenshot: {shot_menu}"
    )
    assert _SYNC_LABEL in (captured.get("actions") or []), (
        f"空白メニューに「{_SYNC_LABEL}」が無い: {captured.get('actions')!r}"
    )
    assert captured.get("clicked"), "「X軸同期」の実クリックが発火しなかった"
    assert view.vm.tabs()[0].x_sync_enabled is True, (
        "「X軸同期」の実クリックで X-sync が ON にならない (メニュー項目が VM を駆動していない)。"
        f" screenshot: {shot_menu}"
    )

    # ON の状態で panel-0 を実 X ズーム → panel-1 が追随するはず。
    _x_strip_drag(p0, y_frac=0.25)

    shot_after = tmp_path / "x_sync_after_zoom.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_after))

    assert p0.vm.x_range is not None and p1.vm.x_range is not None
    after_span = p0.vm.x_range[1] - p0.vm.x_range[0]
    assert after_span < orig_span * 0.9, (
        f"panel-0 で実ズームが起きていない (span={after_span:.4f} orig={orig_span:.4f})。"
        f" screenshot: {shot_after}"
    )
    assert p1.vm.x_range == pytest.approx(p0.vm.x_range), (
        "X-sync ON にしたのに兄弟パネルの x_range が追随しない: "
        f"p0={p0.vm.x_range} p1={p1.vm.x_range}. screenshot: {shot_after}"
    )
