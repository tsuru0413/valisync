"""Shared test factory for GraphPanelView with two real signals/axes.

Imported by tests/gui/ (Layer A/B headless tests) and tests/realgui/ (Layer C
real-OS-input tests) — placed here so both can use ``from tests.gui._panel_factory
import make_two_axis_panel`` with pytest's ``--import-mode=importlib`` (which adds
the rootdir to sys.path, making ``tests`` importable as a namespace package).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_area_view import GraphAreaView
from valisync.gui.views.graph_panel_view import GraphPanelView


def make_single_signal_panel() -> GraphPanelView:
    """Build a GraphPanelView with ONE linear signal on a single axis.

    The signal is ``v = t`` over ``t in [0, 1)`` so the curve passes through the
    plot's geometric centre (x=0.5 → y=0.5 = mid of the auto-fit y-range). That
    makes a click at the plot-rect centre land on the curve — ideal for hit-test
    and offset-drag tests (Layer B/C). Runs on the offscreen platform.
    """
    d = Path(tempfile.mkdtemp())
    csv = d / "lin.csv"
    rows = ["t,lin"] + [f"{i / 50.0:.4f},{i / 50.0:.4f}" for i in range(50)]
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
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(keys[0], 0)
    return GraphPanelView(vm)


def make_two_axis_panel() -> GraphPanelView:
    """Build a GraphPanelView with two axes, each holding one real signal.

    Creates a temporary CSV with signals ``s1`` and ``s2``, loads it into a
    Session, and assigns each signal to its own axis (axis 0 = s1, axis 1 =
    s2, both in the inner column).  Returns the live GraphPanelView so callers
    can inspect state or drive click/drag events.

    The panel runs on the offscreen platform (set by ``tests/gui/conftest.py``
    before Qt is imported) so no real display is needed.
    """
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1,s2"] + [
        f"{i * 0.01:.3f},{i % 50}.0,{(i * 2) % 50}.0" for i in range(50)
    ]
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
            signal_end_column=2,
            has_header=True,
        ),
    )
    keys = sorted(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(keys[0], 0)
    vm.create_new_axis(keys[1])
    return GraphPanelView(vm)


def make_two_axis_area() -> GraphAreaView:
    """Build a GraphAreaView whose sole tab/panel holds two signals on two axes.

    Same s1/s2 data and axis layout as ``make_two_axis_panel``, but wrapped in
    the GraphAreaView container (single tab, single panel, auto-active) so
    callers that need the panel's owning readout pane (readout-pane Task 4
    moved CursorReadout ownership off GraphPanelView onto GraphAreaView) can
    reach it via ``area.readout_pane``. The panel widget itself is
    ``area.tabs.widget(0).widget(0)``.
    """
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1,s2"] + [
        f"{i * 0.01:.3f},{i % 50}.0,{(i * 2) % 50}.0" for i in range(50)
    ]
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
            signal_end_column=2,
            has_header=True,
        ),
    )
    keys = sorted(s.name for s in session.signals())
    vm = GraphAreaVM(AppViewModel(session))
    panel_vm = vm.panels(0)[0]  # GraphAreaVM always starts with one empty panel
    panel_vm.add_signal_to_axis(keys[0], 0)
    panel_vm.create_new_axis(keys[1])
    return GraphAreaView(vm)
