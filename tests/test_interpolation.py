"""Unit tests for Interpolator (Task 10.4).

Covers the three methods plus the edge cases from Requirements 12.7 (out of
range → None) and 12.8 (exact match). AN-02/03 update the former 12.10/12.11
behaviours: NaN samples are excluded (interpolate across the gap between
finite neighbours) and a single finite sample holds forward (ZOH).
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
def test_single_sample_zoh_forward_hold(method: InterpolationMethod) -> None:
    """単一サンプルは t>=ts0 で値を保持・t<ts0 は None (AN-03・方式非依存)."""
    sig = _sig([5.0], [1.0])
    interp = Interpolator()
    assert interp.interpolate(sig, 5.0, method) == 1.0  # 厳密一致
    assert interp.interpolate(sig, 9.0, method) == 1.0  # 前方保持 (ZOH)
    assert interp.interpolate(sig, 4.0, method) is None  # サンプル以前


def test_all_non_finite_signal_returns_none() -> None:
    """全値が非有限の信号は有限サンプル0で None (AN-02/03)."""
    sig = _sig([0.0, 1.0], [math.nan, math.inf])
    assert Interpolator().interpolate(sig, 0.5, LINEAR) is None


def test_linear_interpolates_across_nan_gap() -> None:
    """NaN サンプルを欠測として除外し前後の有限サンプル間で線形補間 (AN-02)."""
    sig = _sig([0.0, 5.0, 10.0], [0.0, math.nan, 100.0])
    # 有限は (0,0) と (10,100) → t=5 は線形で 50
    assert Interpolator().interpolate(sig, 5.0, LINEAR) == 50.0


def test_nan_adjacent_now_uses_finite_neighbors() -> None:
    """2 サンプルの片方が NaN → 有限は1点 → ZOH 前方保持で解釈 (AN-02+03)."""
    interp = Interpolator()
    left_nan = _sig([0.0, 10.0], [math.nan, 100.0])  # 有限は (10,100) のみ
    right_nan = _sig([0.0, 10.0], [0.0, math.nan])  # 有限は (0,0) のみ
    assert interp.interpolate(left_nan, 5.0, LINEAR) is None  # t=5 < 10
    assert interp.interpolate(right_nan, 5.0, LINEAR) == 0.0  # t=5 >= 0 保持


def test_interpolate_non_monotonic_input_matches_sorted() -> None:
    messy = _sig([0.0, 2.0, 1.0], [0.0, 20.0, 10.0])
    tidy = _sig([0.0, 1.0, 2.0], [0.0, 10.0, 20.0])
    interp = Interpolator()
    for t in (0.5, 1.0, 1.5):
        assert interp.interpolate(messy, t, LINEAR) == interp.interpolate(
            tidy, t, LINEAR
        )
