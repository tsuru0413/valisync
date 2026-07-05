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

        Reads on ``finite_view()``: samples whose value is non-finite (NaN/Inf)
        are treated as missing and excluded, so interpolation happens between
        the surrounding finite samples (AN-02). Returns ``None`` when there are
        no finite samples, or when *t* is outside the finite range (Req 12.7).
        A single finite sample holds forward (ZOH): its value for ``t >= ts0``
        and ``None`` before it (AN-03). Returns the exact sample value when *t*
        matches a timestamp exactly (Req 12.8).
        """
        ts, vs = signal.finite_view()
        n = len(ts)

        if n == 0:
            return None
        # AN-03: 単一サンプルは ZOH 前方保持 (t>=ts0 で値・t<ts0 は None)。
        # 方式に依らず保持 — 1 点では補間対象がないため。
        if n == 1:
            return float(vs[0]) if t >= ts[0] else None

        # Req 12.7: 複数サンプルの範囲外は None (右端範囲外は本増分では据え置き)
        if t < ts[0] or t > ts[-1]:
            return None

        # Req 12.8: exact match — searchsorted (side='left') returns the first
        # index where ts[idx] >= t; if ts[idx] == t it is an exact hit.
        idx = int(np.searchsorted(ts, t, side="left"))
        if idx < len(ts) and ts[idx] == t:
            return float(vs[idx])

        # t is strictly between ts[idx-1] and ts[idx] (idx >= 1 guaranteed
        # because t > ts[0] after the exact-match check above). Both endpoints
        # are finite (finite_view removed non-finite values — AN-02).
        lo, hi = idx - 1, idx

        if method is InterpolationMethod.LINEAR:
            alpha = (t - ts[lo]) / (ts[hi] - ts[lo])
            return float(vs[lo] + alpha * (vs[hi] - vs[lo]))

        if method is InterpolationMethod.ZERO_ORDER_HOLD:
            return float(vs[lo])

        if method is InterpolationMethod.NEAREST:
            if (t - ts[lo]) <= (ts[hi] - t):
                return float(vs[lo])
            return float(vs[hi])

        raise ValueError(f"unknown InterpolationMethod: {method!r}")
