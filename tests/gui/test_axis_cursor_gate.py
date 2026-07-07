"""PC-13: Y 軸ホバーのカーソル — アクティブ軸=ゾーン別・非アクティブ軸=活性化ヒント。"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.cursor_shapes import CursorKind
from valisync.gui.views.graph_panel_view import GraphPanelView


def _view(qtbot: QtBot, tmp_path: Path) -> GraphPanelView:
    csv_file = tmp_path / "d.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "s1"])
        for i in range(50):
            w.writerow([i * 0.01, float(i)])
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    session = Session()
    session.load(csv_file, fmt)
    vm = GraphPanelVM(session)
    vm.add_signal(session.signals()[0].name)
    view = GraphPanelView(vm)
    qtbot.addWidget(view)
    view.resize(800, 500)
    return view


def _hover(axis, lx, ly):
    ev = MagicMock()
    ev.pos.return_value = type("P", (), {"x": lambda self: lx, "y": lambda self: ly})()
    axis.hoverMoveEvent(ev)


def test_non_active_axis_hover_shows_pointing_hand(
    qtbot: QtBot, tmp_path: Path
) -> None:
    view = _view(qtbot, tmp_path)
    axis = view._y_axes[0]
    view._active_axis_index = None  # どの軸もアクティブでない
    _hover(axis, 15.0, 60.0)
    assert axis.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_active_axis_hover_shows_zone_cursor(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    view = _view(qtbot, tmp_path)
    axis = view._y_axes[0]
    view._active_axis_index = axis._vm_axis_index  # この軸をアクティブに
    # ゲート挙動に集中(boundingRect 高さ依存の zone 判定を避ける): cursor_for_local を固定
    monkeypatch.setattr(axis, "cursor_for_local", lambda lx, ly, h: CursorKind.PAN_V)
    _hover(axis, 15.0, 60.0)
    assert axis.cursor().shape() == Qt.CursorShape.SizeVerCursor
