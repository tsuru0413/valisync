"""Layer C: 曲線の実クリック活性化/H 表示切替/右クリックメニュー/DP16 実ドラッグ (PC-01)。

増分2a (entry_id 化・DP16 ジェスチャ・曲線アクティブ化・H キー・右クリックメニュー) の
merge 前 ①証拠ゲート。合成 qtbot/QApplication.sendEvent/action.trigger() ではなく実
OS 入力 (``tests/realgui/_realgui_input`` の ``at``/``key``) で GraphPanelView 単体を
駆動し、OS -> Qt のヒットテスト/配送/描画結果を検証する (Layer A/B は
``tests/gui/test_graph_panel_view.py`` の TestCurveActivation / TestCurveContextMenu /
``test_h_toggles_active_curve_visibility`` が既にカバーする — ここはそれらの
実経路版で、直接呼び出しでは検出できない OS 由来の欠落だけを狙う)。

DP16 の move 駆動 (offset drag) は grabMouse-at-press が無いと実 OS の move は子
QGraphicsView に消費され親 GraphPanelView に届かない (memory
gui_realgui_move_not_reaching_parent_qwidget)。これは構造的に Layer C でしか
証明できない — Layer B の sendEvent は move を親へ直送するため見逃す
(合成テストはこの欠落があっても green になる)。実ドラッグは別 OS スレッド +
watchdog (memory gui_realgui_drag_qtimer_hang) で駆動する — tests/realgui/
test_offset_drag.py の駆動パターンを再利用する (同ファイルは無回帰確認のため
書き換えない)。
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
    MOVE,
    RDOWN,
    RUP,
    VK_ESCAPE,
    VK_RETURN,
    at,
    skip_unless_real_display,
    to_phys,
)
from tests.realgui._realgui_input import key as key_input

pytestmark = pytest.mark.realgui

VK_H = 0x48  # Win32 VK code for the 'H' key (letter VKs == their ASCII code)


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _pump_n(n: int, dt: float = 0.02) -> None:
    for _ in range(n):
        _pump(dt)


def _build_panel(color_dialog_fn=None):
    """Build a lone GraphPanelView with one linear signal (v=t, t in [0,1)).

    Same data shape as ``tests/gui/_panel_factory.make_single_signal_panel``
    (a straight line through the plot centre, ideal for hit-testing), but the
    view is constructed directly here so an optional ``color_dialog_fn`` stub
    can be injected AT CONSTRUCTION (memory
    gui_realgui_qaction_slot_patch_before_construction: a native QColorDialog
    must never be reachable from realgui — DI has to happen before the widget
    exists, not via a later monkeypatch on an instance method).
    """
    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
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
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(signal_key, 0)
    view = GraphPanelView(vm, color_dialog_fn=color_dialog_fn)
    return view, signal_key


def _show(qtbot: QtBot, view) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    w = min(640, screen.width() - 120)
    h = min(480, screen.height() - 120)
    view.setGeometry(screen.x() + 60, screen.y() + 60, w, h)
    view.show()
    view.raise_()
    view.activateWindow()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: (
            bool(view._view_boxes)
            and view._view_boxes[0].sceneBoundingRect().height() > 100
        ),
        timeout=3000,
    )


def _curve_point_phys(view, eid: int, frac: float = 0.5) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """Physical screen point ON *eid*'s curve at fraction *frac* of its data.

    curve_xy (data coords) -> ViewBox.mapViewToScene (scene coords) ->
    to_phys (widget space via plot_widget.mapFromScene, per the widget-space
    convention in memory gui_realgui_zone_widgetspace_and_offscreen_clamp).
    """
    xs, ys = view.curve_xy(eid)
    i = int(len(xs) * frac)
    vb = view._item_vb[eid]
    scene = vb.mapViewToScene(QPointF(float(xs[i]), float(ys[i])))
    return to_phys(view, scene.x(), scene.y())


def _dialog_dismisser(stop: threading.Event) -> None:
    """Background thread: confirm the real default apply dialog with Enter.

    Mirrors tests/realgui/test_offset_drag.py's ``_dialog_dismisser``: the
    dialog opens via ``QTimer.singleShot(0, ...)`` AFTER the mouse release, so
    this thread must start after LUP (started by the caller), sleeping first
    so the deferred open has completed before Enter is sent. A 3s Escape
    watchdog guards against the dialog never appearing.
    """
    time.sleep(0.5)
    if not stop.is_set():
        key_input(VK_RETURN)
    deadline = time.time() + 3.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.2)
    if not stop.is_set():
        key_input(VK_ESCAPE)


def test_real_click_activates_curve_thick_pen_and_does_not_offset(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """曲線を実クリック (press+release, move無し) -> 活性化 (太線) し、Δt=0 のまま。

    DP16: a press only holds a candidate (_curve_press_candidate); a release
    within startDragDistance activates instead of beginning the offset drag.
    A synthetic sendEvent can deliver press+release directly to
    _curve_press_candidate without ever going through OS hit-testing
    (_curve_at / plot_widget hierarchy) — the real click is what proves the
    OS -> Qt path actually resolves to this curve (Layer A/B already covers
    the DP16 state machine itself: test_graph_panel_view.py::TestCurveActivation).
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view, _signal_key = _build_panel()
    _show(qtbot, view)
    eid = view.curve_keys()[0]
    assert view.active_curve_id() is None
    assert view.pen_width(eid) != 2.5
    x_before = np.asarray(view.curve_xy(eid)[0]).copy()

    px, py = _curve_point_phys(view, eid)
    at(px, py, LDOWN)
    _pump()
    at(px, py, LUP)  # same point, no MOVE -> pure click -> DP16 activation path
    _pump_n(6)

    qtbot.waitUntil(lambda: view.active_curve_id() == eid, timeout=2000)
    shot = tmp_path / "01_curve_active_thick.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot))
    assert view.active_curve_id() == eid, (
        f"real click did not activate the curve. screenshot: {shot}"
    )
    assert view.pen_width(eid) == 2.5, (
        f"activated curve is not thick (width=2.5). screenshot: {shot}"
    )
    # 閾値内クリック = 活性化のみ、オフセットは発生しない (x 配列は不変)。
    x_after = np.asarray(view.curve_xy(eid)[0])
    np.testing.assert_allclose(
        x_after,
        x_before,
        err_msg="within-threshold click must not begin an offset drag",
    )


