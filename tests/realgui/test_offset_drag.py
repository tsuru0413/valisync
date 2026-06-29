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
import ctypes
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

pytestmark = pytest.mark.realgui
_MOVE, _LDOWN, _LUP = 0x0001, 0x0002, 0x0004
_KEYDOWN, _KEYUP = 0x0000, 0x0002
_VK_RETURN, _VK_ESCAPE = 0x0D, 0x1B


def _skip_unless_real_display() -> None:
    if sys.platform != "win32":
        pytest.skip("real OS input is Windows-only")
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() == "offscreen":
        pytest.skip(
            "requires a real display — run: uv run pytest --realgui tests/realgui/"
        )


def _to_phys(view, sx: float, sy: float) -> tuple[int, int]:
    from PySide6.QtCore import QPoint

    vp = view.plot_widget.mapFromScene(QPoint(int(sx), int(sy)))
    g = view.plot_widget.viewport().mapToGlobal(vp)
    dpr = view.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _at(x: float, y: float, flag: int) -> None:
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(flag, 0, 0, 0, 0)


def _key(vk: int) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, _KEYDOWN, 0)
    user32.keybd_event(vk, 0, _KEYUP, 0)


def _dialog_dismisser(stop: threading.Event) -> None:
    """別スレッド: 実 modal を Enter で確定（既定=この信号のみ）。3s で Escape ウォッチドッグ。

    このスレッドはマウスリリース後に開始する（呼び出し側参照）。ダイアログは
    QTimer.singleShot(0,...) で遅延開口するため、ドラッグ中に開始すると
    DPR 依存のドラッグ所要時間と競合して Enter が空振りする。
    リリース後に開始すれば 0.5s のスリープで singleShot 処理が確実に完了する。
    """
    time.sleep(0.5)
    if not stop.is_set():
        _key(_VK_RETURN)
    deadline = time.time() + 3.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.2)
    if not stop.is_set():
        _key(_VK_ESCAPE)


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
    _skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    _view, panels, key = _two_panel_area(qtbot)
    p0, p1 = panels[0], panels[1]
    x0_before = np.asarray(p0.curve_xy(key)[0]).copy()
    x1_before = np.asarray(p1.curve_xy(key)[0]).copy()

    # Grab p0's curve at the plot centre (linear v=t passes through it) and drag right.
    vb = p0._view_boxes[0]
    rect = vb.sceneBoundingRect()
    start_sx = rect.x() + rect.width() * 0.5
    start_sy = rect.y() + rect.height() * 0.5
    target_sx = rect.x() + rect.width() * 0.75
    gx, gy = _to_phys(p0, start_sx, start_sy)
    tx, _ = _to_phys(p0, target_sx, start_sy)

    stop = threading.Event()
    dismisser = threading.Thread(target=_dialog_dismisser, args=(stop,), daemon=True)

    _at(gx, gy, _LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        _at(gx + (tx - gx) * k // steps, gy, _MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    _at(tx, gy, _LUP)
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

    x0_after = np.asarray(p0.curve_xy(key)[0])
    x1_after = np.asarray(p1.curve_xy(key)[0])
    # p0 (dragged) re-rendered with the committed offset → leftmost x moved right.
    assert float(x0_after.min()) > float(x0_before.min()) + 1e-3
    # p1 (the OTHER panel) re-rendered identically via the real 'offsets' broadcast
    # (same width → same LOD → identical arrays). This is the cross-panel evidence.
    np.testing.assert_allclose(x1_after, x0_after, atol=1e-6)
    assert float(x1_after.min()) > float(x1_before.min()) + 1e-3
