"""Layer B: GraphAreaView が offset_apply_requested を VM に配線する (R14)。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication, QSplitter
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
    eid = panel_view.entry_id_for(signal_key)
    base = np.asarray(panel_view.curve_xy(eid)[0]).copy()

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
    after = np.asarray(panel_view.curve_xy(eid)[0])
    np.testing.assert_allclose(after, base + 0.5)


def test_dragged_panel_rerenders_clipped_not_preview(qtbot: QtBot) -> None:
    """Bug B regression: _finish_offset must clear the drag state BEFORE emitting.

    The emit synchronously triggers the offsets broadcast → every panel's
    refresh().  If the dragged panel's _offset_drag_key is still set at emit time,
    its refresh hits the mid-drag guard and RE-APPLIES the full unclipped preview
    data over the VM's authoritative clipped render — desyncing it from
    broadcast-only sibling panels.  Two panels share a clipping x_range here; after
    apply both must hold IDENTICAL clipped arrays (the dragged panel must not
    retain the longer preview array).  Mirrors the realgui cross-panel assertion.
    """
    view, app, area_vm, signal_key = _area_view(qtbot)
    area_vm.add_panel(0)  # tab 0 now holds two panels in the splitter
    area_vm.panels(0)[1].add_signal_to_axis(
        signal_key, 0
    )  # panels(0)[0] already has it
    for _ in range(3):
        QApplication.processEvents()

    splitter = view.tabs.widget(0)
    assert isinstance(splitter, QSplitter)
    panels = [
        splitter.widget(i)
        for i in range(splitter.count())
        if isinstance(splitter.widget(i), GraphPanelView)
    ]
    assert len(panels) == 2
    p0, p1 = panels

    # Clipping window: signal spans t∈[0,0.29]; a +0.15 offset pushes the upper
    # half out of [0,0.29], so the VM render clips to fewer points than the full
    # 30-sample preview.  Both panels pinned to the same window → identical clip.
    for p in panels:
        p.vm.x_range = (0.0, 0.29)
    for _ in range(3):
        QApplication.processEvents()

    eid0 = p0.entry_id_for(signal_key)
    eid1 = p1.entry_id_for(signal_key)
    full_len = len(np.asarray(p0.curve_xy(eid0)[0]))

    # Put p0 into the mid-drag state the real gesture leaves at release time, then
    # finish through the real apply path (apply_dialog_fn → "signal").  The pixel→
    # Δt conversion is hard to pin, so the state is set directly; the finish→emit→
    # broadcast→refresh path under test is exercised unchanged.
    xs0, ys0 = p0._items[eid0].getData()
    p0._apply_dialog_fn = lambda k, dt: "signal"  # type: ignore[assignment]
    p0._offset_drag_key = eid0
    p0._offset_drag_start_x = 0.0
    p0._offset_orig_xy = (np.asarray(xs0).copy(), np.asarray(ys0).copy())
    p0._offset_orig_pen = p0._items[eid0].opts.get("pen")
    p0._offset_last_delta = 0.15
    p0._items[eid0].setData(np.asarray(xs0) + 0.15, ys0)  # preview applied

    p0._finish_offset(eid0, 0.15)
    for _ in range(3):
        QApplication.processEvents()

    assert app.signal_offsets == {signal_key: 0.15}
    x0 = np.asarray(p0.curve_xy(eid0)[0])
    x1 = np.asarray(p1.curve_xy(eid1)[0])
    # Clipping must have shortened the render (else the test cannot distinguish
    # preview from clipped — guards the test's own meaningfulness).
    assert len(x1) < full_len
    # The dragged panel must match the broadcast-only panel exactly (no stale
    # preview points retained).
    np.testing.assert_array_equal(x0, x1)
    assert float(x0.min()) > 0.0  # offset actually applied
