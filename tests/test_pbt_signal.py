"""Property-based tests for the Signal data model.

Property 1: Signal data-model invariants (length match, finite & strictly
            increasing timestamps).
Property 2: Signal immutability (arrays read-only, instance frozen).
Property 3: Transform input immutability (no transform mutates its input Signal;
            covers offset, interpolation, downsampling, statistics, formula and
            the Calcbar operations).
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from valisync.core.downsampler import Downsampler
from valisync.core.formula import FormulaEngine
from valisync.core.interpolation import InterpolationMethod, Interpolator
from valisync.core.models import Signal
from valisync.core.session import Session
from valisync.core.statistics import RangeStatistics
from valisync.core.sync import TimeSynchronizer

from .conftest import finite_floats, monotonic_timestamps, valid_signals

pytestmark = pytest.mark.property


def _arrays_equal(a: np.ndarray, b: np.ndarray) -> bool:
    return a.shape == b.shape and bool(np.array_equal(a, b, equal_nan=True))


# ─── Property 1: data-model invariants ───────────────────────────────────────


@given(valid_signals())
def test_valid_signal_construction_succeeds(signal: Signal) -> None:
    assert len(signal.timestamps) == len(signal.values)
    assert np.all(np.isfinite(signal.timestamps))
    assert np.all(np.diff(signal.timestamps) > 0)


@given(monotonic_timestamps(), st.integers(min_value=1, max_value=10))
def test_length_mismatch_rejected(ts: np.ndarray, extra: int) -> None:
    values = np.zeros(len(ts) + extra, dtype=np.float64)
    with pytest.raises(ValueError):
        Signal("s", ts, values, "Derived", "", "", {})


@given(monotonic_timestamps(), st.sampled_from([np.inf, -np.inf, np.nan]))
def test_non_finite_timestamp_rejected(ts: np.ndarray, bad: float) -> None:
    ts = ts.copy()
    ts[len(ts) // 2] = bad
    values = np.zeros(len(ts), dtype=np.float64)
    with pytest.raises(ValueError):
        Signal("s", ts, values, "Derived", "", "", {})


@given(monotonic_timestamps(min_size=3))
def test_non_monotonic_timestamp_rejected(ts: np.ndarray) -> None:
    ts = ts.copy()
    # force a non-increasing step by duplicating a neighbour
    ts[1] = ts[0]
    values = np.zeros(len(ts), dtype=np.float64)
    with pytest.raises(ValueError):
        Signal("s", ts, values, "Derived", "", "", {})


# ─── Property 2: immutability ─────────────────────────────────────────────────


@given(valid_signals())
def test_arrays_are_read_only(signal: Signal) -> None:
    assert signal.timestamps.flags.writeable is False
    assert signal.values.flags.writeable is False
    with pytest.raises(ValueError):
        signal.timestamps[0] = 999.0
    with pytest.raises(ValueError):
        signal.values[0] = 999.0


@given(valid_signals())
def test_instance_is_frozen(signal: Signal) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        signal.name = "mutated"  # type: ignore[misc]


# ─── Property 3: transform input immutability ─────────────────────────────────


@given(valid_signals(), finite_floats, finite_floats)
def test_apply_offset_preserves_input(
    signal: Signal, file_off: float, sig_off: float
) -> None:
    ts_before, vs_before = signal.timestamps.copy(), signal.values.copy()
    TimeSynchronizer().apply_offset(signal, file_off, sig_off)
    assert _arrays_equal(signal.timestamps, ts_before)
    assert _arrays_equal(signal.values, vs_before)


@given(
    valid_signals(),
    st.floats(min_value=0.0, max_value=1.0),
    st.sampled_from(list(InterpolationMethod)),
)
def test_interpolate_preserves_input(
    signal: Signal, frac: float, method: InterpolationMethod
) -> None:
    ts_before, vs_before = signal.timestamps.copy(), signal.values.copy()
    t = float(
        signal.timestamps[0] + frac * (signal.timestamps[-1] - signal.timestamps[0])
    )
    Interpolator().interpolate(signal, t, method)
    assert _arrays_equal(signal.timestamps, ts_before)
    assert _arrays_equal(signal.values, vs_before)


@given(valid_signals(), st.integers(min_value=2, max_value=100))
def test_downsample_preserves_input(signal: Signal, n: int) -> None:
    ts_before, vs_before = signal.timestamps.copy(), signal.values.copy()
    Downsampler().downsample(signal, n)
    assert _arrays_equal(signal.timestamps, ts_before)
    assert _arrays_equal(signal.values, vs_before)


@given(valid_signals(allow_nan_values=False))
def test_range_statistics_preserves_input(signal: Signal) -> None:
    ts_before, vs_before = signal.timestamps.copy(), signal.values.copy()
    RangeStatistics().compute(
        signal, float(signal.timestamps[0]), float(signal.timestamps[-1])
    )
    assert _arrays_equal(signal.timestamps, ts_before)
    assert _arrays_equal(signal.values, vs_before)


@given(valid_signals(allow_nan_values=False))
def test_formula_eval_preserves_input(signal: Signal) -> None:
    ts_before, vs_before = signal.timestamps.copy(), signal.values.copy()
    FormulaEngine().evaluate("x * 2 + 1", {"x": signal})
    assert _arrays_equal(signal.timestamps, ts_before)
    assert _arrays_equal(signal.values, vs_before)


@given(valid_signals(min_size=2, max_size=40), st.data())
def test_calcbar_ops_preserve_input(signal: Signal, data: st.DataObject) -> None:
    ts_before, vs_before = signal.timestamps.copy(), signal.values.copy()
    session = Session()
    window = data.draw(st.integers(min_value=1, max_value=len(signal.values)))
    session.moving_average(signal, window)
    session.linear_regression(signal)
    session.differentiate(signal)
    session.integrate(signal)
    assert _arrays_equal(signal.timestamps, ts_before)
    assert _arrays_equal(signal.values, vs_before)
