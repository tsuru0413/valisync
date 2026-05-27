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
    )  # float64, shape=(n,), strictly monotone increasing, all finite
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
        if len(self.timestamps) > 0:
            if not np.all(np.isfinite(self.timestamps)):
                idx = int(np.argmax(~np.isfinite(self.timestamps)))
                raise ValueError(f"timestamps contains non-finite value at index {idx}")
            if not np.all(np.diff(self.timestamps) > 0):
                diffs = np.diff(self.timestamps)
                idx = int(np.argmax(diffs <= 0)) + 1
                raise ValueError(
                    f"timestamps not strictly monotonically increasing at index {idx}"
                )
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
