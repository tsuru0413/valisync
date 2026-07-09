# ruff: noqa: RUF002
"""Layer C (realgui) — X 方向グリッド表示トグルの実 OS 入力検証 (PC-15 / 増分4)。

プロット空白部を実右クリック → build_context_menu の「グリッド」を実クリックし、
`_x_axis.grid` が有効化されることと、**スクリーンショットに縦グリッド線が実描画**
されることを検証する。`_x_axis.grid` の truthy 値は「setGrid を呼んだ」証拠に過ぎない
ため、ピクセルの正しさ (縦線が本当に描かれたか) は realgui のスクショ目視でのみ誠実に
証明できる (memory gui_offscreen_grab_text_tofu の教訓で QT_QPA_PLATFORM=windows)。

合成 qtbot.mouseClick / action.trigger() ではなく実 OS 入力 (tests/realgui/_realgui_input
の at / RDOWN / RUP / LDOWN / LUP) で右クリック→メニュー行クリックを駆動する。右クリックが
メニューを開かず外れた場合の menu.exec() 無限ハングは _menu_hang_watchdog (Escape 送出) で
clean-fail に倒す。_open_menu_click_item / _menu_hang_watchdog は
tests/realgui/test_axis_menu_offset.py の確立パターンを module-local に忠実コピーしたもの。
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
    RDOWN,
    RUP,
    VK_ESCAPE,
    at,
    skip_unless_real_display,
    to_phys,
)
from tests.realgui._realgui_input import key as key_input

pytestmark = pytest.mark.realgui


# ─── shared harness (faithful module-local copy of test_axis_menu_offset.py) ───


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _pump_n(n: int, dt: float = 0.02) -> None:
    for _ in range(n):
        _pump(dt)


def _menu_hang_watchdog(stop: threading.Event) -> None:
    """Force-close a stuck ``QMenu.exec()`` modal loop by sending a real Escape.

    ``contextMenuEvent`` calls ``menu.exec(globalPos)`` synchronously — a *nested*
    Qt event loop entered from within the caller's outer ``loop.exec()``. If the
    real click on a menu row misses its target (wrong geometry, DPI mismatch, or
    the right-click never raised the menu at all), nothing closes the popup and
    the nested ``menu.exec()`` blocks forever; the caller's outer
    ``QTimer.singleShot(5000, loop.quit)`` safety net only reaches the OUTER loop
    and cannot unwind the nested exec(). QMenu treats Escape as "close", so this
    daemon thread sends ``VK_ESCAPE`` after a deadline and the test then fails on a
    clean assertion instead of hanging. Ground truth for "did it hang" is whether
    the caller's ``loop.exec()`` returned: the caller sets ``stop`` immediately
    after, so in the happy path this thread sees ``stop`` well before its deadline
    and never fires. (module-local copy of the helper established in
    test_axis_menu_offset.py — kept per-file to avoid cross-test-module imports.)
    """
    deadline = time.time() + 4.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.1)
    if not stop.is_set():
        key_input(VK_ESCAPE)


def _open_menu_click_item(dpr_widget, phys, item_text: str, shot_menu: Path):  # type: ignore[no-untyped-def]
    """Real right-click at *phys*, screenshot the popup, then real-click its
    row labelled *item_text*. Returns the captured dict {type, actions, clicked}.

    Mirrors the established modal-menu pattern (test_axis_menu_offset.py::
    _open_menu_click_item): the QMenu opens inside contextMenuEvent's synchronous
    exec(), and the capture singleShot fires *inside* that nested modal loop. The
    clicked-row rect is mapped to physical pixels via popup.mapToGlobal × DPR
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
                # The real evidence is the per-test effect assertion below.
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


# ─── panel builder ─────────────────────────────────────────────────────────────


