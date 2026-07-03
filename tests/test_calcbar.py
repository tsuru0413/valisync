"""Unit tests for Calcbar operations on Session (Task 8.3, Requirements 26/15)."""

from __future__ import annotations

import numpy as np
import pytest

from valisync.core.models import Signal
from valisync.core.session import Session


def _sig(ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        name="x",
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata={},
    )


def test_moving_average_uses_shrinking_window_at_head():
    sig = _sig([0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])
    out = Session().moving_average(sig, window=2)
    # head: mean([1]) ; then mean([1,2]), mean([2,3]), mean([3,4])
    np.testing.assert_allclose(out.values, [1.0, 1.5, 2.5, 3.5])
    np.testing.assert_array_equal(out.timestamps, sig.timestamps)
    assert out.file_format == "Derived"


def test_moving_average_rejects_out_of_range_window():
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        Session().moving_average(sig, window=0)
    with pytest.raises(ValueError):
        Session().moving_average(sig, window=4)  # > len


def test_linear_regression_recovers_a_line():
    sig = _sig([0.0, 1.0, 2.0], [1.0, 3.0, 5.0])  # y = 2x + 1
    out = Session().linear_regression(sig)
    np.testing.assert_allclose(out.values, [1.0, 3.0, 5.0])
    np.testing.assert_array_equal(out.timestamps, sig.timestamps)


def test_differentiate_central_with_endpoint_differences():
    sig = _sig([0.0, 1.0, 2.0], [1.0, 3.0, 5.0])  # constant slope 2
    out = Session().differentiate(sig)
    np.testing.assert_allclose(out.values, [2.0, 2.0, 2.0])
    assert len(out.values) == len(sig.values)


def test_integrate_cumulative_trapezoid_starts_at_zero():
    sig = _sig([0.0, 1.0, 2.0], [1.0, 1.0, 1.0])
    out = Session().integrate(sig)
    np.testing.assert_allclose(out.values, [0.0, 1.0, 2.0])
    assert len(out.values) == len(sig.values)


@pytest.mark.parametrize(
    "op", ["moving_average", "differentiate", "integrate", "linear_regression"]
)
def test_calcbar_rejects_too_few_samples(op):
    sig = _sig([0.0], [1.0])
    session = Session()
    with pytest.raises(ValueError):
        if op == "moving_average":
            session.moving_average(sig, window=1)
        else:
            getattr(session, op)(sig)


def test_calcbar_does_not_mutate_input():
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    ts_before = sig.timestamps.copy()
    vs_before = sig.values.copy()
    Session().moving_average(sig, window=2)
    Session().integrate(sig)
    np.testing.assert_array_equal(sig.timestamps, ts_before)
    np.testing.assert_array_equal(sig.values, vs_before)


def test_integrate_non_monotonic_matches_sorted():
    messy = _sig([0.0, 2.0, 1.0], [1.0, 3.0, 2.0])
    tidy = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    session = Session()
    out_m = session.integrate(messy)
    out_t = session.integrate(tidy)
    assert out_m.timestamps.tolist() == out_t.timestamps.tolist()
    assert out_m.values.tolist() == out_t.values.tolist()
    assert np.all(np.diff(out_m.timestamps) > 0)  # Derived は整列軸
