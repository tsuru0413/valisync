from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from valisync.core.models import Signal


@dataclass(frozen=True)
class StatisticsResult:
    """Statistics over a time range. All float fields are float64."""

    mean: float
    max: float
    min: float
    std: float  # population std (ddof=0)
    count: int


class RangeStatistics:
    """Computes descriptive statistics for a Signal over a closed time range."""

    def compute(
        self,
        signal: Signal,
        t_start: float,
        t_end: float,
    ) -> StatisticsResult:
        """Return statistics for samples where t_start ≤ timestamp ≤ t_end.

        Raises ValueError when t_start or t_end is NaN/Inf (Req 13.6) or when
        t_start > t_end (Req 13.5). Non-finite (NaN/Inf) *values* in range are
        excluded via ``finite_view()``; ``count`` is the number of finite
        samples in range (AN-01). When the range holds no finite samples
        (empty or all non-finite), all float statistics are NaN and count is 0.
        """
        if not math.isfinite(t_start):
            raise ValueError(f"t_start must be finite, got {t_start!r}")
        if not math.isfinite(t_end):
            raise ValueError(f"t_end must be finite, got {t_end!r}")
        if t_start > t_end:
            raise ValueError(f"t_start must be ≤ t_end, got {t_start!r} > {t_end!r}")

        ts, vs = signal.finite_view()

        in_range = vs[(ts >= t_start) & (ts <= t_end)]

        if len(in_range) == 0:
            nan = float("nan")
            return StatisticsResult(mean=nan, max=nan, min=nan, std=nan, count=0)

        return StatisticsResult(
            mean=float(np.mean(in_range)),
            max=float(np.max(in_range)),
            min=float(np.min(in_range)),
            std=float(np.std(in_range, ddof=0)),
            count=len(in_range),
        )
