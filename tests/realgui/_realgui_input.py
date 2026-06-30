# ruff: noqa: RUF002
"""Layer C 共有: 実 OS 入力プリミティブ＋背景スレッド QDrag ドライバ。

QDrag.exec は Windows の OLE DoDragDrop モーダルループに入り Qt タイマを汲まない
ため、QTimer 駆動の move/release は無限ハングする（memory: gui_realgui_drag_qtimer_hang）。
本ドライバは別 OS スレッドが実マウス入力を wall-clock で発行してモーダルループを
駆動し、watchdog が停滞時に ESC+LEFTUP でキャンセルする。
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

# Win32 mouse_event / keybd_event フラグ
MOVE, LDOWN, LUP = 0x0001, 0x0002, 0x0004
KEYDOWN, KEYUP = 0x0000, 0x0002
VK_RETURN, VK_ESCAPE, VK_CONTROL, VK_SHIFT = 0x0D, 0x1B, 0x11, 0x10

_user32 = ctypes.windll.user32 if sys.platform == "win32" else None


def real_display_skip_reason() -> str | None:
    """実ディスプレイが無ければ skip 理由文字列、あれば None（テスト可能なロジック）。"""
    if sys.platform != "win32":
        return "real OS input is Windows-only"
    from PySide6.QtGui import QGuiApplication

    # QGuiApplication.platformName() returns the default "windows" before any
    # QApplication is created (even with QT_QPA_PLATFORM=offscreen set). When
    # no instance exists yet, fall back to the env var that conftest sets before
    # Qt initialises so this function works correctly in test collection order.
    if QGuiApplication.instance() is not None:
        platform = QGuiApplication.platformName()
    else:
        platform = os.environ.get("QT_QPA_PLATFORM", "")
    if platform == "offscreen":
        return "requires a real display — run: uv run pytest --realgui tests/realgui/"
    return None


def skip_unless_real_display() -> None:
    import pytest

    reason = real_display_skip_reason()
    if reason:
        pytest.skip(reason)


def to_phys(view, sx: float, sy: float) -> tuple[int, int]:
    """view の scene 座標 (sx, sy) → 物理スクリーンピクセル（DPR スケール）。"""
    vp = view.plot_widget.mapFromScene(QPoint(int(sx), int(sy)))
    g = view.plot_widget.viewport().mapToGlobal(vp)
    dpr = view.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def at(x: float, y: float, flag: int) -> None:
    _user32.SetCursorPos(int(x), int(y))
    _user32.mouse_event(flag, 0, 0, 0, 0)


def key(vk: int, *, down: bool = True, up: bool = True) -> None:
    if down:
        _user32.keybd_event(vk, 0, KEYDOWN, 0)
    if up:
        _user32.keybd_event(vk, 0, KEYUP, 0)


def drive_qdrag(
    press_phys: tuple[int, int],
    waypoints_phys: list[tuple[int, int]],
    *,
    done: Callable[[], bool],
    modifier_vk: int | None = None,
    threshold_dy: int = 15,
    pump_deadline_s: float = 15.0,
    watchdog_s: float = 3.0,
) -> None:
    """実 OS QDrag を別スレッドで駆動し、GUI スレッドを done() まで pump する。

    press_phys: 物理ピクセルの press 点（ドラッグ元）。
    waypoints_phys: 閾値 move 後の物理ピクセル move 停止点列（末尾＝ドロップ点）。
    done: GUI スレッドで poll する述語（例 lambda: view.drop_seen）。
    modifier_vk: ジェスチャ全体で保持する修飾キー VK（例 VK_CONTROL で Ctrl 結合）。
    threshold_dy: 最初の move を press_y+threshold_dy（垂直）にしてドラッグ閾値を超える。
    """
    finished = threading.Event()
    sx, sy = press_phys
    dx, dy = waypoints_phys[-1]

    def drive() -> None:
        time.sleep(0.3)  # GUI スレッドが pump に到達するのを待つ
        if modifier_vk is not None:
            _user32.keybd_event(modifier_vk, 0, KEYDOWN, 0)
        at(sx, sy, LDOWN)
        time.sleep(0.1)
        at(sx, sy + threshold_dy, MOVE)  # 閾値超え → QDrag.exec 開始
        time.sleep(0.2)
        for wx, wy in waypoints_phys:
            at(wx, wy, MOVE)
            time.sleep(0.2)
        time.sleep(0.1)
        at(dx, dy, LUP)  # drop
        if modifier_vk is not None:
            _user32.keybd_event(modifier_vk, 0, KEYUP, 0)
        if not finished.wait(timeout=watchdog_s):  # 停滞 → キャンセル
            _user32.keybd_event(VK_ESCAPE, 0, KEYDOWN, 0)
            _user32.keybd_event(VK_ESCAPE, 0, KEYUP, 0)
            at(dx, dy, LUP)

    worker = threading.Thread(target=drive, daemon=True)
    worker.start()
    deadline = time.monotonic() + pump_deadline_s
    while not done() and worker.is_alive() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    finished.set()
    worker.join(timeout=4.0)
