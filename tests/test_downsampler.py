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


def test_downsample_non_monotonic_output_is_monotonic() -> None:
    ts = [float(x) for x in [0, 5, 1, 6, 2, 7, 3, 8, 4, 9]]
    sig = _sig(ts, [float(i) for i in range(10)])
    out = Downsampler().downsample(sig, 4)
    assert np.all(np.diff(out.timestamps) > 0)


def test_downsample_passthrough_non_monotonic_returns_sorted_signal() -> None:
    sig = _sig(
        [0.0, 2.0, 1.0], [1.0, 2.0, 3.0]
    )  # len<=n のパススルー経路 returns sorted signal
    out = Downsampler().downsample(sig, 10)
    assert np.all(np.diff(out.timestamps) > 0)
    assert out.timestamps.tolist() == [0.0, 1.0, 2.0]


def test_downsample_passthrough_monotonic_returns_same_object() -> None:
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    assert Downsampler().downsample(sig, 10) is sig  # fast path は無コピー維持


def _segs(starts: list[int], m: int) -> tuple[np.ndarray, np.ndarray]:
    """Build (seg_starts, seg_ends) for contiguous segments over m elements."""
    seg_starts = np.array(starts, dtype=np.intp)
    seg_ends = np.concatenate((seg_starts[1:], [m])).astype(np.intp)
    return seg_starts, seg_ends


def test_minmax_indices_single_segment_global_min_max() -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    vs = np.array([5.0, 6.0, 7.0, -3.0, 4.0, 2.0, 1.0, 9.0, 8.0, 0.0])
    seg_starts, seg_ends = _segs([0], len(vs))  # one bucket
    # global min -3 @ idx3, global max 9 @ idx7
    assert _minmax_indices(vs, seg_starts, seg_ends).tolist() == [3, 7]


def test_minmax_indices_two_segments() -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    vs = np.array([5.0, 6.0, 7.0, -3.0, 4.0, 2.0, 1.0, 9.0, 8.0, 0.0])
    seg_starts, seg_ends = _segs([0, 5], len(vs))
    # seg0 [idx0..4]: min -3@3, max 7@2 ; seg1 [idx5..9]: min 0@9, max 9@7
    assert _minmax_indices(vs, seg_starts, seg_ends).tolist() == [2, 3, 7, 9]


def test_minmax_indices_first_occurrence_tie_break() -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    vs = np.array([3.0, 1.0, 3.0, 1.0])  # max 3 first@0, min 1 first@1
    seg_starts, seg_ends = _segs([0], len(vs))
    assert _minmax_indices(vs, seg_starts, seg_ends).tolist() == [0, 1]


def test_minmax_indices_mixed_nan_segment() -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    vs = np.array([np.nan, 5.0, np.nan, 2.0, np.nan])  # min 2@3, max 5@1
    seg_starts, seg_ends = _segs([0], len(vs))
    assert _minmax_indices(vs, seg_starts, seg_ends).tolist() == [1, 3]


def test_minmax_indices_all_nan_segment_keeps_first() -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    vs = np.array([np.nan, np.nan, np.nan])
    seg_starts, seg_ends = _segs([0], len(vs))
    assert _minmax_indices(vs, seg_starts, seg_ends).tolist() == [0]


def _reference_indices(
    vs: np.ndarray, seg_starts: np.ndarray, seg_ends: np.ndarray
) -> np.ndarray:
    """Independent reference: the pre-vectorization per-bucket loop."""
    result: set[int] = set()
    for lo, hi in zip(seg_starts.tolist(), seg_ends.tolist(), strict=True):
        seg = vs[lo:hi]
        if np.any(np.isfinite(seg)):
            result.add(lo + int(np.nanargmin(seg)))
            result.add(lo + int(np.nanargmax(seg)))
        else:
            result.add(lo)
    return np.array(sorted(result))


@pytest.mark.parametrize("nan_frac", [0.0, 0.05, 0.5, 1.0])
def test_minmax_indices_matches_reference_loop(nan_frac: float) -> None:
    from valisync.core.downsampler.downsampler import _minmax_indices

    rng = np.random.default_rng(0)
    m = 5000
    vs = rng.standard_normal(m)
    if nan_frac > 0:
        vs[rng.random(m) < nan_frac] = np.nan
    # 40 contiguous segments of ~equal length (strictly-increasing starts).
    seg_starts = np.unique(np.linspace(0, m, 41, endpoint=True).astype(np.intp)[:-1])
    seg_ends = np.concatenate((seg_starts[1:], [m])).astype(np.intp)

    got = _minmax_indices(vs, seg_starts, seg_ends)
    ref = _reference_indices(vs, seg_starts, seg_ends)
    assert got.tolist() == ref.tolist()
