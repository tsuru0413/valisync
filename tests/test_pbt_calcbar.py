"""Property-based tests for Calcbar operations (Task 13.4).

Property 23: Moving average — each output equals the mean of its shrinking window.
Property 24: Linear regression — residuals are orthogonal to [1, t] (least squares).
Property 25: Numerical differentiation — central difference, one-sided at ends.
Property 26: Cumulative trapezoidal integral — starts at 0, matches the rule.
Property 16 (Calcbar half): every Calcbar Derived_Signal conforms to the Signal
             data model (Derived, length match, timestamps shared with input).
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from valisync.core.models import Signal
from valisync.core.session import Session

from .conftest import valid_signals

pytestmark = pytest.mark.property


@given(sig=valid_signals(min_size=2, max_size=40), data=st.data())
def test_moving_average_matches_shrinking_window(
    sig: Signal, data: st.DataObject
) -> None:
    n = len(sig.values)
    window = data.draw(st.integers(min_value=1, max_value=n))
    out = Session().moving_average(sig, window)

    expected = np.array(
        [sig.values[max(0, i - window + 1) : i + 1].mean() for i in range(n)]
    )
    np.testing.assert_allclose(out.values, expected, rtol=1e-12, atol=1e-9)


@given(sig=valid_signals(min_size=2, max_size=40))
def test_linear_regression_residuals_are_orthogonal(sig: Signal) -> None:
    out = Session().linear_regression(sig)
    resid = sig.values - out.values
    t = sig.timestamps
    n = len(t)
    # Normal equations for a least-squares line: residuals orthogonal to 1 and t.
    scale1 = max(1.0, float(np.max(np.abs(sig.values))) * n)
    scale2 = max(1.0, float(np.max(np.abs(sig.values)) * np.max(np.abs(t))) * n)
    assert abs(float(resid.sum())) <= 1e-6 * scale1
    assert abs(float((resid * t).sum())) <= 1e-6 * scale2


@given(sig=valid_signals(min_size=2, max_size=40))
def test_differentiate_matches_difference_formula(sig: Signal) -> None:
    out = Session().differentiate(sig)
    v, t = sig.values, sig.timestamps
    expected = np.empty(len(v))
    expected[1:-1] = (v[2:] - v[:-2]) / (t[2:] - t[:-2])
    expected[0] = (v[1] - v[0]) / (t[1] - t[0])
    expected[-1] = (v[-1] - v[-2]) / (t[-1] - t[-2])
    np.testing.assert_allclose(out.values, expected, rtol=1e-12, atol=1e-9)


@given(sig=valid_signals(min_size=2, max_size=40))
def test_integrate_matches_cumulative_trapezoid(sig: Signal) -> None:
    out = Session().integrate(sig)
    v, t = sig.values, sig.timestamps
    segments = (v[1:] + v[:-1]) / 2.0 * (t[1:] - t[:-1])
    expected = np.concatenate([[0.0], np.cumsum(segments)])
    assert out.values[0] == 0.0
    np.testing.assert_allclose(out.values, expected, rtol=1e-12, atol=1e-9)


@given(sig=valid_signals(min_size=2, max_size=40), data=st.data())
def test_calcbar_outputs_conform_to_signal_model(
    sig: Signal, data: st.DataObject
) -> None:
    session = Session()
    window = data.draw(st.integers(min_value=1, max_value=len(sig.values)))
    results = [
        session.moving_average(sig, window),
        session.linear_regression(sig),
        session.differentiate(sig),
        session.integrate(sig),
    ]
    for r in results:
        assert r.file_format == "Derived"
        assert len(r.timestamps) == len(r.values) == len(sig.values)
        assert np.all(np.isfinite(r.timestamps))
        assert np.all(np.diff(r.timestamps) > 0)
        np.testing.assert_array_equal(r.timestamps, sig.timestamps)  # shares input axis
