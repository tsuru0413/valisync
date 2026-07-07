"""Recent Files MRU (SH-01). QSettings-backed; no Qt widgets."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

_KEY = "recent_files"
_ORG = "ValiSync"
_APP = "ValiSync"


class RecentFiles:
    """Most-recently-used file paths, persisted to QSettings.

    Newest first, de-duplicated, capped at *max_items*. `existing()` drops
    paths that no longer resolve on disk (files get moved/deleted).
    """

    def __init__(self, max_items: int = 10, settings: QSettings | None = None) -> None:
        self._max = max_items
        self._settings = settings if settings is not None else QSettings(_ORG, _APP)

    def items(self) -> list[str]:
        raw = self._settings.value(_KEY, [])
        # QSettings can collapse single-element list to str; always normalize to list[str]
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, list):
            return [str(p) for p in raw]
        return []

    def existing(self) -> list[str]:
        return [p for p in self.items() if Path(p).exists()]

    def add(self, path: str | Path) -> None:
        p = str(path)
        items = [x for x in self.items() if x != p]
        items.insert(0, p)
        del items[self._max :]
        self._settings.setValue(_KEY, items)

    def clear(self) -> None:
        self._settings.remove(_KEY)
