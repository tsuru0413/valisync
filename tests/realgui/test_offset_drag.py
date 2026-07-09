# ruff: noqa: RUF002
"""Layer C: R14 時間オフセットのクロスパネル再描画を実 OS 入力で検証。--realgui で実行。

実 GraphAreaView＋同一タブ2パネル（両方が同一信号を表示）。1枚目(可視)の曲線を実 OS マウスで
掴み右へドラッグ→リリースで実 modal 適用ダイアログ→別スレッドが Enter で「この信号のみ」確定→
**両パネルの curve_xy が同一 Δt だけシフト**（②: 実 app→GraphAreaVM→panels の 'offsets' 配線が
実機経路で動く＝単一パネルのジェスチャ＋実 modal 証明を内包）。set_offsets シムは使わない。
縦 splitter なので2パネルは同幅＝同 LOD → 両カーブは同一配列で比較できる。
"""

from __future__ import annotations

import contextlib
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    MOVE,
    VK_ESCAPE,
    VK_RETURN,
    at,
    key,
    skip_unless_real_display,
    to_phys,
)

pytestmark = pytest.mark.realgui


def _dialog_dismisser(stop: threading.Event) -> None:
    """別スレッド: 実 modal を Enter で確定（既定=この信号のみ）。3s で Escape ウォッチドッグ。

    このスレッドはマウスリリース後に開始する（呼び出し側参照）。ダイアログは
    QTimer.singleShot(0,...) で遅延開口するため、ドラッグ中に開始すると
    DPR 依存のドラッグ所要時間と競合して Enter が空振りする。
    リリース後に開始すれば 0.5s のスリープで singleShot 処理が確実に完了する。
    """
    time.sleep(0.5)
    if not stop.is_set():
        key(VK_RETURN)
    deadline = time.time() + 3.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.2)
    if not stop.is_set():
        key(VK_ESCAPE)


