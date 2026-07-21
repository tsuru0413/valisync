# ruff: noqa: RUF002, RUF003
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
RDOWN, RUP = 0x0008, 0x0010
WHEEL = 0x0800  # MOUSEEVENTF_WHEEL — dwData に ±WHEEL_DELTA(120) の倍数 (正=上)
KEYDOWN, KEYUP = 0x0000, 0x0002
VK_RETURN, VK_ESCAPE, VK_CONTROL, VK_SHIFT = 0x0D, 0x1B, 0x11, 0x10
# Arrow keys (Win32 virtual-key codes) for cursor stepping realgui (PC-08).
VK_LEFT, VK_RIGHT = 0x25, 0x27

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


def click_with_modifier(x: int, y: int, modifier_vk: int) -> None:
    """実 OS: 修飾キー (VK) を押下したまま物理 (x, y) を左クリックし最後に離す。

    Windows は WM_LBUTTONDOWN 生成時の非同期キー状態から MK_SHIFT 等の修飾フラグを
    立てるため、``keybd_event`` で修飾キーを先に押下してから ``mouse_event`` を
    発行すれば Qt の ``event.modifiers()`` に反映される (Shift+クリックの実経路 —
    合成 QMouseEvent の modifiers 直渡しでは検証できない部分)。修飾はキーを離すまで
    保持されるので、押下は release まで維持してから戻す。押下/離下の間に短い
    wall-clock を挟み OS がキー状態を登録する猶予を与える (呼び出し側で
    processEvents を pump する)。
    """
    _user32.keybd_event(modifier_vk, 0, KEYDOWN, 0)
    time.sleep(0.03)
    try:
        at(x, y, LDOWN)
        time.sleep(0.03)
        at(x, y, LUP)
        time.sleep(0.03)
    finally:
        _user32.keybd_event(modifier_vk, 0, KEYUP, 0)


def press_grip_and_confirm(view, axis_idx: int, edge: str, gx: int, gy: int) -> None:
    """LDOWN at a Y-axis grip, then jiggle a small IN-BAND move until pyqtgraph
    has started the drag AND classified it as this grip.

    The zone is classified exactly once, at the first *delivered* move past the
    drag threshold (GraphicsScene moveDistance=5 logical px). pyqtgraph's
    mouseRateLimit drops moves closer than its window (10ms at the default
    100/s) and Qt compresses queued moves under load, so fixed-step driving can
    make the first delivered move land 2+ steps (>=12.8 logical px) from the
    press — outside the ~12px grip band — and the one-shot classification
    mis-routes the gesture to zoom/pan (machine-load-dependent flake: 0/4 even
    on main, diagnosed 2026-07-17 with per-step OS-echo/drag-event/zone
    instrumentation). Jiggling ±1px around an in-band point until the
    classification observable confirms pins the crossing inside the band
    structurally. Only after confirmation may the cursor leave the band:
    grip tracking is absolute per event (the finish event updates the edge
    too), so later move coalescing is harmless.

    ``scene.dragButtons`` guards against a false-positive from hover: hover
    also writes ``_zone``, so the zone alone can read as the grip before the
    drag has actually started.
    """
    import pytest

    from valisync.gui.views.graph_panel_view import (
        AXZONE_GRIP_BOTTOM,
        AXZONE_GRIP_TOP,
    )

    expected = AXZONE_GRIP_TOP if edge == "top" else AXZONE_GRIP_BOTTOM
    axis = view._y_axes[axis_idx]
    scene = view.plot_widget.scene()
    # 7 logical px into the band: past the threshold (5), and press(2px inside
    # the spine edge) + 7 stays under the 12px band even at DPR 1.0.
    j = round(7 * view.devicePixelRatioF())
    jiggle_y = gy + j if edge == "top" else gy - j
    at(gx, gy, LDOWN)
    QApplication.processEvents()
    time.sleep(0.05)
    deadline = time.monotonic() + 3.0
    n = 0
    while time.monotonic() < deadline:
        # 同一点への SetCursorPos は WM_MOUSEMOVE を生まない → ±1px 交互
        at(gx, jiggle_y + (n % 2), MOVE)
        n += 1
        QApplication.processEvents()
        if scene.dragButtons and getattr(axis, "_zone", None) == expected:
            return
        time.sleep(0.02)
    at(gx, jiggle_y, LUP)  # 失敗時もボタンを離してから落とす (後続テスト保護)
    pytest.fail(
        f"grip drag crossing not confirmed (zone={getattr(axis, '_zone', None)},"
        f" dragButtons={scene.dragButtons}, jiggles={n})"
    )


def wheel(x: float, y: float, delta: int) -> None:
    """カーソルを物理 (x, y) へ置き、実 OS ホイールを delta だけ回す。

    delta は WHEEL_DELTA(120) の倍数 (負=下スクロール)。ホイールはカーソル下の
    ウィジェットへ配送されるため、対象 viewport 上に置いてから発行する。QDrag と
    違い OLE モーダルループは無く、processEvents の pump だけで配送される
    (FU-01 で確立・repo 初の実ホイール)。
    """
    _user32.SetCursorPos(int(x), int(y))
    _user32.mouse_event(WHEEL, 0, 0, delta, 0)


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """トップレベルウィンドウの外枠 (left, top, width, height)・物理ピクセル。"""
    r = _RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def set_window_pos(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    """実 OS の WM 経由でトップレベルウィンドウを移動/リサイズする。

    user32.SetWindowPos (SWP_NOZORDER) を Qt の外から発行し、WM_SIZE ->
    QResizeEvent の実変換経路を通す (FU-02 で確立)。widget.resize() は
    アプリ発で headless でも同様に動き OS/ユーザー発のリサイズを証明しない
    のに対し、外部 SetWindowPos は OS 発＝ユーザーのフレームドラッグと
    同方向の実経路を証明する。座標は物理ピクセル・外枠基準 —
    現在値は window_rect() で取得して差分リサイズすると DPR 換算が不要。
    """
    swp_nozorder = 0x0004
    _user32.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), swp_nozorder)


def double_click_interval_s() -> float:
    """OS のダブルクリック窓の半分（上限 150ms）— 確実に窓内に収める。"""
    ms = _user32.GetDoubleClickTime() if _user32 is not None else 500
    return min(ms / 2, 150) / 1000.0


def double_click(x: int, y: int) -> None:
    """実 OS ダブルクリック: 同一物理点へ窓内 2 連打（MOVE なし）。

    各イベント間で event loop を pump する（間隔ゼロの連打は OS が dblclick と
    認識しない）。OS が 2 組目の press を WM_LBUTTONDBLCLK に合体させる
    (Qt: MouseButtonDblClick)。test_diagnostics_dock_realinput.py /
    test_tab_ui_flow.py の module-local 版を 3 使用箇所目で共有昇格したもの
    (既存 2 ファイルの module-local 版は本増分のスコープ外で触らない)。
    """

    def _pump(dt: float) -> None:
        QApplication.processEvents()
        time.sleep(dt)

    at(x, y, LDOWN)
    _pump(0.03)
    at(x, y, LUP)
    _pump(double_click_interval_s())
    at(x, y, LDOWN)
    _pump(0.03)
    at(x, y, LUP)
    for _ in range(4):
        _pump(0.02)


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
    # 末尾要素をドロップ点に使うため空列は契約違反。曖昧な IndexError ではなく
    # 明示エラーで弾く（後続フェーズで新規 call site が増えても安全側に倒す）。
    if not waypoints_phys:
        raise ValueError("drive_qdrag requires at least one waypoint")
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
