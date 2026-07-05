"""PC-21: CursorReadout がプロット矩形へ追従再配置され、ユーザードラッグ位置を尊重する。"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import QPoint
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView


def _vm(tmp_path: Path) -> GraphPanelVM:
    csv_file = tmp_path / "d.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "s1"])
        for i in range(100):
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
    return vm


def _laid_out_view(qtbot: QtBot, tmp_path: Path) -> GraphPanelView:
    view = GraphPanelView(_vm(tmp_path))
    qtbot.addWidget(view)
    view.resize(1000, 700)
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(
        lambda: (
            bool(view._view_boxes)
            and view._view_boxes[0].sceneBoundingRect().height() > 100
        )
    )
    return view


def test_reposition_moves_readout_to_plot_area(qtbot: QtBot, tmp_path: Path) -> None:
    view = _laid_out_view(qtbot, tmp_path)
    view.vm.set_cursor(0.5)  # readout placed
    view._readout.move(400, 300)  # 意図的に誤配置
    view._reposition_readout()
    tl = view._plot_area_top_left()
    assert tl is not None
    assert view._readout.pos() == QPoint(tl.x() + 8, tl.y() + 8)
    assert view._readout.pos() != QPoint(400, 300)


def test_reposition_respects_user_drag(qtbot: QtBot, tmp_path: Path) -> None:
    view = _laid_out_view(qtbot, tmp_path)
    view.vm.set_cursor(0.5)
    view._readout._user_moved = True  # ユーザーがドラッグ移動した状態
    view._readout.move(400, 300)
    view._reposition_readout()
    assert view._readout.pos() == QPoint(400, 300)  # 動かさない


def test_cursor_clear_resets_user_moved(qtbot: QtBot, tmp_path: Path) -> None:
    view = _laid_out_view(qtbot, tmp_path)
    view.vm.set_cursor(0.5)
    view._readout._user_moved = True
    view.vm.set_cursor(None)  # カーソル消去 -> _sync_cursor_from_vm の t is None 経路
    assert view._readout.was_user_moved() is False
