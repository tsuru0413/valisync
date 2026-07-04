from __future__ import annotations

from dataclasses import dataclass

from valisync.core.models.signal_group import SignalGroup


@dataclass(frozen=True)
class Diagnostic:
    """Single diagnostic message from a load operation."""

    level: str  # "error" | "warning" | "info"
    message: str
    line_number: int | None = None
    column_number: int | None = None
    signal_name: str | None = None
    sample_index: int | None = None

    def __post_init__(self) -> None:
        if self.level not in ("error", "warning", "info"):
            raise ValueError(
                f"level must be 'error', 'warning' or 'info', got {self.level!r}"
            )


@dataclass(frozen=True)
class LoadResult:
    """Result of a file load operation."""

    signal_group: SignalGroup | None
    diagnostics: tuple[Diagnostic, ...] = ()


class LoadCancelled(Exception):
    """Raised when a load is cancelled via the cooperative ``cancel`` callback.

    User-initiated: callers must NOT surface this as an error (no modal, no
    diagnostics entry) — see spec §4.1/§6.

    Defined here (not in session.py) to avoid a circular import: loaders need
    to raise it but must not import from session, which imports the loaders.
    """
