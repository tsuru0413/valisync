"""Unit tests for RangeStatistics (Task 10.4).

Covers correct aggregates over a closed range, the empty-range result
(Req 13.4: all-NaN, count 0) and the validation errors (Req 13.5: t_start >
t_end; Req 13.6: NaN/Inf bounds).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from valisync.core.models import Signal
from valisync.core.statistics import RangeStatistics


def _sig(ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        "s",
        np.array(ts, dtype=np.float64),
        np.array(vs, dtype=np.float64),
        "Derived",
        "",
        "",
        {},
    )


def test_full_range_aggregates() -> None:
    sig = _sig([0.0, 1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0, 5.0])
    res = RangeStatistics().compute(sig, 0.0, 4.0)
    assert res.mean == pytest.approx(3.0)
    assert res.max == 5.0
    assert res.min == 1.0
    assert res.std == pytest.approx(math.sqrt(2.0))  # population std (ddof=0)
    assert res.count == 5


def test_partial_closed_range_inclusive() -> None:
    sig = _sig([0.0, 1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0, 5.0])
    res = RangeStatistics().compute(sig, 1.0, 3.0)
    # inclusive both ends → values [2, 3, 4]
    assert res.count == 3
    assert res.mean == pytest.approx(3.0)
    assert res.min == 2.0
    assert res.max == 4.0


def test_empty_range_yields_nan_and_zero_count() -> None:
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    res = RangeStatistics().compute(sig, 10.0, 20.0)
    assert res.count == 0
    assert math.isnan(res.mean)
    assert math.isnan(res.max)
    assert math.isnan(res.min)
    assert math.isnan(res.std)


def test_start_after_end_raises() -> None:
    sig = _sig([0.0, 1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        RangeStatistics().compute(sig, 5.0, 1.0)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_start_raises(bad: float) -> None:
    sig = _sig([0.0, 1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        RangeStatistics().compute(sig, bad, 1.0)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_end_raises(bad: float) -> None:
    sig = _sig([0.0, 1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        RangeStatistics().compute(sig, 0.0, bad)


def test_single_point_range() -> None:
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    res = RangeStatistics().compute(sig, 1.0, 1.0)
    assert res.count == 1
    assert res.mean == 2.0
    assert res.std == 0.0
