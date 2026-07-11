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


def _cb_vm_with_signal(
    tmp_path: Path,
    key_orig: str,
    metadata: dict[str, object] | None = None,
    bus_type: str = "",
    n_samples: int = 10,
) -> ChannelBrowserVM:
    """Build a ChannelBrowserVM with one fake Signal active under "test_key".

    Follows the existing group_signals-injection pattern used elsewhere in
    this module (see test_signal_item_contains_unit): tooltip_for only needs
    Signal fields, so a real loaded file is unnecessary.
    """
    import numpy as np

    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    sig = Signal(
        name=f"test_key::{key_orig}",
        timestamps=np.arange(float(n_samples)),
        values=np.zeros(n_samples),
        file_format="MDF4",
        bus_type=bus_type,
        source_file="test.mf4",
        metadata=dict(metadata) if metadata else {},
    )

    app_vm.session.group_signals = lambda key: [sig]  # type: ignore[method-assign]
    app_vm.set_active_file("test_key")
    return vm


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


def test_tooltip_for_lists_value_labels(tmp_path: Path) -> None:
    """value_labels 持ち信号の tooltip_for に『ラベル: 0=OFF, 1=LEFT, 2=RIGHT』(LD-07)."""
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    import numpy as np

    sig = Signal(
        name="test_key::TurnSig",
        timestamps=np.array([0.0, 1.0]),
        values=np.array([0.0, 1.0]),
        file_format="MDF4",
        bus_type="",
        source_file="test.mf4",
        metadata={"value_labels": {0.0: "OFF", 1.0: "LEFT", 2.0: "RIGHT"}},
    )

    app_vm.session.group_signals = lambda key: [sig]
    app_vm.set_active_file("test_key")

    item = next(i for i in vm.signals if i.name == "TurnSig")
    assert "ラベル: 0=OFF, 1=LEFT, 2=RIGHT" in vm.tooltip_for(item.key)


def test_tooltip_for_truncates_after_8(tmp_path: Path) -> None:
    """9 件以上は先頭 8 件 + 『… (全 n 件)』(LD-07)."""
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    import numpy as np

    value_labels = {float(i): f"S{i}" for i in range(10)}
    sig = Signal(
        name="test_key::Many",
        timestamps=np.array([0.0, 1.0]),
        values=np.array([0.0, 1.0]),
        file_format="MDF4",
        bus_type="",
        source_file="test.mf4",
        metadata={"value_labels": value_labels},
    )

    app_vm.session.group_signals = lambda key: [sig]
    app_vm.set_active_file("test_key")

    item = next(i for i in vm.signals if i.name == "Many")
    tip = vm.tooltip_for(item.key)
    assert tip.endswith("… (全 10 件)")
    assert "8=S8" not in tip.split("…")[0]


def test_tooltip_for_omits_labels_without_value_labels(tmp_path: Path) -> None:
    """value_labels が無い信号の tooltip_for に『ラベル:』行は無い。"""
    vm, app_vm, key = _setup_vm(tmp_path)
    app_vm.set_active_file(key)

    assert all("ラベル:" not in vm.tooltip_for(item.key) for item in vm.signals)


def test_tooltip_for_full_metadata(tmp_path: Path) -> None:
    # MDF 相当: unit + comment + channel_group_name + source_name + value_labels
    vm = _cb_vm_with_signal(
        tmp_path,
        key_orig="gear",
        metadata={
            "unit": "-",
            "comment": "現在のギア段",
            "channel_group_name": "PT_CAN",
            "source_name": "ECU1",
            "value_labels": {0: "N", 1: "D"},
        },
        bus_type="CAN",
        n_samples=1234,
    )
    key = vm.signals[0].key
    tip = vm.tooltip_for(key)
    assert "単位: -" in tip
    assert "サンプル数: 1234" in tip
    assert "CAN" in tip and "PT_CAN" in tip and "ECU1" in tip  # 由来
    assert "現在のギア段" in tip  # コメント
    assert "N" in tip and "D" in tip  # value_labels (LD-07)


