# ruff: noqa: RUF002
"""Layer C (realgui) — 軸/曲線右クリックメニューとオフセット導線の実 OS 入力検証。

増分2b (build_axis_menu＋ルーティング軸分岐・曲線メニュー拡張「新しい軸へ移動/
時間オフセット…/オフセットをリセット…」) の merge 前 ①証拠ゲート。合成 qtbot/
QApplication.sendEvent/action.trigger() ではなく実 OS 入力
(``tests/realgui/_realgui_input`` の ``at``/``key``) で GraphPanelView / GraphAreaView を
駆動し、OS -> Qt のヒットテスト/メニュー配送/描画結果を検証する。Layer A/B
(``tests/gui/test_graph_panel_view.py`` の軸メニュー/曲線メニュー) は
``contextMenuEvent`` を直接呼ぶため OS 由来の欠落 (右クリックが軸スパインで消費される・
pyqtgraph 既定メニューが勝つ 等) を検出できない — ここはその実経路版。

メニュー navigation は実 OS 入力 (右クリック→メニュー行を実クリック)。終端の
数値/スコープダイアログはネイティブモーダルのため realgui では駆動せず DI スタブを
構築時に注入する (spec §4.3・memory gui_realgui_qaction_slot_patch_before_construction)。
右クリックがメニューを開かず外れた場合の ``menu.exec()`` 無限ハングは
``_menu_hang_watchdog`` (Escape 送出) で clean-fail に倒す (2a Task 8 の教訓・memory
gui_realgui_drag_qtimer_hang と同種の nested-exec ハング)。
"""

from __future__ import annotations

import contextlib
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPointF
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


# ─── shared harness (mirrors tests/realgui/test_curve_direct_ops.py) ───────────


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
    test_curve_direct_ops.py — kept per-file to avoid cross-test-module imports.)
    """
    deadline = time.time() + 4.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.1)
    if not stop.is_set():
        key_input(VK_ESCAPE)


def _show(qtbot: QtBot, view, w: int = 820, h: int = 620) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    ww = min(w, screen.width() - 120)
    hh = min(h, screen.height() - 120)
    view.setGeometry(screen.x() + 60, screen.y() + 60, ww, hh)
    view.show()
    view.raise_()
    view.activateWindow()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()


def _wait_panel_laid_out(qtbot: QtBot, panel) -> None:  # type: ignore[no-untyped-def]
    qtbot.waitUntil(
        lambda: (
            bool(panel._view_boxes)
            and panel._view_boxes[0].sceneBoundingRect().height() > 100
        ),
        timeout=3000,
    )


def _spine_center_phys(panel, axis_index: int) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """Physical screen point at the CENTRE of *axis_index*'s Y-axis spine.

    The spine is a scene item drawn in the fixed-width gutter LEFT of the plot
    (memory gui_region_overlay_viewbox_fixed_axis_spine_height), so its scene
    centre maps back — via the same plot_widget.mapFromScene transform that
    _plot_rect_in_widget uses — to a widget point with ``x < plot_rect.left()``:
    ZONE_Y_INNER/OUTER, which contextMenuEvent routes to build_axis_menu. Derived
    from the axis geometry, not a magic ratio (same recipe as
    test_click_activate_axis._spine_center_phys).
    """
    spine = panel._y_axes[axis_index].sceneBoundingRect()
    return to_phys(panel, spine.center().x(), spine.center().y())


def _curve_point_phys(panel, eid: int, frac: float = 0.5) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """Physical screen point ON *eid*'s curve at fraction *frac* of its data.

    curve_xy (data coords) -> ViewBox.mapViewToScene (scene) -> to_phys (widget
    space), per the widget-space convention in memory
    gui_realgui_zone_widgetspace_and_offscreen_clamp. Same helper shape as
    test_curve_direct_ops.py.
    """
    xs, ys = panel.curve_xy(eid)
    i = int(len(xs) * frac)
    vb = panel._item_vb[eid]
    scene = vb.mapViewToScene(QPointF(float(xs[i]), float(ys[i])))
    return to_phys(panel, scene.x(), scene.y())


def _open_menu_click_item(dpr_widget, phys, item_text: str, shot_menu: Path):  # type: ignore[no-untyped-def]
    """Real right-click at *phys*, screenshot the popup, then real-click its
    row labelled *item_text*. Returns the captured dict {type, actions, clicked}.

    Mirrors the established modal-menu pattern (test_curve_direct_ops.py::
    test_real_right_click_menu_hide_removes_curve / test_graph_panel_menu_realclick.py):
    the QMenu opens inside contextMenuEvent's synchronous exec(), and the capture
    singleShot fires *inside* that nested modal loop. The clicked-row rect is
    mapped to physical pixels via popup.mapToGlobal × DPR (widget-space
    convention). A menu-hang watchdog guards against the click missing its target.
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


