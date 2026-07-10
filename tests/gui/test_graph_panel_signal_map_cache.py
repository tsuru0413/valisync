from pathlib import Path

import numpy as np
import pytest

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

_FMT = FormatDefinition(
    name="fmt",
    delimiter=Delimiter.COMMA,
    timestamp_column=0,
    timestamp_unit="sec",
    signal_start_column=1,
    signal_end_column=2,
    has_header=True,
)


def _vm_two(tmp_path: Path) -> tuple[GraphPanelVM, list[str], Session]:
    csv = tmp_path / "d.csv"
    rows = ["t,s1,s2"] + [f"{i * 0.1:.1f},{i}.0,{(i + 10)}.0" for i in range(5)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    session = Session()
    session.load(csv, _FMT)
    keys = sorted(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(keys[0], 0)
    vm.add_signal_to_axis(keys[1], 0)
    return vm, keys, session


def test_no_offset_returns_base_wrappers(tmp_path: Path) -> None:
    vm, keys, session = _vm_two(tmp_path)
    sm = vm._signal_map()
    assert sm[keys[0]] is session.signal_map()[keys[0]]  # ゼロコピー(同一ラッパー)


def test_signal_offset_applies_to_target_only(tmp_path: Path) -> None:
    vm, keys, session = _vm_two(tmp_path)
    base0 = session.signal_map()[keys[0]]
    vm.set_offsets({keys[0]: 0.5}, {})
    sm = vm._signal_map()
    np.testing.assert_allclose(sm[keys[0]].timestamps, base0.timestamps + 0.5)
    assert sm[keys[1]] is session.signal_map()[keys[1]]  # 非対象は base のまま


def test_file_offset_applies_group_wide(tmp_path: Path) -> None:
    vm, keys, session = _vm_two(tmp_path)
    group_key = keys[0].split("::", 1)[0]
    base0 = session.signal_map()[keys[0]]
    base1 = session.signal_map()[keys[1]]
    vm.set_offsets({}, {group_key: 0.3})
    sm = vm._signal_map()
    np.testing.assert_allclose(sm[keys[0]].timestamps, base0.timestamps + 0.3)
    np.testing.assert_allclose(sm[keys[1]].timestamps, base1.timestamps + 0.3)


def test_reset_y_covers_signal_range(tmp_path: Path) -> None:
    vm, _keys, _ = _vm_two(tmp_path)
    vm.reset_y()
    lo, hi = vm._axes[0].y_range
    assert lo is not None and hi is not None
    # 2信号 s1(0..4) と s2(10..14) の和集合を内包
    assert lo <= 0.0 and hi >= 14.0


def test_map_built_once_across_add_and_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from valisync.core.loaders.signal_group_manager import SignalGroupManager

    vm, _keys, _ = _vm_two(tmp_path)
    calls: list[str] = []
    orig = SignalGroupManager._namespaced

    def spy(key: str, group: object) -> list:  # type: ignore[type-arg]
        calls.append(key)
        return orig(key, group)  # type: ignore[arg-type]

    monkeypatch.setattr(SignalGroupManager, "_namespaced", staticmethod(spy))
    for _ in range(5):
        vm.reset_y()
        vm.reset_axis_y(0)
    assert calls == []  # add_signal 時点で構築済み→autofit 群では再構築ゼロ