def _shown_panel(qtbot: QtBot):  # type: ignore[no-untyped-def]
    """Standalone GraphPanelView with ONE signal, shown on-screen and laid out.

    The signal is a triangle peaking at the horizontal centre (0 at both ends,
    1 at the middle), so the curve hugs the TOP at x-centre; the geometric plot
    centre — where the test right-clicks — is then ~half the plot height away
    from the nearest curve sample (>> CURVE_HIT_TOL_PX = 8 px), so
    ``_curve_at`` returns None and ``contextMenuEvent`` routes to
    ``build_context_menu`` (the blank-area menu that carries the checkable
    「グリッド」) rather than the curve menu. One signal is REQUIRED: an empty
    panel has no ``_view_boxes`` and its X axis has no range to draw grid lines
    across, so grid lines would never render. Window placed within
    availableGeometry so the real clicks land on-screen (memory
    gui_realgui_zone_widgetspace_and_offscreen_clamp).
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import GraphPanelView

    d = Path(tempfile.mkdtemp())
    csv = d / "tri.csv"
    n = 50
    rows = ["t,tri"]
    for i in range(n):
        # Triangle peaking at the centre: y = 1 at i=n/2, 0 at the ends → the
        # curve is at the TOP around x-centre, leaving the plot centre clear.
        y = 1.0 - abs(2.0 * i / (n - 1) - 1.0)
        rows.append(f"{i / (n - 1):.4f},{y:.4f}")
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
    key = sorted(s.name for s in session.signals())[0]
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(key, 0)
    view = GraphPanelView(vm)

    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    ww = min(820, screen.width() - 120)
    hh = min(620, screen.height() - 120)
    view.setGeometry(screen.x() + 60, screen.y() + 60, ww, hh)
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


# ─── grid realgui ──────────────────────────────────────────────────────────────


@pytest.mark.realgui
def test_real_grid_menu_draws_vertical_lines(qtbot: QtBot, tmp_path: Path) -> None:
    """空白実右クリック → 「グリッド」実クリック → _x_axis.grid 有効化＋縦線スクショ。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    for _ in range(3):
        QApplication.processEvents()
    assert view._x_axis.grid is False  # 既定 OFF

    # プロット矩形の空白部 (信号・軸ゾーン外) の中央を実右クリック。
    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    sx = rect.x() + rect.width() * 0.5
    sy = rect.y() + rect.height() * 0.5
    px, py = to_phys(view, sx, sy)

    # NOTE: _open_menu_click_item grabs the screen WHILE the menu is open (grid
    # still OFF), so its shot is the menu, not the grid. The load-bearing grid
    # screenshot is grabbed below, AFTER the toggle dismisses the menu.
    shot_menu = tmp_path / "grid_menu.png"
    captured = _open_menu_click_item(view, (px, py), "グリッド", shot_menu)

    # Pump so toggled -> vm.toggle_grid -> notify 'grid' -> _apply_grid ->
    # _x_axis.setGrid(alpha) completes and the plot repaints with grid lines.
    qtbot.waitUntil(lambda: view.vm.grid_enabled is True, timeout=2000)
    _pump_n(6)
    view.plot_widget.repaint()
    _pump_n(2)

    # Honest AFTER screenshot: plot with vertical grid lines, menu dismissed.
    shot_on = tmp_path / "grid_on.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_on))

    assert captured.get("type") == "QMenu", (
        "real right-click on the blank plot area did not raise build_context_menu "
        f"(got {captured.get('type')!r}); may be swallowed / routed to a curve or "
        f"axis menu. screenshot: {shot_menu}"
    )
    assert "グリッド" in (captured.get("actions") or []), (
        f"blank-area menu missing 「グリッド」: {captured.get('actions')!r}"
    )
    assert captured.get("clicked"), "real click on 「グリッド」 failed to fire"
    assert view.vm.grid_enabled is True, "vm.grid_enabled not True after real click"
    # setGrid(alpha) took effect (grid holds the alpha int, was False). The
    # actual vertical lines in shot_on are confirmed by human/AI screenshot review.
    assert view._x_axis.grid, (
        f"_x_axis.setGrid not applied (grid={view._x_axis.grid!r}). screenshot: {shot_on}"
    )
