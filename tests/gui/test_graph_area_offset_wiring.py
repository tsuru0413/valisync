"""Layer B: GraphAreaView が offset_apply_requested を VM に配線する (R14)。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.views.graph_area_view import GraphAreaView
from valisync.gui.views.graph_panel_view import GraphPanelView


def _area_view(qtbot: QtBot):
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1"] + [f"{i * 0.01:.3f},{i}.0" for i in range(30)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    app = AppViewModel()
    app.request_load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    signal_key = sorted(s.name for s in app.signals())[0]
    area_vm = GraphAreaVM(app)
    area_vm.panels(0)[0].add_signal_to_axis(signal_key, 0)
    view = GraphAreaView(area_vm)
    qtbot.addWidget(view)
    view.resize(700, 500)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    return view, app, area_vm, signal_key


def _first_panel_view(area_view) -> GraphPanelView:
    splitter = area_view.tabs.widget(0)
    for i in range(splitter.count()):
        w = splitter.widget(i)
        if isinstance(w, GraphPanelView):
            return w
    raise AssertionError("no GraphPanelView found")


def test_offset_request_updates_app_and_rerenders(qtbot: QtBot) -> None:
    view, app, _area_vm, signal_key = _area_view(qtbot)
    panel_view = _first_panel_view(view)
    base = np.asarray(panel_view.curve_xy(signal_key)[0]).copy()

    # Wide x_range so the +0.5 shifted data (0.5-0.79) stays in view after the
    # broadcast refresh.  Without this the auto-fit window (~0-0.29) excludes the
    # shifted points and curve_xy returns empty arrays (false-green pitfall from
    # Tasks 2 & 3).  x_range is set directly (no notify) so the subsequent
    # set_offsets broadcast is the sole cause of the cache bust.
    panel_view.vm.x_range = (0.0, 1.0)

    panel_view.offset_apply_requested.emit(signal_key, 0.5, "signal")
    for _ in range(3):
        QApplication.processEvents()

    assert app.signal_offsets == {signal_key: 0.5}
    after = np.asarray(panel_view.curve_xy(signal_key)[0])
    np.testing.assert_allclose(after, base + 0.5)
