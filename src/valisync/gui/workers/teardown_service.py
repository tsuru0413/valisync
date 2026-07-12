"""Off-UI-thread graveyard for freeing a closed file's ~10 GB in byte-budget
slices (FU-16). A closed file's Signal_Group is stashed here and drained a
budget's worth of bytes per zero-interval QTimer tick, so the event loop keeps
running between ticks and the UI stays responsive during the ~seconds of frees.

Runs entirely on the GUI thread (no worker thread): the freeze is per-tick byte
volume, not GIL contention (PoC verified) — naive offthread is a GIL trap.
Slicing by BYTES (not signal count) bounds a single huge array to one tick.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from valisync.core.models import Signal, SignalGroup

_BYTE_BUDGET = 64 * 1024 * 1024  # 64 MiB per tick


class TeardownService(QObject):
    def __init__(
        self,
        on_finished: Callable[[str], None] | None = None,
        *,
        byte_budget: int = _BYTE_BUDGET,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_finished = on_finished
        self._budget = byte_budget
        self._graveyard: list[tuple[str, Signal]] = []
        self._pending_count: dict[str, int] = {}
        self._pending_bytes = 0
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._drain)

    def pending_bytes(self) -> int:
        return self._pending_bytes

    def enqueue(self, key: str, group: SignalGroup) -> None:
        sigs = list(group.signals)
        if not sigs:
            if self._on_finished is not None:
                self._on_finished(key)
            return
        self._pending_count[key] = self._pending_count.get(key, 0) + len(sigs)
        for s in sigs:
            self._graveyard.append((key, s))
            self._pending_bytes += s.timestamps.nbytes + s.values.nbytes
        # NOTE: caller must not keep a ref to `group` after this (it does not).
        if not self._timer.isActive():
            self._timer.start()

    def _drain(self) -> None:
        freed = 0
        while self._graveyard:
            key, sig = self._graveyard.pop()
            freed += sig.timestamps.nbytes + sig.values.nbytes
            self._pending_bytes -= sig.timestamps.nbytes + sig.values.nbytes
            self._pending_count[key] -= 1
            if self._pending_count[key] == 0:
                del self._pending_count[key]
                if self._on_finished is not None:
                    self._on_finished(key)
            del sig  # drop the last strong ref -> the arrays free here
            if freed >= self._budget:
                break
        if not self._graveyard:
            self._timer.stop()
