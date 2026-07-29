"""Tests for SignalPreviewWindow (FU-13): 2-tab preview + properties window."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from pytestqt.qtbot import QtBot

from valisync.core.models import Signal, SignalGroup
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM
from valisync.gui.views.signal_preview_window import SignalPreviewWindow

_BASE_DIR = Path(__file__).resolve().parent


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


def _window(qtbot: QtBot) -> tuple[SignalPreviewWindow, str]:
    """E-3: プレビューは解決器経由になったので、実際に SignalGroup を登録する
    (group_signals の monkeypatch では信号に到達できない)。"""
    app_vm = AppViewModel()
    key = app_vm.session._groups.add(
        SignalGroup(
            signals=(_sig("A"), _sig("B")),
            source_path=_BASE_DIR / "w.mf4",
            file_format="MDF4",
            loaded_at=datetime.now(),
        )
    )
    app_vm.set_active_file(key)
    app_vm.register_loaded(key)  # E-0: display_name scope = loaded_file_keys
    win = SignalPreviewWindow(SignalPreviewVM(app_vm))
    qtbot.addWidget(win)
    return win, key


def test_two_tabs_present_with_titles(qtbot: QtBot) -> None:
    win, _key = _window(qtbot)
    titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert titles == ["プレビュー", "信号プロパティ"]


def test_show_signal_populates_plot_and_properties(qtbot: QtBot) -> None:
    win, key = _window(qtbot)
    win.show_signal(f"{key}::A")
    # Preview tab: a curve is drawn.
    assert len(win.preview_plot.listDataItems()) == 1
    # Properties tab: rows populated (name row present).
    assert win.property_row_count() >= 1


def test_show_signal_replaces_content_single_instance(qtbot: QtBot) -> None:
    win, key = _window(qtbot)
    win.show_signal(f"{key}::A")
    win.show_signal(f"{key}::B")  # same window, content swapped
    assert len(win.preview_plot.listDataItems()) == 1  # not accumulated
    # E-0 (UX-19): windowTitle は bare 表示名 "B" (生キーではない)
    assert win.windowTitle().endswith("B")


def test_show_signal_unknown_shows_no_curve(qtbot: QtBot) -> None:
    win, key = _window(qtbot)
    win.show_signal(f"{key}::Missing")
    assert len(win.preview_plot.listDataItems()) == 0
    assert win.property_row_count() == 0


# ─── axis labels (UX-43, spec §3) ──────────────────────────────────────────


def test_preview_axis_labels_bottom_time_left_display_name_unit(qtbot: QtBot) -> None:
    win, key = _window(qtbot)
    win.show_signal(f"{key}::A")
    bottom = win.preview_plot.getAxis("bottom")
    left = win.preview_plot.getAxis("left")
    assert bottom.labelText == "Time"
    assert bottom.labelUnits == "s"
    # E-0: display name only -- 生の名前空間つきキーが軸ラベルへ漏れてはならない
    assert left.labelText == "A"
    assert "::" not in left.labelText
    assert left.labelUnits == "V"  # from _sig()'s metadata unit


def test_preview_axis_label_swaps_with_shown_signal(qtbot: QtBot) -> None:
    win, key = _window(qtbot)
    win.show_signal(f"{key}::A")
    win.show_signal(f"{key}::B")  # same window instance -- label must not be stale
    left = win.preview_plot.getAxis("left")
    assert left.labelText == "B"
