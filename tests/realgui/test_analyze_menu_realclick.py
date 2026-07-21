"""Layer C: Analyze メニュー「カーソル A」の実 OS クリック (UX-04 根治の実証)。

計測 IA 刷新 (spec §2.2) で Analyze メニューは空メニュー (UX-04) から解析系
QAction (カーソル A/B/消去/補間) を掲載する実体を得た。ここでは実アプリで
カーソル A を設置した状態から **実 OS でメニューバーの Analyze を開き「カーソル A」を
実クリック** し、チェック済み項目のトグルでカーソル線が消えることを検証する
(メニューが本当に配線され、アクティブパネルへ dispatch される実経路の証明)。

メニューバーのメニューは contextMenuEvent の ``menu.exec()`` と違い modal ネスト
ループを張らない (popup 追従) ため、test_theme_menu_realclick.py と同型に
``activePopupWidget`` を待って段階駆動する。合成 ``action.trigger()`` は
メニューバー→popup→行クリックの実経路 (前面化・座標・dispatch) を丸ごと迂回する。
"""

from __future__ import annotations

import contextlib
import tempfile
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


def _phys_center(widget, rect) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    dpr = widget.devicePixelRatioF()
    gp = widget.mapToGlobal(rect.center())
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _window_with_cursor(qtbot: QtBot):  # type: ignore[no-untyped-def]
    """MainWindow (2 信号・A カーソル設置済み) を実ディスプレイに前面表示する。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.app import build_main_window
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1,s2"] + [
        f"{i * 0.01:.3f},{i % 50}.0,{(i * 2) % 50}.0" for i in range(50)
    ]
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
            signal_end_column=2,
            has_header=True,
        ),
    )
    keys = sorted(s.name for s in session.signals())

    window = build_main_window(app_vm=AppViewModel(session))
    qtbot.addWidget(window)
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(screen.x() + 50, screen.y() + 50, 1120, 760)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    for _ in range(3):
        QApplication.processEvents()

    pvm = window.graph_area_view.active_panel_vm()
    assert pvm is not None
    pvm.add_signal_to_axis(keys[0], 0)
    pvm.create_new_axis(keys[1])
    for _ in range(3):
        QApplication.processEvents()

    # 実ディスプレイでは show 直後にレイアウトが確定しない — viewbox が確定して
    # (height>100) から A を設置しないとカーソル線が実表示されない (global_cursor 同型)。
    panel = window.graph_area_view.tabs.widget(0).widget(0)
    qtbot.waitUntil(
        lambda: panel._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    pvm.x_range = pvm.x_range or (0.0, 0.5)
    pvm.toggle_main_cursor(True)  # A を表示範囲中央に設置
    for _ in range(3):
        QApplication.processEvents()

    return window, pvm, panel


def test_analyze_cursor_a_real_click_clears_cursor(qtbot: QtBot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Analyze→「カーソル A」を実クリック → チェック済み項目のトグルで A 線が消滅。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    window, pvm, panel = _window_with_cursor(qtbot)
    assert panel.cursor_line_visible(), "A カーソル線が事前に表示されていない"
    assert pvm.cursor_t is not None

    # メニューバーの Analyze を実クリックして開く。
    menubar = window.menuBar()
    analyze_action = next(a for a in menubar.actions() if "Analyze" in a.text())
    _click(*_phys_center(menubar, menubar.actionGeometry(analyze_action)))
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None, timeout=3000)
    menu = QApplication.activePopupWidget()

    shot_menu = tmp_path / "analyze_menu_open.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_menu))

    actions = [a.text() for a in menu.actions()]
    assert "カーソル A" in actions, (
        f"Analyze メニューに「カーソル A」が無い (UX-04 空メニューのまま?): {actions!r}. "
        f"screenshot: {shot_menu}"
    )
    cursor_a = next(a for a in menu.actions() if a.text() == "カーソル A")
    # aboutToShow の同期で A 設置済み → チェック済みのはず (クリックで OFF になる)。
    assert cursor_a.isChecked(), "A 設置済みなのに「カーソル A」が未チェック"

    # 「カーソル A」の行を実クリック (チェック済みをトグル → toggle_main_cursor(False))。
    _click(*_phys_center(menu, menu.actionGeometry(cursor_a)))
    for _ in range(6):
        QApplication.processEvents()
        time.sleep(0.02)

    shot_after = tmp_path / "analyze_menu_after.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_after))

    assert pvm.cursor_t is None, (
        "Analyze「カーソル A」の実クリックで A カーソルが消えない "
        f"(cursor_t={pvm.cursor_t!r})。メニューがアクティブパネルへ dispatch されていない "
        f"可能性。screenshots: {shot_menu}, {shot_after}"
    )
    # カーソル消去でパネル view が rebuild され得るため、可視性は現行の widget を
    # 再取得して確認する (手元の panel 参照は破棄済みのことがある)。
    panel_now = window.graph_area_view.tabs.widget(0).widget(0)
    assert not panel_now.cursor_line_visible(), (
        f"A カーソル線がまだ見えている。screenshots: {shot_menu}, {shot_after}"
    )
