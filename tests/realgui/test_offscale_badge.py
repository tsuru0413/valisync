# ruff: noqa: RUF002
"""Layer C (realgui) — オフスケール通知バッジの実 OS クリック＋非干渉検証 (Stage A Task 9)。

手動レンジ時、可視カーブが完全にレンジ外へ出ると ▲/▼ の amber バッジが
プロット左端に出る (spec §3.6・UX-03)。バッジをクリックするとその軸を
オートフィット (``reset_axis_y``) へ戻す。ここはその実 OS 入力ゲート:

* **出現/消滅はピクセル走査で確認** — ``isVisible()`` は z 沈没を見逃す嘘プロキシ
  (memory ``gui_overlay_sibling_zorder_sinks_behind_later_children`` /
  offscale_badge.py の設計コメント)。真の観測はスクリーンの amber ピクセル。
* **手動化は実メニュー経路** — 軸スパインを実右クリック → 「ズームイン」を実クリック
  (``zoom_axis`` → ``set_axis_range`` → ``y_is_auto=False``)。低帯/高帯の 2 信号を
  1 軸に載せ、中心ズームで両カーブを帯外へ追い出す (単一カーブは中心が常に帯内で
  追い出せない)。
* **非干渉**: バッジは ``mousePressEvent`` を accept してプロット内クリック処理へ
  流さない。プロット左押下は ``activate_requested`` を必ず emit する
  (graph_panel_view.py: どのゾーンでも押下=活性化) ので、これを観測に使う ——
  バッジ命中時は emit されず、同座標の素のプロットクリックでは emit される。
  ※ブリーフ原文は「R15 カーソル設置」を観測に挙げるが、空クリックによるカーソル
  設置は現行仕様で撤去済み (test_global_cursor.py L192 / CLAUDE.md)。よって
  ``cursor_t`` は常に None のまま (副次 assert) とし、素のプロットクリックが起きた
  ことの主観測は ``activate_requested`` に置き換える (実挙動に忠実な等価物)。

座標変換は widget 空間規約 (memory ``gui_realgui_zone_widgetspace_and_offscreen_clamp``):
scene → viewport → global → ×DPR。メニュー nested-exec ハングは
``_menu_hang_watchdog`` (Escape) で clean-fail に倒す (test_axis_menu_offset.py と同型)。
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
from valisync.gui.views.offscale_badge import BADGE_PX

pytestmark = pytest.mark.realgui


# ─── shared harness (mirrors tests/realgui/test_axis_menu_offset.py) ────────────


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
    Qt event loop. If the real click on a menu row misses its target, nothing
    closes the popup and the nested ``menu.exec()`` blocks forever; the caller's
    outer ``QTimer.singleShot(5000, loop.quit)`` safety net only reaches the OUTER
    loop and cannot unwind the nested exec(). QMenu treats Escape as "close", so
    this daemon thread sends ``VK_ESCAPE`` after a deadline and the test then fails
    on a clean assertion instead of hanging. (module-local copy of the helper
    established in test_axis_menu_offset.py — kept per-file to avoid cross-test
    imports.)
    """
    deadline = time.time() + 4.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.1)
    if not stop.is_set():
        key_input(VK_ESCAPE)


