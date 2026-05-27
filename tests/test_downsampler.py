"""Unit tests for Downsampler (Task 10.4).

Covers validation (Req 14.7: n < 2 / non-integer / bool), pass-through
(Req 14.4: len ≤ n), and the output invariants (Req 14.1/14.3/14.6: count ≤ n,
timestamps a strictly-increasing subset of the input).
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from valisync.core.downsampler import Downsampler
from valisync.core.models import Signal


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


@pytest.mark.parametrize("n", [1, 0, -5])
def test_n_below_two_rejected(n: int) -> None:
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        Downsampler().downsample(sig, n)


def test_non_integer_n_rejected() -> None:
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        Downsampler().downsample(sig, 2.5)  # type: ignore[arg-type]


def test_bool_n_rejected() -> None:
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        Downsampler().downsample(sig, True)  # type: ignore[arg-type]


def test_passthrough_when_within_target() -> None:
    sig = _sig([0.0, 1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0, 5.0])
    assert Downsampler().downsample(sig, 10) is sig
    assert Downsampler().downsample(sig, 5) is sig  # len == n boundary


def test_output_within_target_and_subset() -> None:
    ts = np.arange(100, dtype=np.float64)
    vs = np.sin(ts / 5.0)
    sig = Signal("s", ts, vs, "Derived", "", "", {})
    result = Downsampler().downsample(sig, 10)

    assert len(result.timestamps) <= 10
    # output timestamps are a subset of the input (Req 14.3/14.6)
    assert np.all(np.isin(result.timestamps, ts))
    # strictly increasing (Req 14.6)
    assert np.all(np.diff(result.timestamps) > 0)


def test_global_min_max_retained_single_bucket() -> None:
    ts = np.arange(10, dtype=np.float64)
    vs = np.array([5.0, 6.0, 7.0, -3.0, 4.0, 2.0, 1.0, 9.0, 8.0, 0.0])
    sig = Signal("s", ts, vs, "Derived", "", "", {})
    # n=2 → one bucket spanning the whole range → must keep global min and max
    result = Downsampler().downsample(sig, 2)
    assert -3.0 in result.values  # global min at index 3
    assert 9.0 in result.values  # global max at index 7


def test_all_nan_bucket_keeps_one_sample() -> None:
    ts = np.arange(10, dtype=np.float64)
    vs = np.full(10, np.nan)
    sig = Signal("s", ts, vs, "Derived", "", "", {})
    result = Downsampler().downsample(sig, 2)
    assert len(result.timestamps) == 1


def test_downsample_large_signal_is_fast() -> None:
    """min-max downsampling must be O(N), not O(n_buckets x N) (LOD render budget).

    A 1M-point signal downsampled to ~2000 points must complete well under a
    second; the per-bucket full-array-scan algorithm takes several seconds.
    """
    n_samples = 1_000_000
    ts = np.arange(n_samples, dtype=np.float64)
    vs = np.sin(ts / 1000.0)
    sig = Signal("s", ts, vs, "Derived", "", "", {})

    start = time.perf_counter()
    result = Downsampler().downsample(sig, 2000)
    elapsed = time.perf_counter() - start

    assert len(result.timestamps) <= 2000
    assert elapsed < 1.0
