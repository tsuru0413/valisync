from __future__ import annotations

from dataclasses import dataclass

from valisync.core.models.signal_group import SignalGroup


@dataclass(frozen=True)
class Diagnostic:
    """Single diagnostic message from a load operation."""

    level: str  # "error" | "warning"
    message: str
    line_number: int | None = None
    column_number: int | None = None
    signal_name: str | None = None
    sample_index: int | None = None

    def __post_init__(self) -> None:
        if self.level not in ("error", "warning"):
            raise ValueError(f"level must be 'error' or 'warning', got {self.level!r}")


@dataclass(frozen=True)
class LoadResult:
    """Result of a file load operation."""

    signal_group: SignalGroup | None
    diagnostics: tuple[Diagnostic, ...] = ()