def _show(qtbot: QtBot, view, w: int = 820, h: int = 640) -> None:  # type: ignore[no-untyped-def]
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

    The spine is a scene item in the fixed-width gutter LEFT of the plot, so its
    scene centre maps (via the same plot_widget.mapFromScene transform) to a
    widget point with ``x < plot_rect.left()`` -> ZONE_Y_INNER/OUTER, which
    contextMenuEvent routes to build_axis_menu (same recipe as
    test_axis_menu_offset._spine_center_phys).
    """
    spine = panel._y_axes[axis_index].sceneBoundingRect()
    return to_phys(panel, spine.center().x(), spine.center().y())


def _open_menu_click_item(dpr_widget, phys, item_text: str, shot_menu: Path):  # type: ignore[no-untyped-def]
    """Real right-click at *phys*, screenshot the popup, then real-click its row
    labelled *item_text*. Returns the captured dict {type, actions, clicked}.

    Verbatim copy of the modal-menu pattern in test_axis_menu_offset.py: the QMenu
    opens inside contextMenuEvent's synchronous exec(), and the capture singleShot
    fires *inside* that nested modal loop. The clicked-row rect is mapped to
    physical pixels via popup.mapToGlobal x DPR (widget-space convention). A
    menu-hang watchdog guards against the click missing its target.
    """
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


# ─── panel builder: two well-separated bands on ONE axis ───────────────────────


def _offscale_panel():  # type: ignore[no-untyped-def]
    """Standalone GraphPanelView with TWO non-overlapping bands on ONE axis.

    ``a`` ramps 0->1 (low band), ``b`` ramps 1000->1001 (high band). The auto-fit
    union is [0, 1001] centred at ~500. A single centre-based zoom-in (factor 0.9)
    shrinks the range to ~[50, 951], which lies ENTIRELY between the two bands: a's
    max (1) is far below the new lo and b's min (1000) is far above the new hi
    (margin ~50 each). So both curves go fully off-scale -> a ▼ badge (a below) and
    a ▲ badge (b above). Two well-separated bands are required because a single
    curve straddles the zoom centre and can never be pushed fully outside by a
    centre-preserving zoom. Returns (view, key_low, key_high).
    """
    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import GraphPanelView

    d = Path(tempfile.mkdtemp())
    csv = d / "bands.csv"
    rows = ["t,a,b"] + [
        f"{i / 50.0:.4f},{i / 49.0:.4f},{1000.0 + i / 49.0:.4f}" for i in range(50)
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
    keys = sorted(s.name for s in session.signals())  # ['a', 'b']
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(keys[0], 0)  # a -> low band
    vm.add_signal_to_axis(keys[1], 0)  # b -> high band; both on axis 0
    return GraphPanelView(vm), keys[0], keys[1]


# ─── badge geometry (mirrors _position_offscale_badges exactly) ─────────────────


def _badge_scene_pos(view, axis_index: int, direction: str) -> tuple[float, float]:  # type: ignore[no-untyped-def]
    """Top-left scene pos of the badge for (axis_index, direction), computed the
    same way _position_offscale_badges does (plot-rect left edge; region top for
    ▲, region bottom - BADGE_PX for ▼)."""
    r = view._view_boxes[0].sceneBoundingRect()
    ax = view.vm.axes[axis_index]
    region_top = r.y() + ax.top_ratio * r.height()
    region_h = ax.height_ratio * r.height()
    x = r.left()
    y = region_top if direction == "up" else region_top + region_h - BADGE_PX
    return x, y


def _badge_center_phys(view, axis_index: int, direction: str) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    x, y = _badge_scene_pos(view, axis_index, direction)
    return to_phys(view, x + BADGE_PX / 2.0, y + BADGE_PX / 2.0)


def _badge_rect_phys(view, axis_index: int, direction: str):  # type: ignore[no-untyped-def]
    """Physical (col_lo, col_hi, row_lo, row_hi) of the badge's 18x18 scene box."""
    x, y = _badge_scene_pos(view, axis_index, direction)
    ax_col, ay_row = to_phys(view, x, y)
    bx_col, by_row = to_phys(view, x + BADGE_PX, y + BADGE_PX)
    col_lo, col_hi = sorted((ax_col, bx_col))
    row_lo, row_hi = sorted((ay_row, by_row))
    return col_lo, col_hi, row_lo, row_hi


def _count_amber(image, rect) -> int:  # type: ignore[no-untyped-def]
    """Count accent-amber (#f59e0b) pixels inside *rect* on the grabbed screen.

    Per-channel tolerance is asymmetric on purpose: the second curve's colour is
    signal_palette[1] = #ff7f0e (255,127,14) — an ORANGE that shares amber's red
    and blue but differs in green (127 vs 158). A GREEN tolerance of +/-20 keeps
    the amber triangle interior while excluding the orange curve (delta 31), which
    matters for the ABSENCE scan when the fitted curve is drawn back into the
    top region. Blue (a) is excluded on every channel.
    """
    from valisync.gui.theme import tokens

    acc = tokens.active().colors.accent_active
    col_lo, col_hi, row_lo, row_hi = rect
    w, h = image.width(), image.height()
    n = 0
    for row in range(max(0, row_lo), min(h - 1, row_hi) + 1):
        for col in range(max(0, col_lo), min(w - 1, col_hi) + 1):
            c = image.pixelColor(col, row)
            if (
                abs(c.red() - acc.r) <= 25
                and abs(c.green() - acc.g) <= 20
                and abs(c.blue() - acc.b) <= 25
            ):
                n += 1
    return n


