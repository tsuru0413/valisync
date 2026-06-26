"""Tests for SignalTableModel refactored for master-detail (Task 2.2).

Tests verify:
- rowCount matches ChannelBrowserVM.signals count
- columnCount is exactly 2 (Name, Unit)
- data() returns correct name and unit
- model resets when VM notifies 'signals'
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from valisync.core.models import Delimiter, FormatDefinition, Signal
from valisync.gui.adapters.qt_signal_models import SignalTableModel
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM


def _csv_format() -> FormatDefinition:
    return FormatDefinition(
        name="test",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )


def _write_csv(path: Path) -> Path:
    path.write_text("t,sig_a,sig_b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    return path


def test_row_count_matches_signals(qtbot: QtBot, tmp_path: Path) -> None:
    app_vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")
    key = app_vm.request_load(csv_file, _csv_format())
    vm = ChannelBrowserVM(app_vm)
    model = SignalTableModel(vm)

    # Initially empty (no active file)
    assert model.rowCount(QModelIndex()) == 0

    app_vm.set_active_file(key)
    assert model.rowCount(QModelIndex()) == 2


def test_column_count_is_two(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    model = SignalTableModel(vm)
    assert model.columnCount(QModelIndex()) == 2


def test_data_returns_name_and_unit(qtbot: QtBot, tmp_path: Path) -> None:
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    model = SignalTableModel(vm)

    import numpy as np

    sig = Signal(
        name="k::a",
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={"unit": "V"},
    )
    app_vm.session.group_signals = lambda key: [sig]
    app_vm.set_active_file("k")

    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "a"
    assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "V"


def test_header_data(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    model = SignalTableModel(vm)

    assert model.headerData(0, Qt.Orientation.Horizontal) == "Name"
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Unit"


def test_signal_key_at_returns_full_key(qtbot: QtBot, tmp_path: Path) -> None:
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    model = SignalTableModel(vm)

    import numpy as np

    sig = Signal(
        name="k::a",
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="MDF4",
        bus_type="",
        source_file="",
    )
    app_vm.session.group_signals = lambda key: [sig]
    app_vm.set_active_file("k")

    assert model.signal_key_at(model.index(0, 0)) == "k::a"
