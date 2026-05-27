from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from valisync.core.models.signal import Signal


@dataclass(frozen=True)
class SignalGroup:
    """File-level collection of Signal objects loaded in a single operation."""

    signals: tuple[Signal, ...]
    source_path: Path  # must be absolute
    file_format: str  # "MDF4" | "CSV"
    loaded_at: datetime

    def __post_init__(self) -> None:
        if not self.source_path.is_absolute():
            raise ValueError(f"source_path must be absolute, got: {self.source_path}")
