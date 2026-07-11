"""Layer C: FU-02 — 表示中の BusyOverlay が実 WM リサイズに追従し、
リサイズ後のキャンセルボタンへ実クリックが届く (到達性の直接反証)。

`--realgui` opt-in・実ディスプレイ+Windows 必須。リサイズは Win32
`SetWindowPos` (repo 初のプリミティブ・Qt 外部からの実 OS ウィンドウ操作 =
WM_SIZE -> QResizeEvent の実変換経路) で駆動する — `widget.resize()` は
アプリ発で headless でも同様に動き OS/ユーザー発のリサイズを証明しない
のに対し、外部 `SetWindowPos` は OS 発 = ユーザーのフレームドラッグと
同方向の実経路を証明する。クリックは実マウス (`at()`)。
オーバーレイの表示は先行例
tests/realgui/test_busy_cancel_realclick.py と同じ LoadController +
blocking callable パターン (MainWindow と同一配線)。

honest-RED: `busy_overlay.py` の `parent.installEventFilter(self)` を一時的に
外す sabotage で、リサイズ後の geometry 一致 assert が実際に FAIL することを
実証済み (Task 2 Step 4)。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    at,
    set_window_pos,
    skip_unless_real_display,
    window_rect,
)

pytestmark = pytest.mark.realgui


def test_overlay_tracks_real_wm_resize_and_cancel_click_lands(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """FU-02 受け入れ: 実 WM 縮小リサイズ後も overlay が親全域を覆い、
    キャンセル実クリックが cancel_requested を発火して overlay が隠れる。"""
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget

    from valisync.gui.views.busy_overlay import BusyOverlay
    from valisync.gui.workers.load_worker import LoadController

    release = threading.Event()
    cancel_event = threading.Event()
    discards: list[object] = []

    def slow_load() -> str:
        release.wait(timeout=10.0)  # クリックまでロードを「実行中」に保つ
        return "late_result"

    parent = QWidget()
    qtbot.addWidget(parent)
    overlay = BusyOverlay(parent)
    controller = LoadController()
    overlay.cancel_requested.connect(controller.cancel_active)  # main_window と同配線

    parent.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    parent.setGeometry(screen.x() + 60, screen.y() + 60, 900, 600)
    parent.show()
    qtbot.waitExposed(parent)
    for _ in range(3):
        QApplication.processEvents()

    controller.submit(
        slow_load,
        busy=overlay,
        cancel_event=cancel_event,
        label="a.mf4",
        on_discard=discards.append,
    )
    qtbot.waitUntil(lambda: not overlay.isHidden(), timeout=3000)
    assert overlay.geometry() == parent.rect()  # 表示直後は一致 (既存 cover)

    # 実 WM 経由で縮小 (実機で観測された方向)。座標は物理・外枠基準なので
    # 現在の実枠から差分で縮める (DPR 換算不要)。
    hwnd = int(parent.winId())
    left, top, w, h = window_rect(hwnd)
    old_client_w = parent.width()
    set_window_pos(hwnd, left, top, w - 300, h - 200)
    qtbot.waitUntil(lambda: parent.width() < old_client_w, timeout=3000)  # WM_SIZE 到達
    for _ in range(4):
        QApplication.processEvents()
        time.sleep(0.02)

    shot_resized = tmp_path / "fu02_after_wm_resize.png"
    QApplication.primaryScreen().grabWindow(0).save(str(shot_resized))
    # 修正の核: リサイズ後も overlay が親全域と一致 (sabotage 時ここで FAIL)。
    assert overlay.geometry() == parent.rect(), (
        f"FU-02 再発: WM リサイズ後 overlay={overlay.geometry()} が "
        f"parent={parent.rect()} に追従していない。screenshot: {shot_resized}"
    )

    # リサイズ後のキャンセルボタン実座標を実クリック -> 発火 + overlay 非表示。
    qtbot.waitUntil(lambda: overlay.cancel_button.rect().height() > 0, timeout=3000)
    center = overlay.cancel_button.rect().center()
    gp = overlay.cancel_button.mapToGlobal(center)
    dpr = overlay.devicePixelRatioF()
    phys_x, phys_y = round(gp.x() * dpr), round(gp.y() * dpr)
    with qtbot.waitSignal(overlay.cancel_requested, timeout=3000):
        at(phys_x, phys_y, LDOWN)
        QApplication.processEvents()
        time.sleep(0.05)
        at(phys_x, phys_y, LUP)
        for _ in range(4):
            QApplication.processEvents()
            time.sleep(0.02)

    print(f"[FU-02] overlay tracked resize; cancel click landed. shot: {shot_resized}")
    assert overlay.isHidden(), (
        f"cancel_requested は発火したが overlay が隠れない。screenshot: {shot_resized}"
    )
    assert cancel_event.is_set(), "実クリックで hard-cancel が立っていない"

    release.set()  # キャンセル済みワーカーを排水しスレッドを残さない
    qtbot.waitUntil(lambda: discards == ["late_result"], timeout=3000)
