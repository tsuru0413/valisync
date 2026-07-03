"""Unit tests for Interpolator (Task 10.4).

Covers the three methods plus the edge cases from Requirements 12.7 (out of
range → None), 12.8 (exact match), 12.10 (insufficient samples → None) and
12.11 (NaN-adjacent → NaN).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from valisync.core.interpolation import InterpolationMethod, Interpolator
from valisync.core.models import Signal

LINEAR = InterpolationMethod.LINEAR
ZOH = InterpolationMethod.ZERO_ORDER_HOLD
NEAREST = InterpolationMethod.NEAREST


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


def test_linear_midpoint() -> None:
    sig = _sig([0.0, 10.0], [0.0, 100.0])
    assert Interpolator().interpolate(sig, 5.0, LINEAR) == pytest.approx(50.0)
    assert Interpolator().interpolate(sig, 2.5, LINEAR) == pytest.approx(25.0)


def test_zero_order_hold_returns_left() -> None:
    sig = _sig([0.0, 10.0], [3.0, 100.0])
    assert Interpolator().interpolate(sig, 7.0, ZOH) == 3.0


def test_nearest_picks_closest() -> None:
    sig = _sig([0.0, 10.0], [0.0, 100.0])
    assert Interpolator().interpolate(sig, 3.0, NEAREST) == 0.0
    assert Interpolator().interpolate(sig, 7.0, NEAREST) == 100.0


def test_nearest_tie_prefers_left() -> None:
    sig = _sig([0.0, 10.0], [0.0, 100.0])
    assert Interpolator().interpolate(sig, 5.0, NEAREST) == 0.0


@pytest.mark.parametrize("method", list(InterpolationMethod))
def test_exact_match_returns_sample(method: InterpolationMethod) -> None:
    sig = _sig([0.0, 10.0, 20.0], [1.0, 2.0, 3.0])
    assert Interpolator().interpolate(sig, 10.0, method) == 2.0
    assert Interpolator().interpolate(sig, 0.0, method) == 1.0
    assert Interpolator().interpolate(sig, 20.0, method) == 3.0


@pytest.mark.parametrize("method", list(InterpolationMethod))
@pytest.mark.parametrize("t", [-1.0, 20.1])
def test_out_of_range_returns_none(method: InterpolationMethod, t: float) -> None:
    sig = _sig([0.0, 10.0, 20.0], [1.0, 2.0, 3.0])
    assert Interpolator().interpolate(sig, t, method) is None


@pytest.mark.parametrize("method", list(InterpolationMethod))
def test_insufficient_samples_returns_none(method: InterpolationMethod) -> None:
    sig = _sig([5.0], [1.0])
    assert Interpolator().interpolate(sig, 5.0, method) is None


def test_linear_nan_adjacent_propagates() -> None:
    left_nan = _sig([0.0, 10.0], [math.nan, 100.0])
    right_nan = _sig([0.0, 10.0], [0.0, math.nan])
    assert math.isnan(Interpolator().interpolate(left_nan, 5.0, LINEAR))  # type: ignore[arg-type]
    assert math.isnan(Interpolator().interpolate(right_nan, 5.0, LINEAR))  # type: ignore[arg-type]


def test_interpolate_non_monotonic_input_matches_sorted() -> None:
    messy = _sig([0.0, 2.0, 1.0], [0.0, 20.0, 10.0])
    tidy = _sig([0.0, 1.0, 2.0], [0.0, 10.0, 20.0])
    interp = Interpolator()
    for t in (0.5, 1.0, 1.5):
        assert interp.interpolate(messy, t, LINEAR) == interp.interpolate(
            tidy, t, LINEAR
        )
