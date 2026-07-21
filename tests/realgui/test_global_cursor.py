"""Layer C: Global_Cursor を実 OS 入力で検証(R15/R16)。--realgui で実行。

新規経路(前例なし): InfiniteLine 実ドラッグ(A 線単独・B 線2線ヒット分離)。
再利用: tests/gui/_panel_factory.make_two_axis_panel、test_active_axis_zoom_pan.py 同形の _to_phys/_at。
"""

from __future__ import annotations

import contextlib
import threading
import time

import pytest
from PySide6.QtCore import QPointF
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    MOVE,
    RDOWN,
    RUP,
    VK_ESCAPE,
    VK_RIGHT,
    at,
    skip_unless_real_display,
    to_phys,
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


def _shown_area(qtbot: QtBot):
    """Real-display GraphAreaView (one tab/panel, two signals/axes) + its panel.

    readout-pane Task 4 moved CursorReadout ownership from GraphPanelView onto
    GraphAreaView's single ``readout_pane``; tests that assert on the readout
    (as opposed to the cursor lines themselves, which stay panel-local) need
    the owning area, not a bare panel. Module-local copy of the pattern in
    test_readout_realclick.py::_shown_area (kept per-file — established
    cross-test-module convention in this directory).
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from tests.gui._panel_factory import make_two_axis_area

    area = make_two_axis_area()
    qtbot.addWidget(area)
    area.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    area.setGeometry(300, 300, 900, 620)
    area.show()
    qtbot.waitExposed(area)
    for _ in range(3):
        QApplication.processEvents()
    panel = area.tabs.widget(0).widget(0)  # type: ignore[attr-defined]
    qtbot.waitUntil(
        lambda: panel._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return area, panel


def test_real_drag_cursor_line_moves_it(qtbot: QtBot, tmp_path) -> None:
    """A 線をトグルで設置→線を右へ実ドラッグ → 描画 x(line.value)が増加(②: 実ドラッグ結果)。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    # 設置はトグル経由(空クリック設置は撤去済み)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible()
    x_before = view.cursor_line_value()
    # A 線の現在位置を起点に右へ実ドラッグ(線上を掴む)
    sx, sy, _ = _scene_center(view)

    rect = view._view_boxes[0].sceneBoundingRect()
    target_sx = rect.x() + rect.width() * 0.75
    gx, gy = to_phys(view, sx, sy)
    tx, _ = to_phys(view, target_sx, sy)
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        at(gx + (tx - gx) * k // steps, gy, MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    at(tx, gy, LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "cursor_dragged.png")
        )
    assert view.cursor_line_value() > x_before


