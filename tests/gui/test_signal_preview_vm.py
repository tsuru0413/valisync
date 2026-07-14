"""Tests for SignalPreviewVM (FU-13): preview properties + downsampled waveform."""

from __future__ import annotations

import numpy as np
from pytestqt.qtbot import QtBot

from valisync.core.models import Signal
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM


def _sig(name: str, ts: np.ndarray, vs: np.ndarray) -> Signal:
    return Signal(
        name=name,
        timestamps=ts,
        values=vs,
        file_format="MDF4",
        bus_type="CAN",
        source_file="",
        metadata={"unit": "km/h", "comment": "veh speed"},
    )


def _vm(qtbot: QtBot) -> SignalPreviewVM:
    app_vm = AppViewModel()
    ts = np.arange(0.0, 100.0, 1.0)
    vs = np.sin(ts)
    app_vm.session.group_signals = lambda k: [_sig("g::Speed", ts, vs)]
    app_vm.set_active_file("g")
    return SignalPreviewVM(app_vm)


def test_properties_include_name_unit_samples_timerange_minmax(qtbot: QtBot) -> None:
    vm = _vm(qtbot)
    vm.set_signal("g::Speed")
    props = dict(vm.properties())
    assert props["名前"] == "g::Speed"
    assert props["単位"] == "km/h"
    assert props["サンプル数"] == "100"
    assert "時間範囲" in props and "s" in props["時間範囲"]
    assert "最小値" in props and "最大値" in props
    assert props["コメント"] == "veh speed"


def test_properties_empty_for_unknown_or_none(qtbot: QtBot) -> None:
    vm = _vm(qtbot)
    assert vm.properties() == []  # no signal set
    vm.set_signal("g::Missing")
    assert vm.properties() == []


def test_plot_data_downsampled_within_range(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    ts = np.arange(0.0, 10000.0, 1.0)  # 10k points
    vs = np.cos(ts)
    app_vm.session.group_signals = lambda k: [_sig("g::Big", ts, vs)]
    app_vm.set_active_file("g")
    vm = SignalPreviewVM(app_vm)
    vm.set_signal("g::Big")
    data = vm.plot_data()
    assert data is not None
    x, y = data
    assert 0 < len(x) <= 480  # downsampled to <= _PREVIEW_POINTS
    assert len(x) == len(y)
    assert x[0] >= 0.0 and x[-1] <= 9999.0  # within original range


def test_plot_data_none_for_unknown(qtbot: QtBot) -> None:
    vm = _vm(qtbot)
    vm.set_signal("g::Missing")
    assert vm.plot_data() is None


def test_time_range_does_not_materialize_sorted_view_cache(qtbot: QtBot) -> None:
    """properties() must read time range via Signal.time_range() (raw min/max),
    NOT sorted_view()[0][0]/[-1] which would inflate the FU-20 float64 cache
    (memory signal_range_via_sorted_view_materializes_float64_cache)."""
    app_vm = AppViewModel()
    ts = np.arange(0.0, 50.0, 1.0)
    sig = _sig("g::S", ts, np.sin(ts))
    app_vm.session.group_signals = lambda k: [sig]
    app_vm.set_active_file("g")
    vm = SignalPreviewVM(app_vm)
    vm.set_signal("g::S")
    # Reading properties (time range) must not populate the sorted-view cache.
    # The cache attribute is only ever set via object.__setattr__ inside
    # sorted_view()/finite_view() (it is not a dataclass field), so it may not
    # exist at all yet -- use getattr with a default, matching the existing
    # idiom in tests/test_session.py and tests/test_signal_sorted_view.py.
    _ = vm.properties()
    assert getattr(sig, "_sorted_view_cache", None) is None
