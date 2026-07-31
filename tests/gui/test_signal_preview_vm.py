"""Tests for SignalPreviewVM (FU-13): preview properties + downsampled waveform.

E-3 で信号解決が「アクティブファイルの線形走査」から Session の解決器へ移ったため、
fixture は ``group_signals`` の monkeypatch ではなく **実際に SignalGroup を登録する**
(monkeypatch では解決器に到達せず、全テストが空の VM を見ることになる)。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from pytestqt.qtbot import QtBot

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.models import Signal, SignalGroup
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM

_BASE_DIR = Path(__file__).resolve().parent


def _sig(
    name: str,
    ts: np.ndarray,
    vs: np.ndarray,
    metadata: dict[str, object] | None = None,
) -> Signal:
    return Signal(
        name=name,
        timestamps=ts,
        values=vs,
        file_format="MDF4",
        bus_type="CAN",
        source_file="",
        metadata=(
            {"unit": "km/h", "comment": "veh speed"} if metadata is None else metadata
        ),
    )


def _register(app_vm: AppViewModel, file_name: str, *signals: Signal) -> str:
    """1 ファイル分の SignalGroup を登録して group key を返す (信号名は bare)。"""
    key = app_vm.session._groups.add(
        SignalGroup(
            signals=tuple(signals),
            source_path=_BASE_DIR / file_name,
            file_format="MDF4",
            loaded_at=datetime.now(),
        )
    )
    app_vm.register_loaded(key)  # E-0: display_name scope = loaded_file_keys
    return key


def _vm(qtbot: QtBot) -> tuple[SignalPreviewVM, str]:
    app_vm = AppViewModel()
    ts = np.arange(0.0, 100.0, 1.0)
    key = _register(app_vm, "a.mf4", _sig("Speed", ts, np.sin(ts)))
    app_vm.set_active_file(key)
    return SignalPreviewVM(app_vm), key


def test_properties_include_name_unit_samples_timerange_minmax(qtbot: QtBot) -> None:
    vm, key = _vm(qtbot)
    vm.set_signal(f"{key}::Speed")
    props = dict(vm.properties())
    # E-0 (UX-19): "名前" は bare 表示名 — 生の名前空間つきキーではない
    assert props["名前"] == "Speed"
    assert props["単位"] == "km/h"
    assert props["サンプル数"] == "100"
    assert "時間範囲" in props and "s" in props["時間範囲"]
    assert "最小値" in props and "最大値" in props
    assert props["コメント"] == "veh speed"


def test_properties_empty_for_unknown_or_none(qtbot: QtBot) -> None:
    vm, key = _vm(qtbot)
    assert vm.properties() == []  # no signal set
    vm.set_signal(f"{key}::Missing")
    assert vm.properties() == []


# ─── display_name (E-0, spec §1.2) ────────────────────────────────────────


def test_display_name_bare_when_no_collision(qtbot: QtBot) -> None:
    vm, key = _vm(qtbot)
    assert vm.display_name(f"{key}::Speed") == "Speed"


def test_display_name_qualified_when_two_loaded_files_share_bare_name(
    qtbot: QtBot,
) -> None:
    """Scope = ALL loaded signals, not just the active file's (spec §1.2)."""
    app_vm = AppViewModel()
    ts = np.arange(0.0, 10.0, 1.0)
    k1 = _register(app_vm, "a.mf4", _sig("Speed", ts, np.sin(ts)))
    k2 = _register(app_vm, "b.mf4", _sig("Speed", ts, np.sin(ts)))
    app_vm.set_active_file(k1)
    vm = SignalPreviewVM(app_vm)
    assert vm.display_name(f"{k1}::Speed") == f"Speed ({k1})"
    assert vm.display_name(f"{k2}::Speed") == f"Speed ({k2})"


def test_display_name_unresolvable_key_falls_back_to_bare_name(
    qtbot: QtBot,
) -> None:
    """読み込み済み信号に無いキー (stale/unknown) でも落ちない — 何とも衝突しない。"""
    vm, key = _vm(qtbot)
    assert vm.display_name(f"{key}::TotallyUnknown") == "TotallyUnknown"


