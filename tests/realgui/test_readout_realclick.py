"""Layer C: CursorReadout ペインの右クリックメニューを実 OS 入力で検証(増分3b -> readout-pane)。

readout-pane Task 4 で CursorReadout の所有が GraphPanelView から GraphAreaView の
単一ペイン(``area.readout_pane``)へ移った。旧 ✕ ボタン(close_button())は撤去済みで、
全消去は右クリックメニュー「カーソルを消す」に一本化されている(``build_readout_menu``)。
ここは「実ディスプレイに映って実 OS 入力で効く」ことのみを証拠化する
(memory gui_realgui_synthetic_click_mislabeled_layer_c)。

再利用: tests/gui/_panel_factory.make_two_axis_area・test_global_cursor.py の
_shown_panel 作法・test_axis_menu_offset.py の _menu_hang_watchdog/_open_menu_click_item
モーダルメニューパターン(module-local 忠実コピー)。
"""

from __future__ import annotations

import contextlib
import threading
import time

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    RDOWN,
    RUP,
    VK_ESCAPE,
    at,
    skip_unless_real_display,
)
from tests.realgui._realgui_input import key as key_input

pytestmark = pytest.mark.realgui


def _menu_hang_watchdog(stop: threading.Event) -> None:
    """Force-close a stuck ``QMenu.exec()`` modal loop by sending a real Escape.

    ``contextMenuEvent`` calls ``menu.exec(globalPos)`` synchronously — a *nested*
    Qt event loop. If the real click on a menu row misses its target (wrong
    geometry, DPI mismatch, or the right-click never raised the menu at all),
    nothing closes the popup and the nested ``menu.exec()`` blocks forever; the
    caller's outer ``QTimer.singleShot(5000, loop.quit)`` safety net only reaches
    the OUTER loop and cannot unwind the nested exec(). QMenu treats Escape as
    "close", so this daemon thread sends ``VK_ESCAPE`` after a deadline and the
    test then fails on a clean assertion instead of hanging. Ground truth for
    "did it hang" is whether the caller's ``loop.exec()`` returned: the caller
    sets ``stop`` immediately after, so in the happy path this thread sees
    ``stop`` well before its deadline and never fires. (module-local copy of the
    helper established in test_axis_menu_offset.py — kept per-file to avoid
    cross-test-module imports.)
    """
    deadline = time.time() + 4.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.1)
    if not stop.is_set():
        key_input(VK_ESCAPE)


def _open_menu_click_item(dpr_widget, phys, item_text, shot_menu):  # type: ignore[no-untyped-def]
    """Real right-click at *phys*, screenshot the popup, then real-click its row
    labelled *item_text*. Returns the captured dict {type, actions, clicked}.

    Mirrors the established modal-menu pattern (test_axis_menu_offset.py::
    _open_menu_click_item): the QMenu opens inside contextMenuEvent's synchronous
    exec(), and the capture singleShot fires *inside* that nested modal loop. The
    clicked-row rect is mapped to physical pixels via popup.mapToGlobal x DPR
    (widget-space convention). A menu-hang watchdog guards against the click
    missing its target.
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    px, py = phys
    captured: dict[str, object] = {}
    loop = QEventLoop()

    def _do_right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)
        # The context-menu QMenu.exec() opens here (real OS WM_CONTEXTMENU);
        # _capture_and_click (a later singleShot) runs inside its modal loop.

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
                # Firing at the rect is NOT proof it landed/dismissed the menu
                # (menu.exec() may still be blocked; see _menu_hang_watchdog).
                # The real evidence is the per-test effect assertion.
                captured["clicked"] = True
        loop.quit()

    stop = threading.Event()
    watchdog = threading.Thread(target=_menu_hang_watchdog, args=(stop,), daemon=True)
    watchdog.start()

    QTimer.singleShot(300, _do_right_click)
    QTimer.singleShot(900, _capture_and_click)
    QTimer.singleShot(5000, loop.quit)  # outer safety net
    loop.exec()

    # loop.exec() returned -> any nested menu.exec() already unwound; stop the
    # watchdog before it can fire a stray Escape at a later test/dialog.
    stop.set()
    watchdog.join(timeout=2.0)
    return captured


def _shown_area(qtbot: QtBot):
    """Real-display GraphAreaView (one tab/panel, two signals/axes) + its panel.

    Returns (area, panel) — ``panel`` is the sole GraphPanelView so tests can
    drive its VM (cursor placement) directly, while the readout pane under test
    lives on ``area.readout_pane`` (readout-pane Task 4 moved ownership there).
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_area

    area = make_two_axis_area()
    qtbot.addWidget(area)
    area.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    area.setGeometry(screen.x() + 60, screen.y() + 60, 900, 620)
    area.show()
    area.raise_()
    area.activateWindow()
    qtbot.waitExposed(area)
    for _ in range(3):
        QApplication.processEvents()
    panel = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    qtbot.waitUntil(
        lambda: panel._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return area, panel


def _widget_center_phys(view, w) -> tuple[int, int]:
    """物理スクリーン中心座標(w は view と同じトップレベルウィンドウ内の子ウィジェット)。"""
    from PySide6.QtCore import QPoint

    dpr = view.devicePixelRatioF()
    gp = w.mapToGlobal(QPoint(w.width() // 2, w.height() // 2))
    return round(gp.x() * dpr), round(gp.y() * dpr)


def test_real_right_click_readout_clear_clears(qtbot: QtBot, tmp_path) -> None:
    """A カーソル設置 → readout ペインを実右クリック → 「カーソルを消す」実クリック
    → カーソル消滅。

    旧 ✕ ボタン単クリック経路(close_button())は readout-pane 化で撤去され、全消去は
    build_readout_menu() の「カーソルを消す」に一本化された。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    area, panel = _shown_area(qtbot)
    panel.vm.x_range = panel.vm.x_range or (0.0, 1.0)
    panel.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    assert panel.cursor_line_visible()

    phys = _widget_center_phys(area, area.readout_pane)
    shot_menu = tmp_path / "readout_menu_clear.png"
    captured = _open_menu_click_item(area, phys, "カーソルを消す", shot_menu)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "readout_closed.png")
        )
    assert captured.get("type") == "QMenu", (
        "real right-click on the readout pane did not raise the readout menu "
        f"(got {captured.get('type')!r}). screenshot: {shot_menu}"
    )
    actions = captured.get("actions") or []
    assert "カーソルを消す" in actions, (
        f"readout menu missing 'カーソルを消す': {actions!r}"
    )
    assert captured.get("clicked"), "real click on 'カーソルを消す' failed to fire"
    assert not panel.cursor_line_visible()


def test_real_right_click_readout_copy(qtbot: QtBot, tmp_path) -> None:
    """A カーソル設置 → readout ペインを実右クリック → 「表をコピー」実クリック → clipboard に TSV。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    area, panel = _shown_area(qtbot)
    panel.vm.x_range = panel.vm.x_range or (0.0, 1.0)
    panel.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    QApplication.clipboard().clear()
    phys = _widget_center_phys(area, area.readout_pane)
    shot = tmp_path / "readout_menu.png"
    captured = _open_menu_click_item(area, phys, "表をコピー", shot)
    for _ in range(5):
        QApplication.processEvents()
    assert captured.get("type") == "QMenu"
    assert "表をコピー" in (captured.get("actions") or [])
    assert QApplication.clipboard().text() != ""  # TSV がコピーされた
