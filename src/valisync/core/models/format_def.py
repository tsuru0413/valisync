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
                "名前は 1–64 文字で指定してください"  # noqa: RUF001
                f"（現在 {len(self.name)} 文字: {self.name!r}）"  # noqa: RUF001
            )
        if not (0 <= self.timestamp_column <= 255):
            raise ValueError(
                "時間列は 0–255 の範囲で指定してください"  # noqa: RUF001
                f"（現在 {self.timestamp_column}）"  # noqa: RUF001
            )
        if self.timestamp_unit not in ("sec", "msec"):
            raise ValueError(
                "時間単位は sec または msec を指定してください"
                f"（現在 {self.timestamp_unit!r}）"  # noqa: RUF001
            )
        if not (0 <= self.signal_start_column <= self.signal_end_column <= 255):
            raise ValueError(
                f"信号列は開始 ({self.signal_start_column}) ≤ 終了"
                f" ({self.signal_end_column}) かつ 0–255 の範囲で指定してください"  # noqa: RUF001
            )
        if self.signal_start_column <= self.timestamp_column <= self.signal_end_column:
            raise ValueError(
                f"時間列 ({self.timestamp_column}) を信号列の範囲"
                f" {self.signal_start_column}–{self.signal_end_column}"  # noqa: RUF001
                " に重ねることはできません"
            )
