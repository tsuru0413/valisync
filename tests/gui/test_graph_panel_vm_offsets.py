"""Layer A: GraphPanelVM のオフセット適用 (R14)。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


def _vm_two_signals() -> tuple[GraphPanelVM, list[str], str]:
    """2 信号 (同一グループ csv_1) を持つ VM・信号キー列・グループキーを返す。"""
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1,s2"] + [f"{i * 0.01:.3f},{i}.0,{i * 2}.0" for i in range(30)]
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
    vm.add_signal_to_axis(keys[1], 0)
    group_key = keys[0].split("::", 1)[0]
    return vm, keys, group_key


def _curve_x(vm: GraphPanelVM, key: str) -> np.ndarray:
    return next(c.timestamps for c in vm.render_data() if c.name == key)


def test_signal_offset_shifts_only_that_signal() -> None:
    vm, keys, _ = _vm_two_signals()
    base0 = _curve_x(vm, keys[0]).copy()
    base1 = _curve_x(vm, keys[1]).copy()
    vm.set_offsets({keys[0]: 0.5}, {})
    np.testing.assert_allclose(_curve_x(vm, keys[0]), base0 + 0.5)
    np.testing.assert_allclose(_curve_x(vm, keys[1]), base1)  # unchanged


def test_group_offset_shifts_all_signals_in_group() -> None:
    vm, keys, group_key = _vm_two_signals()
    base0 = _curve_x(vm, keys[0]).copy()
    base1 = _curve_x(vm, keys[1]).copy()
    vm.set_offsets({}, {group_key: 0.3})
    np.testing.assert_allclose(_curve_x(vm, keys[0]), base0 + 0.3)
    np.testing.assert_allclose(_curve_x(vm, keys[1]), base1 + 0.3)


def test_zero_offset_is_identity() -> None:
    vm, keys, _ = _vm_two_signals()
    base0 = _curve_x(vm, keys[0]).copy()
    vm.set_offsets({}, {})
    np.testing.assert_allclose(_curve_x(vm, keys[0]), base0)


def test_set_offsets_invalidates_cache() -> None:
    vm, keys, _ = _vm_two_signals()
    # Warm the cache (forces fast-path on the next identical-key render).
    base0 = _curve_x(vm, keys[0]).copy()
    vm.set_offsets({keys[0]: 1.0}, {})
    shifted = _curve_x(vm, keys[0])
    # If set_offsets did not invalidate, the stale cached (un-shifted) curve
    # would be returned and this would fail.
    np.testing.assert_allclose(shifted, base0 + 1.0)
