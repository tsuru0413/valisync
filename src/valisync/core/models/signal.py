from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Signal:
    """Immutable time-series signal. All invariants are enforced at construction time."""

    name: str
    timestamps: (
        np.ndarray
    )  # float64, shape=(n,), all finite; 記録どおり(非単調・重複あり得る)
    values: np.ndarray  # float64, shape=(n,)
    file_format: str  # "MDF4" | "CSV" | "Derived"
    bus_type: str  # "CAN" | "XCP" | "Ethernet" | "" (empty for CSV and Derived)
    source_file: str  # absolute path; empty string for Derived signals
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.timestamps) != len(self.values):
            raise ValueError(
                f"timestamps ({len(self.timestamps)}) and values ({len(self.values)}) "
                "must have the same length"
            )
        if len(self.timestamps) > 0 and not np.all(np.isfinite(self.timestamps)):
            idx = int(np.argmax(~np.isfinite(self.timestamps)))
            raise ValueError(f"timestamps contains non-finite value at index {idx}")
        object.__setattr__(
            self,
            "timestamps",
            self.timestamps.copy()
            if self.timestamps.flags.writeable
            else self.timestamps,
        )
        object.__setattr__(
            self,
            "values",
            self.values.copy() if self.values.flags.writeable else self.values,
        )
        self.timestamps.flags.writeable = False
        self.values.flags.writeable = False

    def sorted_view(self) -> tuple[np.ndarray, np.ndarray]:
        """Strictly-monotonic view for computation and rendering (spec §4.1).

        Stable-sorts by timestamp and keeps the last-recorded value for equal
        timestamps (CAN "last received wins"). Already-monotonic signals get
        the raw arrays back untouched (zero-copy), so the common case costs
        one O(n) diff check. Cached after the first call; the computation is
        idempotent, so racing initialisations are harmless.
        """
        cache = getattr(self, "_sorted_view_cache", None)
        if cache is not None:
            return cache
        ts, vs = self.timestamps, self.values
        if len(ts) < 2 or bool(np.all(np.diff(ts) > 0)):
            cache = (ts, vs)
        else:
            order = np.argsort(ts, kind="stable")
            ts_s = ts[order]
            vs_s = vs[order]
            # keep-last: 安定ソートで同値 ts は記録順のまま並ぶので、各ランの
            # 末尾(次の ts が大きくなる位置)だけ残せば「最後の記録」が勝つ
            keep = np.concatenate((np.diff(ts_s) > 0, [True]))
            ts_s = ts_s[keep]
            vs_s = vs_s[keep]
            ts_s.flags.writeable = False
            vs_s.flags.writeable = False
            cache = (ts_s, vs_s)
        object.__setattr__(self, "_sorted_view_cache", cache)
        return cache

    @property
    def is_monotonic(self) -> bool:
        """True when the sorted view is the raw arrays (zero-copy fast path)."""
        return self.sorted_view()[0] is self.timestamps