def test_plot_data_downsampled_within_range(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    ts = np.arange(0.0, 10000.0, 1.0)  # 10k points
    key = _register(app_vm, "big.mf4", _sig("Big", ts, np.cos(ts)))
    app_vm.set_active_file(key)
    vm = SignalPreviewVM(app_vm)
    vm.set_signal(f"{key}::Big")
    data = vm.plot_data()
    assert data is not None
    x, y = data
    assert 0 < len(x) <= 480  # downsampled to <= _PREVIEW_POINTS
    assert len(x) == len(y)
    assert x[0] >= 0.0 and x[-1] <= 9999.0  # within original range


def test_plot_data_none_for_unknown(qtbot: QtBot) -> None:
    vm, key = _vm(qtbot)
    vm.set_signal(f"{key}::Missing")
    assert vm.plot_data() is None


# ─── axis_label_parts (UX-43, spec §3) ────────────────────────────────────


def test_axis_label_parts_returns_display_name_and_unit(qtbot: QtBot) -> None:
    vm, key = _vm(qtbot)
    vm.set_signal(f"{key}::Speed")
    assert vm.axis_label_parts() == ("Speed", "km/h")


def test_axis_label_parts_unit_none_when_missing(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    ts = np.arange(0.0, 10.0, 1.0)
    key = _register(app_vm, "nounit.mf4", _sig("NoUnit", ts, np.sin(ts), metadata={}))
    app_vm.set_active_file(key)
    vm = SignalPreviewVM(app_vm)
    vm.set_signal(f"{key}::NoUnit")
    assert vm.axis_label_parts() == ("NoUnit", None)


def test_axis_label_parts_empty_when_no_signal_set(qtbot: QtBot) -> None:
    vm, _key = _vm(qtbot)
    assert vm.axis_label_parts() == ("", None)


def test_axis_label_parts_qualified_name_on_collision(qtbot: QtBot) -> None:
    """Scope = ALL loaded signals (same rule as display_name, spec §1.2)."""
    app_vm = AppViewModel()
    ts = np.arange(0.0, 10.0, 1.0)
    k1 = _register(app_vm, "a.mf4", _sig("Speed", ts, np.sin(ts)))
    _register(app_vm, "b.mf4", _sig("Speed", ts, np.sin(ts)))
    app_vm.set_active_file(k1)
    vm = SignalPreviewVM(app_vm)
    vm.set_signal(f"{k1}::Speed")
    name, unit = vm.axis_label_parts()
    assert name == f"Speed ({k1})"
    assert "::" not in name
    assert unit == "km/h"


def test_time_range_does_not_materialize_sorted_view_cache(qtbot: QtBot) -> None:
    """properties() は Signal.time_range() (生 min/max) で時間範囲を読むこと。
    sorted_view()[0][0]/[-1] だと FU-20 の float64 キャッシュを膨らませる
    (memory signal_range_via_sorted_view_materializes_float64_cache)。"""
    app_vm = AppViewModel()
    ts = np.arange(0.0, 50.0, 1.0)
    sig = _sig("S", ts, np.sin(ts))
    key = _register(app_vm, "s.mf4", sig)
    app_vm.set_active_file(key)
    vm = SignalPreviewVM(app_vm)
    vm.set_signal(f"{key}::S")
    # namespaced ラッパーは sorted_view を元 Signal へ委譲するので、元を見れば足りる。
    _ = vm.properties()
    assert getattr(sig, "_sorted_view_cache", None) is None


# ─── E-3: 列キー / 親チャンネル ─────────────────────────────────────────────


def test_column_key_resolves_to_expanded_column(qtbot: QtBot, tmp_path: Path) -> None:
    """反転後 group_signals は物理チャンネルしか返さない。線形走査のままだと列キーが
    解決できず、プレビュー窓が「この信号はプレビューできません」で真っ白になる —
    設計された空状態と見分けがつかないサイレント破壊。"""
    app_vm = AppViewModel()
    key = app_vm.request_load(write_mdf4_2d(tmp_path))
    app_vm.set_active_file(key)
    vm = SignalPreviewVM(app_vm)

    vm.set_signal(f"{key}::Mat[0]")

    props = dict(vm.properties())
    assert props["名前"] == "Mat[0]"
    assert props["サンプル数"] == "4"
    assert vm.plot_data() is not None
    assert vm.axis_label_parts()[0] == "Mat[0]"


def test_column_display_name_qualified_when_two_files_share_column(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """E-0 の母数から他ファイルの列が消えると Mat[0] の修飾が静かに落ちる
    (2 ファイルとも同名の列を持つのに「Mat[0]」と表示され出所が分からなくなる)。"""
    app_vm = AppViewModel()
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    k1 = app_vm.request_load(write_mdf4_2d(d1))
    k2 = app_vm.request_load(write_mdf4_2d(d2))
    app_vm.set_active_file(k1)
    vm = SignalPreviewVM(app_vm)

    assert vm.display_name(f"{k1}::Mat[0]") == f"Mat[0] ({k1})"
    assert vm.display_name(f"{k2}::Mat[0]") == f"Mat[0] ({k2})"


def test_display_name_does_not_mint_any_column(qtbot: QtBot, tmp_path: Path) -> None:
    """表示名の衝突判定は **1 本も鋳造しない** (列構造だけで決まる)。

    「全ファイルの全列を舐めない」だけでは足りない: 鋳造した列は _resolved_by_key へ
    入り、E-4a の LRU では非 pin の枠を食ってプロット中でない列を押し出す
    (spec §5.5) ので、他ファイル 1 本ずつでも「プレビューを開くたびに枠が削られる」
    経路が残る。上限 (<= 1) ではなく **0** を要求する。
    """
    app_vm = AppViewModel()
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    k1 = app_vm.request_load(write_mdf4_2d(d1))
    k2 = app_vm.request_load(write_mdf4_2d(d2))
    vm = SignalPreviewVM(app_vm)
    before = app_vm.session._groups.mint_count

    # 反 vacuous 前置: この呼び出しは実際に衝突を検出している (母数が縮んで
    # いるだけなら "Mat[0]" が返り、鋳造 0 は自明に通る)。
    assert vm.display_name(f"{k1}::Mat[0]") == f"Mat[0] ({k1})"

    assert app_vm.session._groups.mint_count == before
    assert app_vm.session._groups.resolved_keys(k2) == frozenset()


def test_container_channel_is_not_previewable(qtbot: QtBot, tmp_path: Path) -> None:
    """配列チャンネルの親 (`Mat`) は 1 本の波形を持たない。プレビューしようとすると
    値を全読み (prod で 96 MB/本) したうえで Downsampler が 2-D 配列に出くわす —
    名前 (列構造) だけで弾く。"""
    app_vm = AppViewModel()
    key = app_vm.request_load(write_mdf4_2d(tmp_path))
    app_vm.set_active_file(key)
    vm = SignalPreviewVM(app_vm)

    vm.set_signal(f"{key}::Mat")

    assert vm.properties() == []
    assert vm.plot_data() is None
    parent = app_vm.session.resolve_signal(f"{key}::Mat")
    assert parent is not None
    assert parent._values_source.is_materialized is False
