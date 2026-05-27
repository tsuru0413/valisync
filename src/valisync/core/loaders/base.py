from __future__ import annotations

from pathlib import Path
from typing import Protocol

from valisync.core.models.load_result import LoadResult


class SignalLoader(Protocol):
    """Format-specific signal loading interface."""

    def load(self, file_path: Path) -> LoadResult:
        """Load a file and return a LoadResult containing SignalGroup and diagnostics."""
        ...

    def supports(self, file_path: Path) -> bool:
        """Return True if this loader can handle the given file."""
        ...
