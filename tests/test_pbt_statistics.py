"""Property-based test for RangeStatistics.

Property 20: Range-statistics correctness — aggregates equal the corresponding
             numpy reductions over exactly the in-range samples, and count
             equals that sample count.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from valisync.core.models import Signal
from valisync.core.statistics import RangeStatistics

from .conftest import valid_signals

pytestmark = pytest.mark.property


@given(
    valid_signals(allow_nan_values=False),
    st.floats(min_value=0.0, max_value=1.0),
    st.floats(min_value=0.0, max_value=1.0),
)
def test_range_statistics_match_numpy(signal: Signal, f1: float, f2: float) -> None:
    ts, vs = signal.timestamps, signal.values
    span = float(ts[-1] - ts[0])
    pad = span * 0.1 + 1.0
    lo, hi = float(ts[0]) - pad, float(ts[-1]) + pad
    a = lo + f1 * (hi - lo)
    b = lo + f2 * (hi - lo)
    t_start, t_end = (a, b) if a <= b else (b, a)

    res = RangeStatistics().compute(signal, t_start, t_end)

    in_range = vs[(ts >= t_start) & (ts <= t_end)]
    assert res.count == len(in_range)
    if len(in_range) == 0:
        assert math.isnan(res.mean)
        assert math.isnan(res.max)
        assert math.isnan(res.min)
        assert math.isnan(res.std)
    else:
        assert res.mean == pytest.approx(float(np.mean(in_range)), rel=1e-9, abs=1e-9)
        assert res.max == float(np.max(in_range))
        assert res.min == float(np.min(in_range))
        assert res.std == pytest.approx(
            float(np.std(in_range, ddof=0)), rel=1e-9, abs=1e-9
        )
