"""Property-based tests for the Signal data model.

Property 1: Signal data-model invariants (length match, finite timestamps;
            non-monotonic/duplicate timestamps are accepted as recorded, and
            sorted_view() provides the strictly-increasing view).
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
def test_non_monotonic_timestamp_accepted_and_sorted_view_monotonic(
    ts: np.ndarray,
) -> None:
    # 意味反転(本タスクで検証緩和): 旧実装は ValueError だったが、非単調は受け入れ、
    # sorted_view() が厳密単調ビューを提供することを検証する
    ts = ts.copy()
    # force a non-increasing step by duplicating a neighbour
    ts[1] = ts[0]
    values = np.zeros(len(ts), dtype=np.float64)
    signal = Signal("s", ts, values, "Derived", "", "", {})
    assert len(signal.timestamps) == len(ts)
    sorted_ts, _ = signal.sorted_view()
    assert np.all(np.diff(sorted_ts) > 0)


@given(
    ts=st.lists(
        st.floats(min_value=-1e6, max_value=1e6, allow_nan=False),
        min_size=0,
        max_size=60,
    )
)
def test_pbt_sorted_view_monotonic_and_keep_last(ts: list[float]) -> None:
    # values に元 index を入れ、keep-last(同値 ts の最後の記録が残る)を検証
    vs = [float(i) for i in range(len(ts))]
    sig = Signal(
        name="p",
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )
    s_ts, s_vs = sig.sorted_view()
    assert np.all(np.diff(s_ts) > 0)  # 厳密単調
    assert len(s_ts) == len(set(ts))  # 重複は1点に縮退
    for t, v in zip(s_ts.tolist(), s_vs.tolist(), strict=True):
        # v は元配列で t が最後に現れた index
        assert int(v) == max(i for i, x in enumerate(ts) if x == t)
    assert sig.timestamps.tolist() == ts  # 生データ無改変


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
