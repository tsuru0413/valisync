"""PC-22+オフセット誤発火: カーソル線=SizeHor、プロット曲線上ホバー=SizeHor(ドラッグ可)。"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
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


def test_cursor_line_has_sizehor_cursor(qtbot: QtBot, tmp_path: Path) -> None:
    view = _view(qtbot, tmp_path)
    assert view._cursor_line.cursor().shape() == Qt.CursorShape.SizeHorCursor
    assert view._cursor_line_b.cursor().shape() == Qt.CursorShape.SizeHorCursor


def test_hover_cursor_over_curve_is_drag_h(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    view = _view(qtbot, tmp_path)
    # プロット領域内の点で _curve_at が命中する状況を固定
    monkeypatch.setattr(view, "_zone_at", lambda pos: "plot")
    monkeypatch.setattr(view, "_curve_at", lambda pos: "csv_1::s1")
    assert view._hover_cursor(QPointF(100.0, 100.0)) == CursorKind.DRAG_H


def test_hover_cursor_over_empty_plot_is_arrow(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    view = _view(qtbot, tmp_path)
    monkeypatch.setattr(view, "_zone_at", lambda pos: "plot")
    monkeypatch.setattr(view, "_curve_at", lambda pos: None)
    assert view._hover_cursor(QPointF(100.0, 100.0)) == CursorKind.ARROW
