"""カーソルレジストリ: ゾーン判定が返す CursorKind を QCursor に解決する単一地点。

カスタムズームカーソル(QPixmap 描画)を遅延生成・キャッシュし、ゾーン判定側
(cursor_for_zone / cursor_for_local)は QApplication 非依存の純粋関数に保つ。
新カーソルは CursorKind に1つ足し、_STANDARD か _build_zoom_cursor に対応を追加するだけ。
"""

from __future__ import annotations

import enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap


class CursorKind(enum.Enum):
    ARROW = "arrow"
    PAN_H = "pan_h"
    PAN_V = "pan_v"
    ZOOM_H = "zoom_h"
    ZOOM_V = "zoom_v"
    RESIZE_V = "resize_v"
    MOVE = "move"
    ACTIVATE = "activate"
    DRAG_H = "drag_h"


_STANDARD: dict[CursorKind, Qt.CursorShape] = {
    CursorKind.ARROW: Qt.CursorShape.ArrowCursor,
    CursorKind.PAN_H: Qt.CursorShape.SizeHorCursor,
    CursorKind.PAN_V: Qt.CursorShape.SizeVerCursor,
    CursorKind.RESIZE_V: Qt.CursorShape.SizeVerCursor,
    CursorKind.MOVE: Qt.CursorShape.SizeAllCursor,
    CursorKind.ACTIVATE: Qt.CursorShape.PointingHandCursor,
    CursorKind.DRAG_H: Qt.CursorShape.SizeHorCursor,
}

_CACHE: dict[CursorKind, QCursor] = {}


def cursor(kind: CursorKind) -> QCursor:
    """Resolve a CursorKind to a cached QCursor (lazy; needs a running QApplication)."""
    c = _CACHE.get(kind)
    if c is not None:
        return c
    if kind in _STANDARD:
        c = QCursor(_STANDARD[kind])
    elif kind is CursorKind.ZOOM_H:
        c = _build_zoom_cursor(horizontal=True)
    elif kind is CursorKind.ZOOM_V:
        c = _build_zoom_cursor(horizontal=False)
    else:
        c = QCursor(Qt.CursorShape.ArrowCursor)  # defensive fallback
    _CACHE[kind] = c
    return c


def _build_zoom_cursor(horizontal: bool) -> QCursor:
    """Draw a two-end-bars + inward-arrows zoom cursor (horizontal / vertical variant).

    白ハロー(太)+黒線(細)の二重描画で明暗どちらの背景でも視認できる。垂直版は
    水平版を90度入れ替えた座標で描く。ホットスポットは中心。
    """
    size = 32
    c = size // 2  # center / hotspot
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    def draw(pen: QPen) -> None:
        p.setPen(pen)
        near, far = 4, size - 4  # 端バー位置(主軸)
        b0, b1 = c - 8, c + 8  # 端バーの副軸方向の長さ
        arr_out, arr_in = c - 9, c - 2  # 左/上矢印: 外->内(主軸)
        head = 4  # 矢じりの長さ
        if horizontal:
            p.drawLine(near, b0, near, b1)  # 左バー
            p.drawLine(far, b0, far, b1)  # 右バー
            p.drawLine(arr_out, c, arr_in, c)  # 左矢印の軸(->)
            p.drawLine(arr_in, c, arr_in - head, c - head)  # 矢じり上
            p.drawLine(arr_in, c, arr_in - head, c + head)  # 矢じり下
            rx0, rx1 = size - arr_out, size - arr_in  # 右矢印(<-) 反転
            p.drawLine(rx0, c, rx1, c)
            p.drawLine(rx1, c, rx1 + head, c - head)
            p.drawLine(rx1, c, rx1 + head, c + head)
        else:
            p.drawLine(b0, near, b1, near)  # 上バー
            p.drawLine(b0, far, b1, far)  # 下バー
            p.drawLine(c, arr_out, c, arr_in)  # 上矢印(下向き)
            p.drawLine(c, arr_in, c - head, arr_in - head)
            p.drawLine(c, arr_in, c + head, arr_in - head)
            ry0, ry1 = size - arr_out, size - arr_in  # 下矢印(上向き)
            p.drawLine(c, ry0, c, ry1)
            p.drawLine(c, ry1, c - head, ry1 + head)
            p.drawLine(c, ry1, c + head, ry1 + head)

    draw(QPen(QColor(255, 255, 255), 3))  # 白ハロー(太)
    draw(QPen(QColor(0, 0, 0), 1))  # 黒線(細)
    p.end()
    return QCursor(pm, c, c)  # hotspot at center
