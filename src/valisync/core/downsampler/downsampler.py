from __future__ import annotations

import numpy as np

from valisync.core.models import Signal


def _minmax_indices(
    vs: np.ndarray, seg_starts: np.ndarray, seg_ends: np.ndarray
) -> np.ndarray:
    """Per-segment min-max sample selection, vectorized (NaN-aware).

    For each contiguous segment [seg_starts[i], seg_ends[i]) return the FIRST
    index attaining that segment's min and the FIRST attaining its max — matching
    np.nanargmin/np.nanargmax's leading-tie preference. A segment whose values are
    all NaN keeps its first index (seg start). Result is sorted, de-duplicated
    input indices.

    seg_starts must be strictly increasing (distinct bucket boundaries) so
    reduceat treats each as its own segment. seg_ends[i] == seg_starts[i+1].
    """
    n_seg = len(seg_starts)
    m = len(vs)

    # NaN を極値へ退避: min には +inf、max には -inf を割り当て決して勝たせない。
    finite = np.isfinite(vs)
    v_min = np.where(finite, vs, np.inf)
    v_max = np.where(finite, vs, -np.inf)

    # 各要素 -> 所属セグメント id(セグメント長で arange を反復)。
    seg_id = np.repeat(np.arange(n_seg), seg_ends - seg_starts)
    idx = np.arange(m)

    # セグメントごとの min/max 値(reduceat で一括縮約)。
    seg_min = np.minimum.reduceat(v_min, seg_starts)
    seg_max = np.maximum.reduceat(v_max, seg_starts)

    # 各セグメントで min/max を達成する「最初の」インデックス(非達成は番兵 m)。
    # 全 NaN セグメントは seg_min=+inf に全要素が一致 -> 先頭 index を選ぶ。
    min_hit = np.where(v_min == seg_min[seg_id], idx, m)
    max_hit = np.where(v_max == seg_max[seg_id], idx, m)
    argmin_seg = np.minimum.reduceat(min_hit, seg_starts)
    argmax_seg = np.minimum.reduceat(max_hit, seg_starts)

    return np.unique(np.concatenate([argmin_seg, argmax_seg]))


class Downsampler:
    """Min-max LOD downsampler for rendering large signals."""

    def downsample(self, signal: Signal, n: int) -> Signal:
        """Return a new Signal with at most *n* samples using min-max bucketing.

        Divides the signal into ``n // 2`` equal-width time buckets and retains
        the min-value and max-value sample from each bucket, producing at most
        ``n`` output points (Req 14.2). Output timestamps are always a strict
        subset of the input timestamps (Req 14.3, 14.6).

        When the *aligned* (sorted, dedup'd) view is already within *n* samples
        (Req 14.4), monotonic inputs return the same Signal object unchanged;
        non-monotonic inputs get a freshly-built Signal on the aligned axis
        instead, so the pass-through never leaks raw disorder downstream. The
        ``<= n`` threshold is evaluated against this aligned length, not the
        raw (possibly duplicate-laden) input length.

        Raises ValueError when *n* is not a plain integer, is bool, or is < 2
        (Req 14.7).
        """
        if isinstance(n, bool) or not isinstance(n, int):
            raise ValueError(f"n must be a plain integer, got {type(n).__name__}")
        if n < 2:
            raise ValueError(f"n must be ≥ 2, got {n!r}")

        ts, vs = signal.sorted_view()

        # Req 14.4: pass-through when already within target.
        # 非単調入力では raw をそのまま返すと下流(render)に非単調が漏れる
        # ため、整列ビューから作り直した Signal を返す(単調なら無コピー)。
        if len(ts) <= n:
            if signal.is_monotonic:
                return signal
            return Signal(
                name=signal.name,
                timestamps=ts,
                values=vs,
                file_format=signal.file_format,
                bus_type=signal.bus_type,
                source_file=signal.source_file,
                metadata=signal.metadata,
            )

        n_buckets = n // 2
        t_lo = float(ts[0])
        t_hi = float(ts[-1])
        width = (t_hi - t_lo) / n_buckets

        # Assign each sample to an equal-width time bucket. Because timestamps are
        # strictly increasing, bucket ids are non-decreasing, so each bucket's
        # samples form one contiguous slice — letting us pick its min/max in O(N)
        # total rather than re-scanning the whole array per bucket.
        bucket = ((ts - t_lo) / width).astype(np.intp)
        np.clip(bucket, 0, n_buckets - 1, out=bucket)

        seg_starts = np.concatenate(([0], np.nonzero(np.diff(bucket))[0] + 1))
        seg_ends = np.concatenate((seg_starts[1:], [len(bucket)]))

        sorted_idx = _minmax_indices(vs, seg_starts, seg_ends)
        return Signal(
            name=signal.name,
            timestamps=ts[sorted_idx],
            values=vs[sorted_idx],
            file_format=signal.file_format,
            bus_type=signal.bus_type,
            source_file=signal.source_file,
            metadata=signal.metadata,
        )