def _two_panel_area(qtbot: QtBot):
    """実 app→GraphAreaVM→GraphAreaView を構築し、同一タブに同一信号を表示する2パネルを返す。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
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
    area_vm.add_panel(0)  # tab 0 now holds two panels (both visible in the splitter)
    for p in area_vm.panels(0):
        p.add_signal_to_axis(signal_key, 0)

    # Default factory builds real GraphPanelViews (real modal apply dialog) and
    # GraphAreaView._wire_panel connects offset_apply_requested → vm.apply_offset.
    view = GraphAreaView(area_vm)
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(200, 100, 900, 800)
    view.show()
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
    return view, panels, signal_key


def test_real_offset_drag_shifts_both_panels(qtbot: QtBot, tmp_path) -> None:
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    _view, panels, signal_key = _two_panel_area(qtbot)
    p0, p1 = panels[0], panels[1]
    eid0 = p0.entry_id_for(signal_key)
    eid1 = p1.entry_id_for(signal_key)
    x0_before = np.asarray(p0.curve_xy(eid0)[0]).copy()
    x1_before = np.asarray(p1.curve_xy(eid1)[0]).copy()

    # Grab p0's curve at the plot centre (linear v=t passes through it) and drag right.
    vb = p0._view_boxes[0]
    rect = vb.sceneBoundingRect()
    start_sx = rect.x() + rect.width() * 0.5
    start_sy = rect.y() + rect.height() * 0.5
    target_sx = rect.x() + rect.width() * 0.75
    gx, gy = to_phys(p0, start_sx, start_sy)
    tx, _ = to_phys(p0, target_sx, start_sy)

    stop = threading.Event()
    dismisser = threading.Thread(target=_dialog_dismisser, args=(stop,), daemon=True)

    at(gx, gy, LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        at(gx + (tx - gx) * k // steps, gy, MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    at(tx, gy, LUP)
    # ダイアログは QTimer.singleShot(0,...) でリリース後に開口するため、
    # dismisser はリリース後に開始する (HiDPI でドラッグ所要時間が伸びても競合しない)。
    dismisser.start()
    # Pump the event loop so the deferred dialog opens and the thread confirms it.
    for _ in range(40):
        QApplication.processEvents()
        time.sleep(0.05)
    stop.set()
    dismisser.join(timeout=2.0)

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "offset_cross.png")
        )

    x0_after = np.asarray(p0.curve_xy(eid0)[0])
    x1_after = np.asarray(p1.curve_xy(eid1)[0])
    # p0 (dragged) re-rendered with the committed offset → leftmost x moved right.
    assert float(x0_after.min()) > float(x0_before.min()) + 1e-3
    # p1 (the OTHER panel) re-rendered identically via the real 'offsets' broadcast
    # (same width → same LOD → identical arrays). This is the cross-panel evidence.
    np.testing.assert_allclose(x1_after, x0_after, atol=1e-6)
    assert float(x1_after.min()) > float(x1_before.min()) + 1e-3


def test_real_escape_cancels_offset_drag(qtbot: QtBot, tmp_path: Path) -> None:
    """M1: Escape mid-drag cancels the offset gesture without opening the apply dialog.

    Flow: LDOWN on curve (candidate) → MOVEs past the DP16 threshold (promotes to
    the offset drag) → more MOVEs to set a non-zero delta → VK_ESCAPE → LUP.
    After Escape the drag state must be fully cleared and _finish_offset / the apply
    dialog must never have been called.

    honest RED gate: remove the ``self._offset_drag_key is not None:
    self._cancel_offset_drag()`` branch from graph_panel_view.py's keyPressEvent
    Escape handler (currently around line 1861) → Escape is
    ignored → drag stays active (_offset_drag_key is not None immediately after the
    key) OR the LUP triggers _end_offset_drag → the patched _apply_dialog_fn is
    called → dialog_called=True → the ``assert not dialog_called`` assertion below
    flips RED.
    """
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    _view, panels, _signal_key = _two_panel_area(qtbot)
    p0 = panels[0]

    # Patch the apply-dialog function so that if it IS called (honest-RED path),
    # we detect it without blocking on a modal dialog.
    dialog_called = False

    def _fake_dialog(sk: str, dt: float) -> str | None:
        nonlocal dialog_called
        dialog_called = True
        return None  # return None = "cancel from dialog" (does not commit the offset)

    p0._apply_dialog_fn = _fake_dialog

    # Build drag coordinates (same centre-of-plot pattern as the main test).
    vb = p0._view_boxes[0]
    rect = vb.sceneBoundingRect()
    start_sx = rect.x() + rect.width() * 0.5
    start_sy = rect.y() + rect.height() * 0.5
    target_sx = rect.x() + rect.width() * 0.75
    gx, gy = to_phys(p0, start_sx, start_sy)
    tx, _ = to_phys(p0, target_sx, start_sy)

    # ── Press, then move past the drag threshold ───────────────────────────────
    # DP16: a press alone only holds a candidate (graph_panel_view.py
    # mousePressEvent) — the offset drag itself begins in mouseMoveEvent once the
    # move exceeds QApplication.startDragDistance(). Real win32 press/move
    # delivery can take several event-loop turns, so pump until the candidate is
    # observed, then move (in small steps, matching the main test) until the
    # drag actually engages, rather than asserting after a single processEvents.
    at(gx, gy, LDOWN)
    time.sleep(0.05)
    for _ in range(25):
        QApplication.processEvents()
        if p0._curve_press_candidate is not None:
            break
        time.sleep(0.02)
    assert p0._curve_press_candidate is not None, (
        "curve press candidate did not appear — curve may not be in the "
        "ZONE_PLOT hit area"
    )

    steps = 4
    for k in range(1, steps + 1):
        at(gx + (tx - gx) * k // steps, gy, MOVE)
        QApplication.processEvents()
        if p0._offset_drag_key is not None:
            break
        time.sleep(0.02)

    # Confirm the drag engaged (candidate promoted) before testing the cancel path.
    assert p0._offset_drag_key is not None, (
        "offset drag did not start after crossing the drag threshold"
    )

    # ── Press Escape while grabMouse is held → _cancel_offset_drag ────────────
    key(VK_ESCAPE)
    time.sleep(0.05)
    QApplication.processEvents()

    # ── Release the mouse (grab already released by _reset_offset_state) ──────
    at(tx, gy, LUP)
    # Pump the event loop so any deferred QTimer.singleShot callbacks can fire.
    for _ in range(10):
        QApplication.processEvents()
        time.sleep(0.02)

    # ── Assertions ────────────────────────────────────────────────────────────
    assert p0._offset_drag_key is None, (
        "Escape did not cancel the offset drag — _offset_drag_key still set"
    )
    assert p0._offset_orig_pen is None, (
        "_offset_orig_pen not cleared — _reset_offset_state was not reached"
    )
    assert not dialog_called, (
        "apply dialog was invoked despite Escape cancellation — "
        "_end_offset_drag must not have been called"
    )

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "escape_cancel.png")
        )


def test_real_cursor_line_wins_overlap_press(qtbot: QtBot, tmp_path: Path) -> None:
    """M2: Pressing at cursor-line × curve overlap routes to the line, not the curve.

    _curve_at returns None when the press is within CURSOR_LINE_HIT_PX (10 scene px)
    of a visible cursor line, so no drag candidate is captured even though a curve is
    also nearby (within CURVE_HIT_TOL_PX=8 scene px).

    Press geometry: 5 scene pixels to the right of the cursor line —
      • Inside CURSOR_LINE_HIT_PX=10  → guard fires → _curve_at returns None
      • Outside InfiniteLine bounding rect (~2 scene px) → p0.mousePressEvent IS
        reached (event is not captured by the scene item) → the guard is genuinely
        exercised, not bypassed by Qt's event routing
      • Distance to nearest curve point ≈ 5 scene px < CURVE_HIT_TOL_PX=8 → without
        the guard, _curve_at WOULD return the curve key

    DP16 note: a curve press no longer begins the offset drag directly — it is
    held as ``_curve_press_candidate`` in mousePressEvent (only promoted to
    ``_offset_drag_key`` by a later move past the drag threshold). The guard's
    effect is therefore observed on the candidate right after the press, not on
    ``_offset_drag_key`` — checking the latter after a plain press+release would
    be true whether or not the guard fired (a within-threshold click never begins
    an offset drag, it activates the curve instead), so it would no longer be
    load-bearing for this guard.

    honest RED gate: remove or neuter the ``CURSOR_LINE_HIT_PX`` early-return
    guard inside ``_curve_at`` (``if abs(scene_pos.x() - line_scene_x) <=
    CURSOR_LINE_HIT_PX: return None``) → _curve_at finds the curve at ~5 scene px
    (< CURVE_HIT_TOL_PX) → mousePressEvent sets ``_curve_press_candidate`` to
    that curve → the primary assertion below (checked right after the press)
    flips RED, proving the test is not vacuously green.

    NOTE: the ``if not line.isVisible(): continue`` skip a few lines above the
    guard is NOT the load-bearing target — removing the visibility skip does not
    disable the guard because the visible cursor-A line still reaches the
    ``return None``.

    Positive line-engagement signal: no cursor-line movement is observable here
    because the press lands outside the InfiniteLine's bounding rect (the line item
    does not grab the drag at +5 px). Non-vacuity is therefore established by the
    honest-RED gate above, not by observing the line move.
    """
    skip_unless_real_display()
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    _view, panels, _signal_key = _two_panel_area(qtbot)
    p0 = panels[0]

    # ── Place cursor A at a known data position ────────────────────────────────
    # The CSV data is lin.csv: t[i] = i/50, lin[i] = i/50 (i=0..49).
    # At t=0.5 the curve passes through (0.5, 0.5) in data space.
    t_line = 0.5
    p0.vm.set_cursor(t_line)  # synchronous: _notify("cursor") → _sync_cursor_from_vm
    QApplication.processEvents()

    assert p0.cursor_line_visible(), "cursor A line not visible after set_cursor"
    assert abs(p0.cursor_line_value() - t_line) < 1e-9, (
        "cursor line value mismatch after set_cursor"
    )

    # ── Compute the press point in scene coordinates ───────────────────────────
    vb = p0._view_boxes[0]
    # Scene x of the cursor line (vertical line at data_x = t_line).
    cursor_scene_x = vb.mapViewToScene(QPointF(t_line, 0.0)).x()
    # Scene y of the curve at that same data_x (lin = t, so data_y = t_line).
    curve_scene_y = vb.mapViewToScene(QPointF(t_line, t_line)).y()

    # 5 scene pixels to the right: inside CURSOR_LINE_HIT_PX(10) but outside the
    # InfiniteLine's bounding rect (~2 scene px half-width based on pen width=2).
    # At this offset the nearest curve point is ~5 scene px away, which is less
    # than CURVE_HIT_TOL_PX=8 — so without the guard the curve would be returned.
    press_sx = cursor_scene_x + 5.0
    press_sy = curve_scene_y
    px, py = to_phys(p0, press_sx, press_sy)

    # ── Press at the overlap point ──────────────────────────────────────────────
    at(px, py, LDOWN)
    time.sleep(0.05)
    QApplication.processEvents()

    # ── Primary assertion: cursor-line guard prevented the curve hit-test ──────
    # (checked right after the press, before release — see the DP16 note above)
    assert p0._curve_press_candidate is None, (
        "curve press candidate captured at cursor-line overlap — "
        "_curve_at's cursor-line guard did not fire"
    )

    at(px, py, LUP)
    QApplication.processEvents()

    assert p0._offset_drag_key is None, (
        "offset drag started at cursor-line overlap — _curve_at guard did not fire"
    )
    assert p0._offset_orig_pen is None, (
        "curve pen was highlighted — _begin_offset_drag must have been called"
    )

    # Cursor line still at its original position (no drag redirected it).
    assert p0.cursor_line_visible(), "cursor line disappeared after overlap press"
    assert abs(p0.cursor_line_value() - t_line) < 1e-6, (
        "cursor line moved unexpectedly — routing may have engaged the InfiniteLine"
    )

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "cursor_overlap.png")
        )