def test_real_h_key_toggles_curve_visibility(qtbot: QtBot, tmp_path: Path) -> None:
    """活性化済み曲線を実 H キーで非表示 -> 再度実 H キーで再表示 (両方スクショ)。

    非表示は VM の entry.visible=False 経由で render_data から除外される
    (曲線は _items / curve_keys() から消える)。真の OS キーイベントが前面ウィンドウ
    -> フォーカス済み GraphPanelView (ClickFocus, 直前の実クリックで取得) に届く
    ことを検証する。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view, _signal_key = _build_panel()
    _show(qtbot, view)
    eid = view.curve_keys()[0]

    px, py = _curve_point_phys(view, eid)
    at(px, py, LDOWN)
    _pump()
    at(px, py, LUP)
    _pump_n(6)
    qtbot.waitUntil(lambda: view.active_curve_id() == eid, timeout=2000)

    key_input(VK_H)
    _pump_n(8)
    qtbot.waitUntil(lambda: eid not in view.curve_keys(), timeout=2000)
    shot_hidden = tmp_path / "02_h_hidden.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_hidden))
    assert eid not in view.curve_keys(), (
        f"real H key did not hide the active curve. screenshot: {shot_hidden}"
    )

    key_input(VK_H)
    _pump_n(8)
    qtbot.waitUntil(lambda: eid in view.curve_keys(), timeout=2000)
    shot_shown = tmp_path / "03_h_shown.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_shown))
    assert eid in view.curve_keys(), (
        f"second real H key did not re-show the curve. screenshot: {shot_shown}"
    )
    assert view.active_curve_id() == eid, (
        "H must not deactivate the curve (spec Section 2) — active_curve_id changed"
    )


def test_real_right_click_menu_hide_removes_curve(qtbot: QtBot, tmp_path: Path) -> None:
    """曲線を実右クリック -> メニュー表示 (スクショ) -> 「非表示」を実クリック -> 曲線消滅。

    QColorDialog はネイティブモーダルのため駆動しない: color_dialog_fn を構築前に
    スタブへ差し替える (このテストは色変更を選ばないため実際には呼ばれないが、
    事故で「その他…」へ着弾してもネイティブダイアログでハングしない安全策)。
    メニューは QMenu.exec() の modal loop 内で開く — QTimer.singleShot によるcapture
    はその modal loop 内で発火する (tests/realgui/test_graph_panel_menu_realclick.py /
    test_remove_file_preserves_proportions.py と同じ確立パターン)。
    """
    skip_unless_real_display()
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    view, _signal_key = _build_panel(color_dialog_fn=lambda: None)
    _show(qtbot, view)
    eid = view.curve_keys()[0]
    px, py = _curve_point_phys(view, eid)

    captured: dict[str, object] = {}
    loop = QEventLoop()
    shot_menu = tmp_path / "04_curve_menu.png"
    shot_after = tmp_path / "05_curve_hidden_after_menu.png"

    def do_right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)
        # The context-menu QMenu.exec() opens here (real OS WM_CONTEXTMENU);
        # _capture_and_click_hide (a later singleShot) runs inside its modal loop.

    def _capture_and_click_hide() -> None:
        popup = QApplication.activePopupWidget()
        captured["type"] = type(popup).__name__ if popup is not None else None
        with contextlib.suppress(Exception):
            QApplication.primaryScreen().grabWindow(0).save(str(shot_menu))
        if isinstance(popup, QMenu):
            captured["actions"] = [a.text() for a in popup.actions()]
            hide_action = next(
                (a for a in popup.actions() if a.text() == "非表示"), None
            )
            if hide_action is not None:
                r = popup.actionGeometry(hide_action)
                dpr = view.devicePixelRatioF()
                gp = popup.mapToGlobal(r.center())
                hx, hy = round(gp.x() * dpr), round(gp.y() * dpr)
                at(hx, hy, LDOWN)
                at(hx, hy, LUP)
                captured["clicked"] = True
        loop.quit()

    QTimer.singleShot(300, do_right_click)
    QTimer.singleShot(900, _capture_and_click_hide)
    QTimer.singleShot(5000, loop.quit)  # safety net
    loop.exec()

    assert captured.get("type") == "QMenu", (
        f"real right-click did not raise the curve menu (got "
        f"{captured.get('type')!r}). screenshot: {shot_menu}"
    )
    actions = captured.get("actions") or []
    assert "非表示" in actions, f"curve menu missing '非表示': {actions!r}"
    assert captured.get("clicked"), "real click on the '非表示' action failed to fire"

    _pump_n(6)
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot_after))
    assert eid not in view.curve_keys(), (
        "curve is still drawn after a real click on the menu's '非表示' action. "
        f"screenshots: {shot_menu}, {shot_after}"
    )


def test_real_drag_past_threshold_applies_offset(qtbot: QtBot, tmp_path: Path) -> None:
    """DP16 無回帰: 閾値超えの実ドラッグ -> Δt 適用で curve_xy の x 配列がシフトする。

    grabMouse-at-press が無いと実 OS の move は子 QGraphicsView に消費され親
    GraphPanelView に届かない (memory gui_realgui_move_not_reaching_parent_qwidget)
    ため、これは構造的に Layer C でしか証明できない (Layer B の sendEvent は move を
    親へ直送するため見逃す)。実ドラッグは別 OS スレッド (mouse) + このスレッド
    (Enter で apply dialog を確定) の2スレッドで駆動する
    (tests/realgui/test_offset_drag.py と同じ確立パターン; 同ファイルは書き換えない)。
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view, _signal_key = _build_panel()
    _show(qtbot, view)
    eid = view.curve_keys()[0]
    x_before = np.asarray(view.curve_xy(eid)[0]).copy()

    vb = view._view_boxes[0]
    rect = vb.sceneBoundingRect()
    start_sx = rect.x() + rect.width() * 0.5
    start_sy = rect.y() + rect.height() * 0.5
    target_sx = rect.x() + rect.width() * 0.75
    gx, gy = to_phys(view, start_sx, start_sy)
    tx, _ty = to_phys(view, target_sx, start_sy)

    stop = threading.Event()
    dismisser = threading.Thread(target=_dialog_dismisser, args=(stop,), daemon=True)

    at(gx, gy, LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        at(gx + (tx - gx) * k // steps, gy, MOVE)  # crosses the DP16 drag threshold
        QApplication.processEvents()
        time.sleep(0.02)
    at(tx, gy, LUP)
    # The apply dialog opens via QTimer.singleShot(0, ...) after release; start the
    # dismisser only now (racing it against the drag would miss the deferred open).
    dismisser.start()
    for _ in range(40):
        QApplication.processEvents()
        time.sleep(0.05)
    stop.set()
    dismisser.join(timeout=2.0)

    shot = tmp_path / "06_offset_drag_applied.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(shot))

    x_after = np.asarray(view.curve_xy(eid)[0])
    assert float(x_after.min()) > float(x_before.min()) + 1e-3, (
        f"real drag past the DP16 threshold did not apply an offset (x array "
        f"unshifted). screenshot: {shot}"
    )
