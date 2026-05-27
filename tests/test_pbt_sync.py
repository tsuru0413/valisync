"""Property-based tests for offset application and signal-name uniqueness.

Property 9:  Name uniqueness — key-prefixed names are globally unique, even
             when the same file is loaded more than once.
Property 10: Offset addition correctness.
Property 11: Inter-sample spacing preserved under offset.
Property 12: Sample count invariant under offset.
Property 13: Strict monotonicity preserved under offset.
Property 14: Session.unified_timeline_signals preserves the order, sample count
             and per-signal sample correspondence (no reordering/resampling).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR, SignalGroupManager
from valisync.core.models import Signal, SignalGroup
from valisync.core.session import Session
from valisync.core.sync import TimeSynchronizer

from .conftest import finite_offsets, valid_signals

pytestmark = pytest.mark.property

_NAME = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=6,
)


def _make_group(names: list[str], fmt: str) -> SignalGroup:
    sigs = tuple(
        Signal(
            n,
            np.array([0.0, 1.0], dtype=np.float64),
            np.array([0.0, 1.0], dtype=np.float64),
            fmt,
            "",
            "",
            {},
        )
        for n in names
    )
    return SignalGroup(
        signals=sigs,
        source_path=Path.cwd() / "f.mf4",
        file_format=fmt,
        loaded_at=datetime.now(),
    )


# ─── Property 9: name uniqueness ──────────────────────────────────────────────


@given(
    groups=st.lists(
        st.tuples(
            st.lists(_NAME, unique=True, min_size=1, max_size=5),
            st.sampled_from(["MDF4", "CSV"]),
        ),
        min_size=1,
        max_size=5,
    )
)
def test_keyed_names_are_globally_unique(groups: list[tuple[list[str], str]]) -> None:
    mgr = SignalGroupManager()
    for names, fmt in groups:
        mgr.add(_make_group(names, fmt))
    all_names = [s.name for s in mgr.signals()]
    assert len(all_names) == len(set(all_names))
    assert all(KEY_SEPARATOR in n for n in all_names)


def test_duplicate_path_load_keeps_names_unique() -> None:
    mgr = SignalGroupManager()
    group = _make_group(["speed", "rpm"], "MDF4")
    k1 = mgr.add(group)
    k2 = mgr.add(group)  # same group object loaded twice (Req 4.7)
    assert k1 != k2
    names = [s.name for s in mgr.signals()]
    assert len(names) == len(set(names)) == 4


# ─── Properties 10-13: apply_offset ───────────────────────────────────────────


@given(valid_signals(), finite_offsets, finite_offsets)
def test_offset_addition_correct(
    signal: Signal, file_off: float, sig_off: float
) -> None:
    shifted = TimeSynchronizer().apply_offset(signal, file_off, sig_off)
    expected = signal.timestamps + (file_off + sig_off)
    np.testing.assert_array_equal(shifted.timestamps, expected)
    # values are carried through untouched
    np.testing.assert_array_equal(shifted.values, signal.values)


@given(valid_signals(), finite_offsets, finite_offsets)
def test_offset_preserves_spacing(
    signal: Signal, file_off: float, sig_off: float
) -> None:
    shifted = TimeSynchronizer().apply_offset(signal, file_off, sig_off)
    np.testing.assert_allclose(
        np.diff(shifted.timestamps), np.diff(signal.timestamps), rtol=1e-6, atol=1e-9
    )


@given(valid_signals(), finite_offsets, finite_offsets)
def test_offset_preserves_count_and_monotonicity(
    signal: Signal, file_off: float, sig_off: float
) -> None:
    shifted = TimeSynchronizer().apply_offset(signal, file_off, sig_off)
    assert len(shifted.timestamps) == len(signal.timestamps)
    assert np.all(np.diff(shifted.timestamps) > 0)


# ─── Property 14: Session relative-order preservation (Req 8.3) ────────────────


@given(
    specs=st.lists(
        st.tuples(
            st.lists(valid_signals(min_size=2, max_size=4), min_size=1, max_size=3),
            st.sampled_from(["MDF4", "CSV"]),
        ),
        min_size=1,
        max_size=4,
    ),
    data=st.data(),
)
def test_unified_timeline_preserves_order_count_and_offsets(
    specs: list[tuple[list[Signal], str]], data: st.DataObject
) -> None:
    session = Session()
    for sigs, fmt in specs:
        group = SignalGroup(
            signals=tuple(sigs),
            source_path=Path.cwd() / "f",
            file_format=fmt,
            loaded_at=datetime.now(),
        )
        session._groups.add(group)  # set up loaded state without file I/O

    keyed = session.signals()
    keys = {n.name.split(KEY_SEPARATOR, 1)[0] for n in keyed}
    file_offsets = {k: data.draw(finite_offsets) for k in keys}
    signal_offsets = {s.name: data.draw(finite_offsets) for s in keyed}

    placed = session.unified_timeline_signals(file_offsets, signal_offsets)

    # order preserved — no reordering across signals (8.3)
    assert [s.name for s in placed] == [s.name for s in keyed]
    for orig, out in zip(keyed, placed, strict=True):
        key = orig.name.split(KEY_SEPARATOR, 1)[0]
        total = file_offsets[key] + signal_offsets[orig.name]
        expected = orig.timestamps + total
        assert len(out.timestamps) == len(orig.timestamps)  # count unchanged
        np.testing.assert_array_equal(out.timestamps, expected)
        assert np.all(np.diff(out.timestamps) > 0)  # monotonicity preserved