def test_real_drag_sub_cursor_moves_only_b(qtbot: QtBot, tmp_path) -> None:
    """main+delta 表示 → B 線(75%)を実ドラッグ → B が動き A は不変(②: 実ヒットテスト)。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)  # A=50%
    view.vm.toggle_delta(True)  # B=75%
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible() and view.delta_line_visible()
    a_before = view.cursor_line_value()
    b_before = view.delta_line_value()

    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    # B(75%)の画面位置を起点に、さらに右(85%)へ実ドラッグ
    b_scene_x = rect.x() + rect.width() * 0.75
    sy = rect.y() + rect.height() * 0.5
    tgt_scene_x = rect.x() + rect.width() * 0.85
    gx, gy = to_phys(view, b_scene_x, sy)
    tx, _ = to_phys(view, tgt_scene_x, sy)
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        at(gx + (tx - gx) * k // steps, gy, MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    at(tx, gy, LUP)
    for _ in range(5):
        QApplication.processEvents()
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "sub_cursor_dragged.png")
        )
    assert view.delta_line_value() > b_before  # B は右へ動いた
    assert view.cursor_line_value() == pytest.approx(a_before)  # A は不変


def test_real_drag_b_cursor_stats_live_recalc(qtbot: QtBot, tmp_path) -> None:
    """B 線実ドラッグ → CursorReadout 範囲統計がライブ再計算される(R17 ②証拠)。

    A+B 両線設置 → B 線(75%)を 85%へ実ドラッグ。
    - mid-drag: row_texts() が数値統計を含む(「範囲外」/「データなし」でない)
    - before/after でテキストが異なる(ドラッグに追従してライブ再計算された証拠)
    - 最後に primaryScreen.grabWindow(0) → stats_live.png(判読可能フォント確認用)

    honest RED gate: view._cursor_line_b.sigPositionChanged.disconnect(
        view._on_cursor_line_b_dragged)  # graph_panel_view.py L1127
        # (sigPositionChanged.connect(on_dragged) inside _make_cursor_line)
    を挿入すると B ドラッグ後も統計が更新されず texts_before != texts_after が RED になる。

    readout-pane Task 4/5: the readout table now lives on GraphAreaView's single
    ``readout_pane`` (not the panel), so this test drives the panel's cursor VM
    directly but reads ``area.readout_pane.row_texts()``.
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    area, view = _shown_area(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)  # A: 50%
    view.vm.toggle_delta(True)  # B: 75%
    for _ in range(5):
        QApplication.processEvents()
    assert view.cursor_line_visible() and view.delta_line_visible()
    # Task 8 (計測 IA §2.6): readout_visible() は表示トグル状態のみを表し、実可視性は
    # 「トグル ON かつ非収納」。信号が存在するので収納されず、計測モードで実際に見える
    # ことを両観測 API で確認する (readout_stowed 分離への追随・弱体化なし)。
    assert area.readout_visible() and not area.readout_stowed()
    assert area.readout_pane.isVisible()

    # Initial readout at B=75% — used to prove stats CHANGED after drag
    texts_before = area.readout_pane.row_texts()
    assert texts_before, "delta-mode readout should have at least one signal row"

    # Drag B line from 75% → 85% with real OS mouse input
    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    b_scene_x = rect.x() + rect.width() * 0.75
    sy = rect.y() + rect.height() * 0.5
    tgt_scene_x = rect.x() + rect.width() * 0.85
    gx, gy = to_phys(view, b_scene_x, sy)
    tx, _ = to_phys(view, tgt_scene_x, sy)

    texts_mid: list[tuple[str, str]] = []
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    steps = max(4, (abs(tx - gx) + 7) // 8)
    mid = steps // 2
    for k in range(1, steps + 1):
        at(gx + (tx - gx) * k // steps, gy, MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
        if k == mid:
            texts_mid = area.readout_pane.row_texts()
    at(tx, gy, LUP)
    for _ in range(5):
        QApplication.processEvents()

    texts_after = area.readout_pane.row_texts()

    # (1) mid-drag: readout rows are present and contain no placeholder text
    _PLACEHOLDERS = {"範囲外", "データなし", ""}
    assert texts_mid, (
        "mid-drag readout has no rows — delta mode may not be active mid-drag"
    )
    for _name, cell_text in texts_mid:
        for token in cell_text.split():
            assert token not in _PLACEHOLDERS, (
                f"mid-drag readout has placeholder {token!r} in row {_name!r}: {cell_text!r}"
            )

    # (2) stats changed between B=75% (before) and B=85% (after) — proves live recalc
    # [A,B] range expanded → sample count and aggregates differ
    assert texts_before != texts_after, (
        "range stats unchanged after dragging B cursor — live recalc may be broken. "
        f"before={texts_before!r}  after={texts_after!r}"
    )

    # Screenshot for /verify: readable font on real Windows display (offscreen → tofu)
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "stats_live.png")
        )


# ─── 増分3a: 実 ←/→ でカーソルをサンプルスナップ移動 (PC-08) ──────────────────


