"""Layer B (headless/CI): M11 LOD — GraphPanelView.refresh() must write
LOD-reduced arrays to PlotDataItem, not raw signal arrays.

This is the CI-run false-green guard for M11.  The ViewModel-only tests
(test_lod_benchmark.py) check vm.lod_active / vm.last_rendered_points but
would stay green even if refresh() passed raw 5000-point arrays to pyqtgraph.
This test closes that gap by inspecting PlotDataItem.getData() directly.

The LOD chain is fully synchronous and headless-safe:
  setGeometry → resizeEvent → set_panel_width → _notify → refresh
  → render_data → setData → getData  (no painting / GPU needed)

Honest RED (documents how the guard is non-trivial):
  Replace ``item.setData(curve.timestamps, curve.values)`` at
  graph_panel_view.py line ~790 with raw
  ``item.setData(sig.timestamps, sig.values)`` (bypass LOD).
  → narrow assertion fails: 5000 > 2*200+10 = 410.
  Restore → passes GREEN.

Layer C (tests/realgui/test_active_axis_zoom_pan.py::test_lod_render_after_resize)
retains the visual-density / screenshot proof and coexists with this test.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView


def _make_large_panel() -> tuple[GraphPanelView, GraphPanelVM, str]:
    """Build a GraphPanelView with a 5000-point signal; return (view, vm, key)."""
    n = 5000
    d = Path(tempfile.mkdtemp())
    csv = d / "large.csv"
    rows = ["t,sig"] + [f"{i / 1000.0:.6f},{float(i % 100)}" for i in range(n)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    session = Session()
    session.load(
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
    keys = sorted(s.name for s in session.signals())
    key = keys[0]  # namespaced, e.g. "csv_1::sig"

    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(key, 0)
    return GraphPanelView(vm), vm, key


def test_lod_narrow_viewport_getData_bounded(qtbot: QtBot) -> None:
    """M11 Layer B: narrow viewport → lod_active True + PlotDataItem point count bounded.

    Core guard: the VIEW must pass LOD-reduced arrays to setData, not raw signal
    arrays.  VM tests cannot catch this View-layer regression.

    Honest RED path (documented in module docstring):
      bypass LOD at graph_panel_view.py:~790 → narrow_count = 5000 > 2*200+10 FAILS.
    """
    view, vm, key = _make_large_panel()
    qtbot.addWidget(view)
    view.setGeometry(300, 300, 200, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()

    assert vm.panel_width_px <= 200, f"expected ≤200 px, got {vm.panel_width_px}"
    assert vm.lod_active is True, "5000-pt signal at 200 px width should activate LOD"

    xs_narrow, _ = view._items[key].getData()
    assert xs_narrow is not None, "PlotDataItem has no data after narrow show"
    narrow_count = len(xs_narrow)
    # Core assertion: the VIEW must have called setData with LOD-reduced arrays.
    # A raw-vs-LOD regression (passing signal.timestamps/values directly) would give
    # narrow_count=5000 here and fail this check — which VM tests would miss entirely.
    assert narrow_count <= 2 * vm.panel_width_px + 10, (
        f"View applied raw arrays to PlotDataItem: "
        f"{narrow_count} points > 2*{vm.panel_width_px}+10"
    )


def test_lod_wide_viewport_getData_increases(qtbot: QtBot) -> None:
    """M11 Layer B companion: wide viewport → LOD budget relaxes, getData count grows."""
    view, _vm, key = _make_large_panel()
    qtbot.addWidget(view)
    view.setGeometry(300, 300, 200, 600)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()

    xs_narrow, _ = view._items[key].getData()
    assert xs_narrow is not None, "PlotDataItem has no data after narrow show"
    narrow_count = len(xs_narrow)

    # Widen the panel; resizeEvent fires → set_panel_width(1600) → refresh → LOD relaxes
    view.setGeometry(300, 300, 1600, 600)
    for _ in range(3):
        QApplication.processEvents()

    xs_wide, _ = view._items[key].getData()
    assert xs_wide is not None, "PlotDataItem has no data after wide resize"
    wide_count = len(xs_wide)
    assert wide_count > narrow_count, (
        f"LOD did not relax at wide viewport: wide={wide_count} <= narrow={narrow_count}"
    )
