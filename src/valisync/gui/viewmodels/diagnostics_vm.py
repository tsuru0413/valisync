"""DiagnosticsViewModel — Qt-free accumulator of load diagnostics (FB-02).

Collects Diagnostic records emitted by loads (success-time warnings and
hard-error messages) so the Diagnostics dock can display a session history.
Pure Python; the View subscribes for the "diagnostics" change tag.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from valisync.core.models.load_result import Diagnostic
from valisync.gui.viewmodels.observable import Observable


@dataclass(frozen=True)
class DiagnosticEntry:
    """A single diagnostic with its source file and receipt order (seq)."""

    level: str  # "error" | "warning" | "info"
    message: str
    source: str  # file basename
    signal_name: str | None
    seq: int  # monotonic receipt order (stable display order)


class DiagnosticsViewModel(Observable):
    """Accumulates DiagnosticEntry records; notifies "diagnostics" on change."""

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[DiagnosticEntry] = []
        self._seq: int = 0

    def add(self, source: str, diagnostics: Iterable[Diagnostic]) -> None:
        """Append each Diagnostic under *source*; notify once if any were added."""
        added = False
        for d in diagnostics:
            self._entries.append(
                DiagnosticEntry(
                    level=d.level,
                    message=d.message,
                    source=source,
                    signal_name=d.signal_name,
                    seq=self._seq,
                )
            )
            self._seq += 1
            added = True
        if added:
            self._notify("diagnostics")

    def clear(self) -> None:
        """Drop all entries and notify."""
        self._entries.clear()
        self._notify("diagnostics")

    def entries(self, level: str | None = None) -> list[DiagnosticEntry]:
        """Return entries, optionally filtered by level ("error"/"warning")."""
        if level is None:
            return list(self._entries)
        return [e for e in self._entries if e.level == level]

    def counts(self) -> tuple[int, int]:
        """Return (error_count, warning_count)."""
        errors = sum(1 for e in self._entries if e.level == "error")
        warnings = sum(1 for e in self._entries if e.level == "warning")
        return errors, warnings