def _grab_image():  # type: ignore[no-untyped-def]
    """DWM-flushed full-screen grab -> QImage (FU-12 pattern: processEvents alone
    does not guarantee the OS flushed the repaint to the buffer grabWindow reads)."""
    from PySide6.QtWidgets import QApplication

    time.sleep(0.15)
    QApplication.processEvents()
    return QApplication.primaryScreen().grabWindow(0).toImage()


def _manualize_offscale(qtbot: QtBot, view, tmp_path: Path, tag: str) -> None:  # type: ignore[no-untyped-def]
    """Real menu 'ズームイン' on axis 0's spine -> one centre-zoom that pushes both
    bands off-scale. Asserts the manual flag + off-scale state before returning."""
    from PySide6.QtWidgets import QApplication

    spine = _spine_center_phys(view, 0)
    shot_menu = tmp_path / f"{tag}_00_zoom_menu.png"
    captured = _open_menu_click_item(view, spine, "ズームイン", shot_menu)
    _pump_n(8)
    QApplication.processEvents()

    assert captured.get("type") == "QMenu", (
        "real right-click on axis 0's gutter did not raise the axis menu (got "
        f"{captured.get('type')!r}). screenshot: {shot_menu}"
    )
    assert "ズームイン" in (captured.get("actions") or []), (
        f"axis menu missing 'ズームイン': {captured.get('actions')!r}"
    )
    assert captured.get("clicked"), "real click on 'ズームイン' failed to fire"

    ax = view.vm.axes[0]
    assert ax.y_is_auto is False, (
        "ズームイン must mark the axis manual (y_is_auto=False)"
    )
    up, down = view._axis_offscale.get(0, (False, False))
    assert up and down, (
        "one zoom-in should push BOTH bands off-scale (a below, b above); "
        f"got off-scale state up={up} down={down}, y_range={ax.y_range!r}. "
        f"screenshot: {shot_menu}"
    )


# ─── Steps 1-4: real badge click -> reset axis -> badge disappears ─────────────


def test_real_click_offscale_badge_resets_axis(qtbot: QtBot, tmp_path: Path) -> None:
    """手動化で ▲/▼ バッジ出現をピクセルで確認 → ▲ バッジを実クリック →
    軸が可視和集合へオートフィット復帰 (y_is_auto=True) → バッジ消滅をピクセルで確認。

    honest-RED: offscale_badge.OffscaleBadge.mouseReleaseEvent の
    ``self.clicked.emit()`` を外すと、クリックが reset を起こさず after の
    y_is_auto が False のまま / バッジが残って absence 走査が amber を検出し続けて
    RED になる。
    """
    skip_unless_real_display()

    view, _key_a, _key_b = _offscale_panel()
    _show(qtbot, view)
    _wait_panel_laid_out(qtbot, view)
    assert len(view.vm.axes) == 1

    _manualize_offscale(qtbot, view, tmp_path, "reset")

    # (2) PRESENCE — amber pixels in BOTH badge rects on the real screen.
    up_rect = _badge_rect_phys(view, 0, "up")
    down_rect = _badge_rect_phys(view, 0, "down")
    img_before = _grab_image()
    img_before.save(str(tmp_path / "reset_01_badges_present.png"))
    up_amber = _count_amber(img_before, up_rect)
    down_amber = _count_amber(img_before, down_rect)
    assert up_amber >= 5 and down_amber >= 5, (
        "off-scale badges not found by pixel scan (▲ amber="
        f"{up_amber}, ▼ amber={down_amber}). isVisible would lie here — pixels "
        f"are the honest observable. rects up={up_rect} down={down_rect}. "
        f"screenshot: {tmp_path / 'reset_01_badges_present.png'}"
    )

    before_range = view.vm.axes[0].y_range
    assert before_range is not None
    assert before_range[0] > 5.0 and before_range[1] < 995.0, (
        f"manual (zoomed) range should be narrow, got {before_range!r}"
    )

    # (3) real-click the ▲ badge centre -> reset_axis_y(0)
    px, py = _badge_center_phys(view, 0, "up")
    at(px, py, LDOWN)
    _pump()
    at(px, py, LUP)
    _pump_n(8)

    # axes[0].y_range restored to the visible union (a:0..1, b:1000..1001) and auto.
    after = view.vm.axes[0]
    assert after.y_is_auto is True, (
        "clicking the badge must restore the axis to auto-fit (y_is_auto=True); "
        f"got False, y_range={after.y_range!r}"
    )
    assert after.y_range is not None
    assert after.y_range[0] <= 0.5 and after.y_range[1] >= 1000.5, (
        "reset did not fit the axis to the full visible union [0, 1001]; got "
        f"{after.y_range!r} (still the zoomed range means the click did nothing)."
    )

    # (4) ABSENCE — no amber left in either badge rect (badges removed on refresh).
    img_after = _grab_image()
    img_after.save(str(tmp_path / "reset_02_badges_gone.png"))
    up_after = _count_amber(img_after, up_rect)
    down_after = _count_amber(img_after, down_rect)
    assert up_after == 0 and down_after == 0, (
        "badge amber still on screen after reset (▲ amber="
        f"{up_after}, ▼ amber={down_after}) — badge should be removed once the "
        "axis is auto-fit. screenshot: "
        f"{tmp_path / 'reset_02_badges_gone.png'}"
    )