def test_tooltip_for_csv_omits_absent_rows(tmp_path: Path) -> None:
    # CSV 相当: unit のみ、bus_type 空、comment/group/source/labels なし
    vm = _cb_vm_with_signal(
        tmp_path,
        key_orig="speed",
        metadata={"unit": "km/h"},
        bus_type="",
        n_samples=50,
    )
    key = vm.signals[0].key
    tip = vm.tooltip_for(key)
    assert "単位: km/h" in tip
    assert "サンプル数: 50" in tip
    assert "由来:" not in tip  # bus_type/group/source 全欠損 -> 由来行なし
    assert "コメント:" not in tip  # comment なし
    assert "ラベル:" not in tip  # value_labels なし


def test_tooltip_for_unknown_key_empty(tmp_path: Path) -> None:
    vm = _cb_vm_with_signal(tmp_path, key_orig="speed", metadata={"unit": "km/h"})
    assert vm.tooltip_for("nonexistent::key") == ""


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
    # mdf_loader は全チャンネル skip 時に 0ch グループを登録し得る
    # (production 到達可能・catalog LD-05)。ここでは決定的な単体テストのため
    # session 面で直接再現する(spec §4.2)。
    monkeypatch.setattr(app_vm.session, "group_signals", lambda _key: [])
    assert vm.empty_state() == "no_channels"
    assert vm.header_text() == "d.csv — 0 ch"


# ─── FU-11 Performance: Precompute + Memo Tests ──────────────────────────────


def test_one_keystroke_fetches_group_at_most_once(tmp_path: Path) -> None:
    """FU-11: 1 打鍵(model reset + header_text + empty_state)で group_signals は
    高々 1 回(prep 構築時のみ)。同一 active_file の 2 打鍵目は 0 回。per-access
    再取得への回帰を防ぐ構造アサート(既存 no-full-scan spy パターンの延長)。"""
    vm, app_vm, key = _setup_vm(tmp_path)
    session = app_vm.session
    real_group_signals = session.group_signals
    calls: list[str] = []

    def spy(k: str) -> list[Signal]:
        calls.append(k)
        return real_group_signals(k)

    session.group_signals = spy  # type: ignore[method-assign]
    app_vm.set_active_file(key)  # 遅延ビルド: ここでは fetch しない

    calls.clear()
    # 1 打鍵目: View/Model 相当の 3 消費
    vm.set_filter("s")
    _ = list(vm.signals)  # SignalTableModel._on_vm_change
    vm.header_text()  # _refresh_state 1
    vm.empty_state()  # _refresh_state 2
    assert len(calls) == 1  # prep を 1 度だけ構築し全消費で共有

    calls.clear()
    # 2 打鍵目: 同一 active_file → prep/memo で完全充足
    vm.set_filter("si")
    _ = list(vm.signals)
    vm.header_text()
    vm.empty_state()
    assert calls == []


def test_active_file_switch_invalidates_prep_no_leak(tmp_path: Path) -> None:
    """FU-11: active file 切替で precompute を作り直す。前ファイルの信号が stale
    キャッシュ経由で漏れないことを保証。"""
    app_vm = AppViewModel()
    fa = tmp_path / "a.csv"
    fa.write_text("t,alpha,gamma\n0,1,2\n1,3,4\n", encoding="utf-8")
    fb = tmp_path / "b.csv"
    fb.write_text("t,beta,delta\n0,1,2\n1,3,4\n", encoding="utf-8")
    ka = app_vm.request_load(fa, _csv_format())
    kb = app_vm.request_load(fb, _csv_format())
    vm = ChannelBrowserVM(app_vm)

    app_vm.set_active_file(ka)
    assert {s.name for s in vm.signals} == {"alpha", "gamma"}

    app_vm.set_active_file(kb)
    assert {s.name for s in vm.signals} == {"beta", "delta"}  # alpha/gamma を漏らさない
