"""Property-based tests for the Interpolator.

Property 17: Interpolation correctness for all three methods.
Property 18: Exact-timestamp queries return the stored sample unchanged.
Property 19: Out-of-range queries return None (no extrapolation).
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from valisync.core.interpolation import InterpolationMethod, Interpolator
from valisync.core.models import Signal

from .conftest import valid_signals

pytestmark = pytest.mark.property

LINEAR = InterpolationMethod.LINEAR
ZOH = InterpolationMethod.ZERO_ORDER_HOLD
NEAREST = InterpolationMethod.NEAREST


@given(valid_signals(allow_nan_values=False), st.floats(min_value=0.0, max_value=1.0))
def test_interpolation_correctness(signal: Signal, frac: float) -> None:
    ts, vs = signal.timestamps, signal.values
    t = float(np.clip(ts[0] + frac * (ts[-1] - ts[0]), ts[0], ts[-1]))
    interp = Interpolator()

    # linear matches numpy's linear interpolation
    lin = interp.interpolate(signal, t, LINEAR)
    assert lin == pytest.approx(float(np.interp(t, ts, vs)), rel=1e-9, abs=1e-9)

    # zero-order hold = value at the greatest timestamp ≤ t
    zoh = interp.interpolate(signal, t, ZOH)
    ref_idx = int(np.searchsorted(ts, t, side="right")) - 1
    assert zoh == pytest.approx(float(vs[ref_idx]))

    # nearest = value at the closest timestamp (ties → lower index)
    near = interp.interpolate(signal, t, NEAREST)
    nearest_idx = int(np.argmin(np.abs(ts - t)))
    assert near == pytest.approx(float(vs[nearest_idx]))


@given(valid_signals(allow_nan_values=False))
def test_exact_timestamp_returns_sample(signal: Signal) -> None:
    interp = Interpolator()
    for i in range(len(signal.timestamps)):
        t = float(signal.timestamps[i])
        for method in InterpolationMethod:
            assert interp.interpolate(signal, t, method) == signal.values[i]


@given(
    valid_signals(allow_nan_values=False),
    st.floats(min_value=1e-2, max_value=1e3),
)
def test_out_of_range_returns_none(signal: Signal, delta: float) -> None:
    ts = signal.timestamps
    interp = Interpolator()
    for method in InterpolationMethod:
        assert interp.interpolate(signal, float(ts[0] - delta), method) is None
        assert interp.interpolate(signal, float(ts[-1] + delta), method) is None
