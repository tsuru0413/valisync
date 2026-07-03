from __future__ import annotations

import numpy as np

from valisync.core.models import Signal


class Downsampler:
    """Min-max LOD downsampler for rendering large signals."""

    def downsample(self, signal: Signal, n: int) -> Signal:
        """Return a new Signal with at most *n* samples using min-max bucketing.

        Divides the signal into ``n // 2`` equal-width time buckets and retains
        the min-value and max-value sample from each bucket, producing at most
        ``n`` output points (Req 14.2). Output timestamps are always a strict
        subset of the input timestamps (Req 14.3, 14.6).

        Returns *signal* unchanged when ``len(signal.timestamps) <= n`` (Req 14.4).

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

        result: set[int] = set()
        for lo, hi in zip(seg_starts.tolist(), seg_ends.tolist(), strict=True):
            seg = vs[lo:hi]
            if np.any(np.isfinite(seg)):
                result.add(lo + int(np.nanargmin(seg)))
                result.add(lo + int(np.nanargmax(seg)))
            else:
                result.add(lo)  # all-NaN bucket: keep one sample

        sorted_idx = np.array(sorted(result))
        return Signal(
            name=signal.name,
            timestamps=ts[sorted_idx],
            values=vs[sorted_idx],
            file_format=signal.file_format,
            bus_type=signal.bus_type,
            source_file=signal.source_file,
            metadata=signal.metadata,
        )
