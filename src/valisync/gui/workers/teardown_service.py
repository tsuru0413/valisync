"""Off-UI-thread graveyard for freeing a closed file's ~10 GB in byte-budget
slices (FU-16). A closed file's Signal_Group is stashed here and drained a
budget's worth of bytes per zero-interval QTimer tick, so the event loop keeps
running between ticks and the UI stays responsive during the ~seconds of frees.

Runs entirely on the GUI thread (no worker thread): the freeze is per-tick byte
volume, not GIL contention (PoC verified) -- naive offthread is a GIL trap.
Slicing by BYTES (not signal count) bounds a single huge array to one tick.

enqueue() is O(1) in signal count: it stores each group's signals as one list
(a single C-level `list(tuple)` copy) and defers ALL per-signal work -- nbytes
accounting and the frees themselves -- to _drain(). Touching every signal at
enqueue time (summing nbytes over 330k signals) was itself a ~320 ms freeze on
the closing thread (measured at 264k), which partly defeated the handoff; the
perf E2E at prod scale caught it. Keeping that work in _drain keeps sync-close
independent of data size.
"""

from __future__ import annotations

from collections import deque
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
        # FIFO across groups: the front group drains fully before the next, so
        # the oldest closed file releases first. Order WITHIN a group is
        # irrelevant (all its signals free before on_finished fires), so _drain
        # pops from each list's end (O(1), no shifting).
        self._groups: deque[tuple[str, list[Signal]]] = deque()
        self._pending_signals = 0
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._drain)

    def pending_signals(self) -> int:
        return self._pending_signals

    def pending_bytes(self) -> int:
        # Computed lazily over the still-held signals rather than tracked from
        # enqueue, so enqueue stays O(1). O(remaining) per call -- fine for the
        # small groups in tests; the prod drain-wait polls pending_signals().
        return sum(
            s.timestamps.nbytes + s.values.nbytes
            for _key, sigs in self._groups
            for s in sigs
        )

    def enqueue(self, key: str, group: SignalGroup) -> None:
        sigs = list(group.signals)  # single C-level copy -- no per-signal loop
        if not sigs:
            if self._on_finished is not None:
                self._on_finished(key)
            return
        self._pending_signals += len(sigs)
        self._groups.append((key, sigs))
        # NOTE: caller must not keep a ref to `group` after this (it does not);
        # `sigs` becomes the sole owner, so popping from it frees the arrays.
        if not self._timer.isActive():
            self._timer.start()

    def _drain(self) -> None:
        freed = 0
        while self._groups and freed < self._budget:
            key, sigs = self._groups[0]
            while sigs and freed < self._budget:
                sig = sigs.pop()
                freed += sig.timestamps.nbytes + sig.values.nbytes
                self._pending_signals -= 1
                del sig  # drop the last strong ref -> the arrays free here
            if not sigs:
                self._groups.popleft()
                if self._on_finished is not None:
                    self._on_finished(key)
        if not self._groups:
            self._timer.stop()
