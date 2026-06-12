"""Tests for ChannelBrowserVM refactored for master-detail (Task 2.1).

Tests verify:
- signals returns a flat list of SignalItem for the active file
- SignalItem includes name and unit
- VM updates when AppViewModel.active_file_key changes
- set_filter() narrows the flat list
"""

from __future__ import annotations

from pathlib import Path
from valisync.core.models import Delimiter, FormatDefinition, Signal
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM

# ─── Helpers ────────────────────────────────────────────────────────────────

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

def _setup_vm(tmp_path: Path) -> tuple[ChannelBrowserVM, AppViewModel, str]:
    app_vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")
    key = app_vm.request_load(csv_file, _csv_format())
    vm = ChannelBrowserVM(app_vm)
    return vm, app_vm, key

# ─── Tests ──────────────────────────────────────────────────────────────────

def test_initial_signals_is_empty() -> None:
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    assert vm.signals == []

def test_signals_populated_when_file_active(tmp_path: Path) -> None:
    vm, app_vm, key = _setup_vm(tmp_path)
    
    app_vm.set_active_file(key)
    
    assert len(vm.signals) == 2
    names = {s.name for s in vm.signals}
    assert names == {"sig_a", "sig_b"}

def test_signal_item_contains_unit(tmp_path: Path) -> None:
    # We can't easily set unit in CSV yet via request_load without core changes,
    # but we can mock or use a fake signal in the session.
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    
    import numpy as np
    sig = Signal(
        name="test_key::speed",
        timestamps=np.array([0.0, 1.0]),
        values=np.array([10.0, 20.0]),
        file_format="MDF4",
        bus_type="",
        source_file="test.mf4",
        metadata={"unit": "km/h"}
    )
    
    # Inject fake signal into session proxy (if we can) or mock session.signals
    app_vm.session.signals = lambda: [sig]
    app_vm.set_active_file("test_key")
    
    assert len(vm.signals) == 1
    assert vm.signals[0].name == "speed"
    assert vm.signals[0].unit == "km/h"

def test_signals_clears_when_active_file_unset(tmp_path: Path) -> None:
    vm, app_vm, key = _setup_vm(tmp_path)
    app_vm.set_active_file(key)
    assert len(vm.signals) == 2
    
    app_vm.set_active_file(None)
    assert vm.signals == []

def test_filter_narrows_flat_list(tmp_path: Path) -> None:
    vm, app_vm, key = _setup_vm(tmp_path)
    app_vm.set_active_file(key)
    
    vm.set_filter("sig_a")
    assert len(vm.signals) == 1
    assert vm.signals[0].name == "sig_a"