# ─── panel builders ───────────────────────────────────────────────────────────


def _two_curve_one_axis_panel():  # type: ignore[no-untyped-def]
    """Standalone GraphPanelView with TWO crossing signals on ONE axis.

    ``a`` rises 0→1 and ``b`` falls 1→0, so both fit the SAME auto-fit y-range
    ([0, 1] — set by the first-added signal; _auto_fit_ranges only fits an axis
    while its y_range is None, so a 2nd signal outside the 1st's range would
    render off-screen). They cross at the centre but are well separated
    (>> CURVE_HIT_TOL_PX) away from it, so a click at frac≈0.25 resolves
    unambiguously to ``b``. Returns (view, signal_key_a, signal_key_b).
    """
    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import GraphPanelView

    d = Path(tempfile.mkdtemp())
    csv = d / "two.csv"
    rows = ["t,a,b"] + [
        f"{i / 50.0:.4f},{i / 49.0:.4f},{1.0 - i / 49.0:.4f}" for i in range(50)
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
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(keys[0], 0)
    vm.add_signal_to_axis(keys[1], 0)  # both on axis 0 → one axis, two curves
    return GraphPanelView(vm), keys[0], keys[1]


def _area_one_curve(qtbot: QtBot):  # type: ignore[no-untyped-def]
    """GraphAreaView with a single tab/panel/curve; the panel's offset dialog is a
    DI stub returning (+0.5 s, 'signal').

    Real GraphAreaView wiring (_wire_panel) connects offset_apply_requested →
    GraphAreaVM.apply_offset → AppViewModel broadcast 'offsets' → every panel
    re-renders shifted. Injecting the dialog fn via panel_factory keeps the menu
    navigation real while the terminal numeric modal is a stub (no native modal in
    realgui). Same end-to-end path proven by test_offset_drag.py, triggered here
    via the curve menu instead of a drag. Returns (area_view, panel, signal_key).
    """
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_area_view import GraphAreaView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    d = Path(tempfile.mkdtemp())
    csv = d / "lin.csv"
    rows = ["t,lin"] + [f"{i / 50.0:.4f},{i / 50.0:.4f}" for i in range(50)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    app = AppViewModel()
    app.request_load(
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
    signal_key = sorted(s.name for s in app.signals())[0]
    area_vm = GraphAreaVM(app)
    area_vm.panels(0)[0].add_signal_to_axis(signal_key, 0)

    def _factory(pvm: GraphPanelVM) -> GraphPanelView:
        return GraphPanelView(
            pvm, offset_input_dialog_fn=lambda _sk, _cur: (0.5, "signal")
        )

    view = GraphAreaView(area_vm, panel_factory=_factory)
    _show(qtbot, view, w=760, h=560)
    splitter = view.tabs.widget(0)
    panels = [
        splitter.widget(i)
        for i in range(splitter.count())
        if isinstance(splitter.widget(i), GraphPanelView)
    ]
    assert len(panels) == 1
    _wait_panel_laid_out(qtbot, panels[0])
    for _ in range(3):
        QApplication.processEvents()
    return view, panels[0], signal_key


# ─── Step 1: 軸メニュー「軸を削除」 ─────────────────────────────────────────────


def test_real_right_click_axis_delete_removes_axis(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """軸1のガター (スパイン) を実右クリック → メニュー「軸を削除」を実クリック → 軸が1本消える。

    右クリックがメニューを開かず軸スパインで消費されたり pyqtgraph 既定が勝った場合は
    captured["type"] != "QMenu" で clean-fail する (Layer A/B の contextMenuEvent 直呼び
    では検出できない OS 経路の欠落を狙う)。
    """
    skip_unless_real_display()
    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    _show(qtbot, view)
    _wait_panel_laid_out(qtbot, view)
    assert len(view.vm.axes) == 2

    target = _spine_center_phys(view, 1)
    shot_menu = tmp_path / "axis_menu_00_open.png"
    captured = _open_menu_click_item(view, target, "軸を削除", shot_menu)

    _pump_n(6)
    shot_after = tmp_path / "axis_menu_01_after_delete.png"
    from PySide6.QtWidgets import QApplication

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_after))

    assert captured.get("type") == "QMenu", (
        "real right-click on axis 1's gutter did not raise the axis menu (got "
        f"{captured.get('type')!r}) — event may be swallowed by the axis item or "
        f"pyqtgraph's default. screenshot: {shot_menu}"
    )
    actions = captured.get("actions") or []
    assert "軸を削除" in actions, f"axis menu missing '軸を削除': {actions!r}"
    assert captured.get("clicked"), "real click on '軸を削除' failed to fire"
    assert len(view.vm.axes) == 1, (
        "axis was not removed after a real click on '軸を削除' "
        f"(vm.axes={len(view.vm.axes)}). screenshots: {shot_menu}, {shot_after}"
    )


# ─── Step 2: 曲線メニュー「時間オフセット…」 ────────────────────────────────────


def test_real_curve_menu_offset_shifts_curve(qtbot: QtBot, tmp_path: Path) -> None:
    """曲線を実右クリック → 「時間オフセット…」を実クリック → DI ダイアログが (0.5,'signal') を
    返す → 実 offset ブロードキャストで曲線が右へ水平シフトする (before/after スクショ)。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    _view, panel, signal_key = _area_one_curve(qtbot)
    eid = panel.entry_id_for(signal_key)
    x_before = np.asarray(panel.curve_xy(eid)[0]).copy()
    shot_before = tmp_path / "curve_offset_00_before.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_before))

    target = _curve_point_phys(panel, eid)
    shot_menu = tmp_path / "curve_offset_01_menu.png"
    captured = _open_menu_click_item(panel, target, "時間オフセット…", shot_menu)

    # Pump so the offset_apply_requested → apply_offset → 'offsets' broadcast →
    # panel.refresh() chain completes and curve_xy reflects the shift.
    qtbot.waitUntil(
        lambda: (
            float(np.asarray(panel.curve_xy(eid)[0]).min())
            > float(x_before.min()) + 1e-3
        ),
        timeout=3000,
    )
    shot_after = tmp_path / "curve_offset_02_after.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_after))

    assert captured.get("type") == "QMenu", (
        f"real right-click did not raise the curve menu (got "
        f"{captured.get('type')!r}). screenshot: {shot_menu}"
    )
    actions = captured.get("actions") or []
    assert "時間オフセット…" in actions, (
        f"curve menu missing '時間オフセット…': {actions!r}"
    )
    assert captured.get("clicked"), "real click on '時間オフセット…' failed to fire"
    x_after = np.asarray(panel.curve_xy(eid)[0])
    assert float(x_after.min()) > float(x_before.min()) + 1e-3, (
        "curve did not shift right after the offset dialog returned +0.5 s. "
        f"screenshots: {shot_before}, {shot_after}"
    )


# ─── Step 3: 曲線メニュー「新しい軸へ移動」 ─────────────────────────────────────


def test_real_curve_menu_move_to_new_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """2曲線1軸パネルで曲線bを実右クリック → 「新しい軸へ移動」を実クリック → 軸が2本に増える。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view, _key_a, key_b = _two_curve_one_axis_panel()
    _show(qtbot, view)
    _wait_panel_laid_out(qtbot, view)
    assert len(view.vm.axes) == 1
    eid_b = view.entry_id_for(key_b)

    # frac≈0.25 (NOT 0.5): a and b cross at the centre, so hit off-centre where
    # b (~0.76) is well clear of a (~0.24).
    target = _curve_point_phys(view, eid_b, frac=0.25)
    shot_menu = tmp_path / "curve_move_00_menu.png"
    captured = _open_menu_click_item(view, target, "新しい軸へ移動", shot_menu)

    _pump_n(6)
    shot_after = tmp_path / "curve_move_01_two_axes.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_after))

    assert captured.get("type") == "QMenu", (
        f"real right-click did not raise the curve menu (got "
        f"{captured.get('type')!r}). screenshot: {shot_menu}"
    )
    actions = captured.get("actions") or []
    assert "新しい軸へ移動" in actions, (
        f"curve menu missing '新しい軸へ移動': {actions!r}"
    )
    assert captured.get("clicked"), "real click on '新しい軸へ移動' failed to fire"
    assert len(view.vm.axes) == 2, (
        "a new axis was not created after a real click on '新しい軸へ移動' "
        f"(vm.axes={len(view.vm.axes)}). screenshots: {shot_menu}, {shot_after}"
    )


# ─── FU-09: 軸メニュー中心基準ズーム (Y軸 build_axis_menu / X軸 build_x_axis_menu) ──


def _x_strip_center_phys(panel):  # type: ignore[no-untyped-def]
    """Physical screen point at the centre of the bottom X (time) axis strip.

    _x_axis is a scene AxisItem drawn below the plot; its scene centre maps back
    (same to_phys transform as _spine_center_phys) to a widget point with
    ``py > plot_rect.bottom()`` -> ZONE_X_INNER/OUTER, which contextMenuEvent
    routes to build_x_axis_menu (FU-09).
    """
    strip = panel._x_axis.sceneBoundingRect()
    return to_phys(panel, strip.center().x(), strip.center().y())


def test_real_right_click_y_axis_zoom_in_shrinks_range(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """軸0のガター (スパイン) を実右クリック → メニュー「ズームイン」を実クリック → Y軸レンジが
    中心保持で 10% 縮小する (half*0.9)。Layer B の contextMenuEvent 直呼びでは通らない
    OS 経路 (右クリック配送→メニュー→実項目クリック) を検証する。
    """
    skip_unless_real_display()
    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    _show(qtbot, view)
    _wait_panel_laid_out(qtbot, view)
    before = view.vm.axes[0].y_range
    assert before is not None, "axis 0 has no y_range to zoom"
    before_center = (before[0] + before[1]) / 2.0
    before_half = (before[1] - before[0]) / 2.0

    target = _spine_center_phys(view, 0)
    shot_menu = tmp_path / "y_zoom_00_menu.png"
    captured = _open_menu_click_item(view, target, "ズームイン", shot_menu)
    _pump_n(6)

    assert captured.get("type") == "QMenu", (
        "real right-click on axis 0's gutter did not raise the axis menu (got "
        f"{captured.get('type')!r}). screenshot: {shot_menu}"
    )
    actions = captured.get("actions") or []
    assert "ズームイン" in actions, f"axis menu missing 'ズームイン': {actions!r}"
    assert captured.get("clicked"), "real click on 'ズームイン' failed to fire"
    after = view.vm.axes[0].y_range
    assert after is not None
    after_center = (after[0] + after[1]) / 2.0
    after_half = (after[1] - after[0]) / 2.0
    assert after_half == pytest.approx(before_half * 0.9, rel=1e-6), (
        f"Y range half did not shrink 10% (before {before_half}, after {after_half}). "
        f"screenshot: {shot_menu}"
    )
    assert after_center == pytest.approx(before_center, rel=1e-6, abs=1e-9), (
        "Y zoom did not preserve the axis centre"
    )


def test_real_right_click_x_axis_zoom_in_shrinks_range(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """X軸ストリップを実右クリック → build_x_axis_menu の「ズームイン」を実クリック → X軸レンジが
    中心保持で 10% 縮小する。ZONE_X ルーティング (contextMenuEvent の新分岐) の実 OS 経路検証。
    """
    skip_unless_real_display()
    from tests.gui._panel_factory import make_two_axis_panel

    view = make_two_axis_panel()
    _show(qtbot, view)
    _wait_panel_laid_out(qtbot, view)
    before = view.vm.x_range
    assert before is not None, "panel has no x_range to zoom"
    before_center = (before[0] + before[1]) / 2.0
    before_half = (before[1] - before[0]) / 2.0

    target = _x_strip_center_phys(view)
    shot_menu = tmp_path / "x_zoom_00_menu.png"
    captured = _open_menu_click_item(view, target, "ズームイン", shot_menu)
    _pump_n(6)

    assert captured.get("type") == "QMenu", (
        "real right-click on the X axis strip did not raise the X axis menu (got "
        f"{captured.get('type')!r}). screenshot: {shot_menu}"
    )
    actions = captured.get("actions") or []
    # "X軸をオートフィット" is unique to build_x_axis_menu -> confirms ZONE_X routing.
    assert "X軸をオートフィット" in actions, (
        f"ZONE_X did not route to build_x_axis_menu: {actions!r}"
    )
    assert "ズームイン" in actions, f"X axis menu missing 'ズームイン': {actions!r}"
    assert captured.get("clicked"), "real click on 'ズームイン' failed to fire"
    after = view.vm.x_range
    assert after is not None
    after_center = (after[0] + after[1]) / 2.0
    after_half = (after[1] - after[0]) / 2.0
    assert after_half == pytest.approx(before_half * 0.9, rel=1e-6), (
        f"X range half did not shrink 10% (before {before_half}, after {after_half}). "
        f"screenshot: {shot_menu}"
    )
    assert after_center == pytest.approx(before_center, rel=1e-6, abs=1e-9), (
        "X zoom did not preserve the centre"
    )
