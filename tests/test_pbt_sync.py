"""Property-based tests for offset application and signal-name uniqueness.

Property 9:  Name uniqueness — key-prefixed names are globally unique, even
             when the same file is loaded more than once.
Property 10: Offset addition correctness.
Property 11: Inter-sample spacing preserved under offset.
Property 12: Sample count invariant under offset.
Property 13: Strict monotonicity preserved under offset.
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
            name=n,
            timestamps=np.array([0.0, 1.0], dtype=np.float64),
            values=np.array([0.0, 1.0], dtype=np.float64),
            file_format=fmt,
            bus_type="",
            source_file="",
            metadata={},
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
