from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Delimiter(Enum):
    COMMA = ","
    TAB = "\t"
    SEMICOLON = ";"
    SPACE = " "


@dataclass(frozen=True)
class FormatDefinition:
    """CSV format definition.

    Invariants:
    - 1 <= len(name) <= 64
    - 0 <= timestamp_column <= 255
    - 0 <= signal_start_column <= signal_end_column <= 255
    - timestamp_column is outside signal_start_column..signal_end_column range
    - timestamp_unit is "sec" or "msec"
    """

    name: str
    delimiter: Delimiter
    timestamp_column: int
    timestamp_unit: str  # "sec" | "msec"
    signal_start_column: int
    signal_end_column: int
    has_header: bool
    has_unit_row: bool = False  # row immediately after header contains per-column units

    def __post_init__(self) -> None:
        if not (1 <= len(self.name) <= 64):
            raise ValueError(
                f"name must be 1-64 characters, got {len(self.name)}: {self.name!r}"
            )
        if not (0 <= self.timestamp_column <= 255):
            raise ValueError(
                f"timestamp_column must be 0-255, got {self.timestamp_column}"
            )
        if self.timestamp_unit not in ("sec", "msec"):
            raise ValueError(
                f"timestamp_unit must be 'sec' or 'msec', got {self.timestamp_unit!r}"
            )
        if not (0 <= self.signal_start_column <= self.signal_end_column <= 255):
            raise ValueError(
                f"signal columns must satisfy 0 <= signal_start_column ({self.signal_start_column})"
                f" <= signal_end_column ({self.signal_end_column}) <= 255"
            )
        if self.signal_start_column <= self.timestamp_column <= self.signal_end_column:
            raise ValueError(
                f"timestamp_column ({self.timestamp_column}) must not overlap"
                f" signal columns [{self.signal_start_column}, {self.signal_end_column}]"
            )
