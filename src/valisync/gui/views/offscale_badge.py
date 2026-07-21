"""手動レンジ時のオフスケール通知バッジ (Stage A spec §3.6・UX-03 の手動側).

判定は純関数 (Layer A)・表示/クリックは QGraphicsObject (Layer B/C)。
判定母集合は「render と同一の X 窓スライス済み可視カーブの有限値域」—
全信号値域で判定すると窓内だけ範囲外を見逃し/窓内可視を誤点灯する
(設計レビュー捕捉)。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QGraphicsObject

from valisync.gui.theme import tokens

# クリック可能な当たり判定サイズ。24px 未満ターゲット批判 (UX-38) を踏まえ最低 18。
# view の配置ロジック (集約しきい値) も参照する単一の真実なので公開する。
BADGE_PX = 18


def offscale_directions(
    y_range: tuple[float, float],
    curve_windows: list[tuple[float, float] | None],
) -> tuple[bool, bool]:
    """(上外れあり, 下外れあり) — 完全にレンジ外のカーブがある方向 (spec §3.6).

    *curve_windows* は可視エントリごとの「render と同一 X 窓スライス済み
    RenderCurve.values の有限 (min, max)」。サンプル無し/全 NaN は None で渡し
    判定対象外にする (フィットしても見えないため通知は嘘になる)。部分クリップ
    (片端だけ外れ) はレンジ内に手掛かりが残るので外れ扱いしない。
    """
    lo, hi = min(y_range), max(y_range)
    above = any(w is not None and w[0] > hi for w in curve_windows)
    below = any(w is not None and w[1] < lo for w in curve_windows)
    return above, below


class OffscaleBadge(QGraphicsObject):
    """▲/▼ のクリック可能バッジ。クリック = この軸をオートフィット."""

    clicked = Signal()

    def __init__(self, direction: str) -> None:
        super().__init__()
        self._direction = direction
        self.setZValue(30)  # 曲線より上 — z 沈没は isVisible では検出できない
        self.setToolTip("レンジ外の曲線あり — クリックでフィット")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, BADGE_PX, BADGE_PX)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        c = tokens.active().colors.accent_active
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c.r, c.g, c.b, c.a))
        r = self.boundingRect().adjusted(4, 4, -4, -4)
        cx = r.center().x()
        if self._direction == "up":
            pts = [
                QPointF(r.left(), r.bottom()),
                QPointF(r.right(), r.bottom()),
                QPointF(cx, r.top()),
            ]
        else:
            pts = [
                QPointF(r.left(), r.top()),
                QPointF(r.right(), r.top()),
                QPointF(cx, r.bottom()),
            ]
        painter.drawPolygon(QPolygonF(pts))

    def mousePressEvent(self, event: Any) -> None:
        # accept してプロット内クリック (R15 カーソル設置等) へ流さない (spec §3.6)。
        event.accept()

    def mouseReleaseEvent(self, event: Any) -> None:
        event.accept()
        self.clicked.emit()
