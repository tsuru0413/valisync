from __future__ import annotations

from enum import Enum

import numpy as np

from valisync.core.models import Signal


class InterpolationMethod(Enum):
    LINEAR = "linear"
    ZERO_ORDER_HOLD = "zero_order_hold"
    NEAREST = "nearest"


class Interpolator:
    """Point-in-time interpolation for GUI cursor value read-out."""

    def interpolate(
        self,
        signal: Signal,
        t: float,
        method: InterpolationMethod,
    ) -> float | None:
        """Return the interpolated value of *signal* at time *t*.

        Returns ``None`` when the signal has fewer than 2 samples (Req 12.10)
        or when *t* is outside the signal's timestamp range (Req 12.7).
        Returns ``float('nan')`` when adjacent samples contain NaN (Req 12.11).
        Returns the exact sample value without interpolation when *t* matches a
        timestamp exactly (Req 12.8).
        """
        ts = signal.timestamps
        vs = signal.values

        # Req 12.10: insufficient samples
        if len(ts) < 2:
            return None

        # Req 12.7: out of range
        if t < ts[0] or t > ts[-1]:
            return None

        # Req 12.8: exact match — searchsorted (side='left') returns the first
        # index where ts[idx] >= t; if ts[idx] == t it is an exact hit.
        idx = int(np.searchsorted(ts, t, side="left"))
        if idx < len(ts) and ts[idx] == t:
            return float(vs[idx])

        # t is strictly between ts[idx-1] and ts[idx] (idx >= 1 guaranteed
        # because t > ts[0] after the exact-match check above).
        lo, hi = idx - 1, idx

        if method is InterpolationMethod.LINEAR:
            # Req 12.11: NaN adjacent values propagate
            if np.isnan(vs[lo]) or np.isnan(vs[hi]):
                return float("nan")
            alpha = (t - ts[lo]) / (ts[hi] - ts[lo])
            return float(vs[lo] + alpha * (vs[hi] - vs[lo]))

        if method is InterpolationMethod.ZERO_ORDER_HOLD:
            return float(vs[lo])

        if method is InterpolationMethod.NEAREST:
            if (t - ts[lo]) <= (ts[hi] - t):
                return float(vs[lo])
            return float(vs[hi])

        raise ValueError(f"unknown InterpolationMethod: {method!r}")
