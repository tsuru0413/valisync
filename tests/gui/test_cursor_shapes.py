"""カーソルレジストリ: CursorKind -> QCursor 解決とキャッシュ(増分②)。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.views.cursor_shapes import CursorKind, cursor


def test_standard_kinds_resolve_to_expected_shape(qtbot: QtBot):
    assert cursor(CursorKind.ARROW).shape() == Qt.CursorShape.ArrowCursor
    assert cursor(CursorKind.PAN_H).shape() == Qt.CursorShape.SizeHorCursor
    assert cursor(CursorKind.PAN_V).shape() == Qt.CursorShape.SizeVerCursor
    assert cursor(CursorKind.RESIZE_V).shape() == Qt.CursorShape.SizeVerCursor
    assert cursor(CursorKind.MOVE).shape() == Qt.CursorShape.SizeAllCursor
    assert cursor(CursorKind.ACTIVATE).shape() == Qt.CursorShape.PointingHandCursor
    assert cursor(CursorKind.DRAG_H).shape() == Qt.CursorShape.SizeHorCursor


def test_zoom_kinds_are_custom_bitmap_cursors(qtbot: QtBot):
    for k in (CursorKind.ZOOM_H, CursorKind.ZOOM_V):
        c = cursor(k)
        assert c.shape() == Qt.CursorShape.BitmapCursor
        assert not c.pixmap().isNull()  # 実 pixmap が描かれている


def test_same_kind_is_cached(qtbot: QtBot):
    assert cursor(CursorKind.ZOOM_H) is cursor(CursorKind.ZOOM_H)
    assert cursor(CursorKind.PAN_H) is cursor(CursorKind.PAN_H)
