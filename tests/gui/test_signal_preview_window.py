"""Tests for SignalPreviewWindow (FU-13): 2-tab preview + properties window."""

from __future__ import annotations

import numpy as np
from pytestqt.qtbot import QtBot

from valisync.core.models import Signal
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM
from valisync.gui.views.signal_preview_window import SignalPreviewWindow


def _sig(name: str) -> Signal:
    ts = np.arange(0.0, 200.0, 1.0)
    return Signal(
        name=name,
        timestamps=ts,
        values=np.sin(ts),
        file_format="MDF4",
        bus_type="CAN",
        source_file="",
        metadata={"unit": "V"},
    )


def _window(qtbot: QtBot) -> SignalPreviewWindow:
    app_vm = AppViewModel()
    app_vm.session.group_signals = lambda k: [_sig("g::A"), _sig("g::B")]
    app_vm.set_active_file("g")
    app_vm.register_loaded("g")  # E-0: display_name scope = loaded_file_keys
    win = SignalPreviewWindow(SignalPreviewVM(app_vm))
    qtbot.addWidget(win)
    return win


def test_two_tabs_present_with_titles(qtbot: QtBot) -> None:
    win = _window(qtbot)
    titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert titles == ["プレビュー", "信号プロパティ"]


def test_show_signal_populates_plot_and_properties(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_signal("g::A")
    # Preview tab: a curve is drawn.
    assert len(win.preview_plot.listDataItems()) == 1
    # Properties tab: rows populated (name row present).
    assert win.property_row_count() >= 1


def test_show_signal_replaces_content_single_instance(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_signal("g::A")
    win.show_signal("g::B")  # same window, content swapped
    assert len(win.preview_plot.listDataItems()) == 1  # not accumulated
    # E-0 (UX-19): windowTitle shows the bare display name "B", not "g::B"
    # (no collision here — single loaded file).
    assert win.windowTitle().endswith("B")


def test_show_signal_unknown_shows_no_curve(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_signal("g::Missing")
    assert len(win.preview_plot.listDataItems()) == 0
    assert win.property_row_count() == 0


# ─── axis labels (UX-43, spec §3) ──────────────────────────────────────────


def test_preview_axis_labels_bottom_time_left_display_name_unit(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_signal("g::A")
    bottom = win.preview_plot.getAxis("bottom")
    left = win.preview_plot.getAxis("left")
    assert bottom.labelText == "Time"
    assert bottom.labelUnits == "s"
    # E-0: display name only -- the raw "g::A" key must never leak into the
    # left-axis label (sabotage: using _signal().name directly would put
    # "g::A" here instead of "A").
    assert left.labelText == "A"
    assert "::" not in left.labelText
    assert left.labelUnits == "V"  # from _sig()'s metadata unit


def test_preview_axis_label_swaps_with_shown_signal(qtbot: QtBot) -> None:
    win = _window(qtbot)
    win.show_signal("g::A")
    win.show_signal("g::B")  # same window instance -- label must not be stale
    left = win.preview_plot.getAxis("left")
    assert left.labelText == "B"
