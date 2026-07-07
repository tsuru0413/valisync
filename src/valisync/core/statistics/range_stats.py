from __future__ import annotations

import math
from dataclasses import dataclass

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
        t_start > t_end (Req 13.5). Delegates the range reduction to the
        signal's sqrt-decomposition index (O(sqrt n)); non-finite (NaN/Inf)
        *values* are excluded via ``finite_view()`` inside the index and
        ``count`` is the number of finite samples in range (AN-01). When the
        range holds no finite samples (empty or all non-finite), all float
        statistics are NaN and count is 0.
        """
        if not math.isfinite(t_start):
            raise ValueError(f"t_start must be finite, got {t_start!r}")
        if not math.isfinite(t_end):
            raise ValueError(f"t_end must be finite, got {t_end!r}")
        if t_start > t_end:
            raise ValueError(f"t_start must be ≤ t_end, got {t_start!r} > {t_end!r}")

        return signal.range_stat_index().query(t_start, t_end)
