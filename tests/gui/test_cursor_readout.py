"""CursorReadout フロート表ウィジェット (R15.2 読み取り面)。"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.graph_panel_vm import CursorReading
from valisync.gui.views.cursor_readout import CursorReadout


def test_set_readings_builds_one_row_per_signal(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings(
        [
            CursorReading("csv::vCar", "#1f77b4", 12.34, True),
            CursorReading("csv::aLong", "#ff7f0e", 0.56, True),
        ]
    )
    texts = w.row_texts()
    assert len(texts) == 2
    assert texts[0][0] == "csv::vCar"
    assert "12.34" in texts[0][1]


def test_out_of_range_shows_label(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings([CursorReading("csv::vCar", "#1f77b4", None, False)])
    assert w.row_texts()[0][1] == "範囲外"


def test_empty_readings_clears_rows(qtbot: QtBot):
    w = CursorReadout()
    qtbot.addWidget(w)
    w.set_readings([CursorReading("csv::vCar", "#1f77b4", 1.0, True)])
    w.set_readings([])
    assert w.row_texts() == []
