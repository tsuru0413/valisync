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
        metadata={"unit": "km/h"},
    )

    # Inject a fake signal via the per-file public API the VM now uses.
    app_vm.session.group_signals = lambda key: [sig]
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


def test_active_file_switch_fetches_only_active_group_no_full_scan(
    tmp_path: Path,
) -> None:
    """R5.2: switching the Active File reads only that file's signals via
    group_signals(active) and never scans the whole Session (session.signals).

    Guards the per-file mechanism (introduced in S1) that keeps the update cheap
    — O(active-file signals), not O(total signals) — against a regression that
    reintroduces a full scan. A robust, hardware-independent stand-in for the
    old unverifiable wall-clock "within 100ms".
    """
    vm, app_vm, key = _setup_vm(tmp_path)
    session = app_vm.session
    real_group_signals = session.group_signals

    full_scan_calls = 0
    group_calls: list[str] = []

    def spy_signals() -> list[Signal]:
        nonlocal full_scan_calls
        full_scan_calls += 1
        return []

    def spy_group_signals(k: str) -> list[Signal]:
        group_calls.append(k)
        return real_group_signals(k)

    session.signals = spy_signals  # type: ignore[method-assign]
    session.group_signals = spy_group_signals  # type: ignore[method-assign]

    app_vm.set_active_file(key)
    items = vm.signals  # the master-detail update the view consumes

    assert {s.name for s in items} == {"sig_a", "sig_b"}
    assert group_calls == [key]  # only the active group was fetched
    assert full_scan_calls == 0  # the full Session was never scanned


# ─── Header / Empty State Tests (FB-05/09) ──────────────────────────────────


def _loaded_vm(tmp_path: Path) -> tuple[AppViewModel, ChannelBrowserVM, str]:
    fmt = FormatDefinition(
        name="fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )
    path = tmp_path / "d.csv"
    path.write_text("t,speed,brake\n0.0,1.0,0.0\n1.0,2.0,1.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(path, fmt)
    return app_vm, ChannelBrowserVM(app_vm), key


def test_header_none_selected(tmp_path: Path) -> None:
    app_vm, vm, _key = _loaded_vm(tmp_path)
    app_vm.set_active_file(None)
    assert vm.header_text() == "ファイル未選択"
    assert vm.empty_state() == "none_selected"


def test_header_counts_and_has_rows(tmp_path: Path) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    assert vm.header_text() == "d.csv — 2 ch 中 2 件表示"
    assert vm.empty_state() == "has_rows"


def test_no_match_state_and_query(tmp_path: Path) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    vm.set_filter("xyz123")
    assert vm.empty_state() == "no_match"
    assert vm.filter_query() == "xyz123"
    assert vm.header_text() == "d.csv — 2 ch 中 0 件表示"


def test_no_channels_state(tmp_path: Path, monkeypatch) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    # mdf4_loader は全チャンネル skip 時に 0ch グループを登録し得る
    # (production 到達可能・catalog LD-05)。ここでは決定的な単体テストのため
    # session 面で直接再現する(spec §4.2)。
    monkeypatch.setattr(app_vm.session, "group_signals", lambda _key: [])
    assert vm.empty_state() == "no_channels"
    assert vm.header_text() == "d.csv — 0 ch"