# ─── Step 5: non-interference (badge accepts the press) ────────────────────────


def test_offscale_badge_click_is_non_interfering(qtbot: QtBot, tmp_path: Path) -> None:
    """バッジ命中はプロット内クリック処理へ流れない (``event.accept()``)。

    観測 = ``activate_requested`` (どのゾーンでも左押下=活性化で必ず emit)。
    - バッジを実クリック → reset は起きるが activate_requested は emit されず・
      ``cursor_t`` は None のまま (バッジが press を accept して親 mousePressEvent
      に届かせない)。
    - 同座標を素のプロット (バッジ消滅後) で実クリック → activate_requested が
      emit される (その座標が生きたプロットクリック標的である証拠) ・cursor_t は
      引き続き None (空クリックカーソル設置は撤去済み)。

    honest-RED: OffscaleBadge.mousePressEvent の ``event.accept()`` を外すと press
    が親へバブルして activate_requested が emit され、最初の assert が RED になる。
    """
    skip_unless_real_display()

    view, _key_a, _key_b = _offscale_panel()
    _show(qtbot, view)
    _wait_panel_laid_out(qtbot, view)
    _manualize_offscale(qtbot, view, tmp_path, "noninterf")

    activations: list[int] = []
    view.activate_requested.connect(lambda: activations.append(1))

    assert view.vm.cursor_t is None, "precondition: no global cursor set"
    px, py = _badge_center_phys(view, 0, "up")

    # (a) click the badge — resets, but must NOT reach GraphPanelView.mousePressEvent
    at(px, py, LDOWN)
    _pump()
    at(px, py, LUP)
    _pump_n(8)
    _grab_image().save(str(tmp_path / "noninterf_01_after_badge_click.png"))

    assert view.vm.axes[0].y_is_auto is True, (
        "badge click should have reset the axis (sanity: the click landed on the "
        "badge). If this fails the coordinate mapping missed the badge."
    )
    assert activations == [], (
        "clicking the badge leaked into the plot's click handling: "
        f"activate_requested fired {len(activations)} time(s). The badge's "
        "mousePressEvent must accept() the press so it never bubbles to "
        "GraphPanelView.mousePressEvent."
    )
    assert view.vm.cursor_t is None, (
        "badge click must not place any cursor (cursor_t stayed None)"
    )

    # (b) same physical coords, now a plain plot point (badge gone) — the plot
    # DOES handle the click (activate_requested fires). Proves the coords are a
    # live plot target that the badge was genuinely intercepting in (a).
    activations.clear()
    at(px, py, LDOWN)
    _pump()
    at(px, py, LUP)
    _pump_n(6)

    assert activations, (
        "a plain plot click at the same coords did NOT emit activate_requested — "
        "the coordinates must be a live plot-click target for the non-interference "
        "comparison to be meaningful (mousePressEvent not reached)."
    )
    # empty-click cursor placement was removed (test_global_cursor.py L192); the
    # honest 'cursor NOT placed' invariant holds for the plain click too.
    assert view.vm.cursor_t is None, (
        "plain plot click unexpectedly placed a cursor (empty-click placement is "
        "removed in the current spec)"
    )