def test_real_arrow_keys_step_cursor(qtbot: QtBot, tmp_path) -> None:
    """A 線をトグル設置 → ウィンドウを前面/アクティブ化 → 実 → キーで cursor 値が増加。

    実 OS キー (keybd_event VK_RIGHT) が GraphPanelView.keyPressEvent に届き
    vm.step_cursor 経由でカーソルが次サンプルへスナップする経路 (②の load-bearing:
    cursor_line_value の数値変化) を実機で証明する。合成 QTest.keyClick は
    keyPressEvent を直送してしまい、フォーカス/前面化の欠落を見逃す (Layer B 偽装)。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible()

    # Real OS keys only reach the app if its window is the foreground/active
    # window; _shown_panel only sets WindowStaysOnTopHint (visual) so raise +
    # activate here, then land keyboard focus on the View (ClickFocus accepts a
    # programmatic setFocus once the window is active).
    view.raise_()
    view.activateWindow()
    qtbot.waitUntil(view.isActiveWindow, timeout=3000)
    view.setFocus()
    for _ in range(3):
        QApplication.processEvents()
    assert view.hasFocus(), (
        "GraphPanelView did not take keyboard focus — a real arrow key would "
        "not reach keyPressEvent (focus routing defect, not a test artefact)."
    )

    x_before = view.cursor_line_value()
    key_input(VK_RIGHT)  # real OS Key_Right (keybd_event)
    for _ in range(6):
        QApplication.processEvents()
        time.sleep(0.02)
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "arrow_step.png")
        )
    assert view.cursor_line_value() > x_before, (
        "real → key did not advance the cursor to the next sample "
        f"(before={x_before!r}, after={view.cursor_line_value()!r}). The key may "
        "not be reaching GraphPanelView.keyPressEvent (window not active / focus "
        "on a child that consumes arrow keys)."
    )


def test_real_right_click_cursor_line_clears(qtbot: QtBot, tmp_path) -> None:
    """A 線を設置 → 線上を実右クリック → 「カーソルを消す」を実クリック → カーソル消滅。

    contextMenuEvent のカーソル線分岐 (_cursor_line_at → build_cursor_menu) が実 OS
    右クリック経路で機能することを証明する。右クリックがカーソル線で消費されたり
    pyqtgraph 既定メニューが勝った場合は captured["type"] != "QMenu" で clean-fail。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view = _shown_panel(qtbot)
    view.vm.x_range = view.vm.x_range or (0.0, 1.0)
    view.vm.toggle_main_cursor(True)  # A at 50% — inside the visible plot rect
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible()

    # Physical screen point ON the A cursor line: its data-x → scene → widget →
    # physical pixels. y at the plot centre keeps the grab point inside the
    # visible plot rect (memory gui_realgui_offscreen_target_opens_os_system_menu:
    # right-clicking outside the drawn rect opens the OS window menu instead).
    line_x = view.cursor_line_value()
    sx = view._view_boxes[0].mapViewToScene(QPointF(line_x, 0.0)).x()
    _sx, sy, _ = _scene_center(view)
    target = to_phys(view, sx, sy)

    shot_menu = tmp_path / "cursor_menu_00_open.png"
    captured = _open_menu_click_item(view, target, "カーソルを消す", shot_menu)

    for _ in range(6):
        QApplication.processEvents()
        time.sleep(0.02)
    shot_after = tmp_path / "cursor_menu_01_after_clear.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_after))

    assert captured.get("type") == "QMenu", (
        "real right-click on the A cursor line did not raise the cursor menu (got "
        f"{captured.get('type')!r}) — event may be swallowed by the line item or "
        f"pyqtgraph's default. screenshot: {shot_menu}"
    )
    actions = captured.get("actions") or []
    assert "カーソルを消す" in actions, (
        f"cursor menu missing 'カーソルを消す': {actions!r}"
    )
    assert captured.get("clicked"), "real click on 'カーソルを消す' failed to fire"
    assert not view.cursor_line_visible(), (
        "cursor line still visible after a real click on 'カーソルを消す' "
        f"(vm.cursor_t={view.vm.cursor_t!r}). screenshots: {shot_menu}, {shot_after}"
    )
