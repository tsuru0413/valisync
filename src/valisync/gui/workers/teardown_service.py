"""Off-UI-thread graveyard for freeing a closed file's ~10 GB in byte-budget
slices (FU-16). A closed file's Signal_Group is stashed here and drained a
budget's worth of bytes per zero-interval QTimer tick, so the event loop keeps
running between ticks and the UI stays responsive during the ~seconds of frees.

Runs entirely on the GUI thread (no worker thread): the freeze is per-tick byte
volume, not GIL contention (PoC verified) -- naive offthread is a GIL trap.
Slicing by BYTES (not signal count) bounds a single huge array to one tick.

A tick is bounded on THREE axes -- bytes, signal COUNT and elapsed time --
whichever is hit first (see the budget constants below for the WHY of each).
Bytes alone stopped being sufficient once loading went lazy: an unmaterialized
lazy signal is ~0 bytes on the books, so a 330k-shell group would drain in a
single tick (measured 649 ms) -- exactly the FU-16 freeze the pacing exists to
prevent. The byte axis is still what keeps one huge array in its own tick.

enqueue() is O(1) in signal count: it stores each group's signals as one list
(a single C-level `list(tuple)` copy) and defers ALL per-signal work -- nbytes
accounting and the frees themselves -- to _drain(). Touching every signal at
enqueue time (summing nbytes over 330k signals) was itself a ~320 ms freeze on
the closing thread (measured at 264k), which partly defeated the handoff; the
perf E2E at prod scale caught it. Keeping that work in _drain keeps sync-close
independent of data size.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from valisync.core.models import Signal, SignalGroup

_BYTE_BUDGET = 64 * 1024 * 1024  # 64 MiB per tick
# 未展開の遅延シェルはバイト会計上ほぼ 0 なので、バイト予算だけでは 330k シェルが
# 1 ティックで解放され実測 649ms 固まる (FU-16 の再来)。解放コストは個数にも比例
# するため、信号数の上限を第 2 の軸として持つ。
_SIGNAL_BUDGET = 8_000  # ユーザー決定 3 (変更不可・ハード上限)
# WHY (第 3 軸): 予算はどちらもコストの proxy でしかない。1 信号の解放コストは状態で
# 1.6us (未展開シェル) → 4.8us (展開値 + sorted/finite + range_stat_index) と約 3 倍
# 動き、バイト軸は RangeStatIndex のブロック配列を数えないので補償できない。実測:
# 8,000 シェル = 13-17ms だが 8,000 展開信号 (240 サンプル) = 24ms・+RSI = 28ms、
# 1,200 サンプルでは 6,990 信号 / 64MiB で 36ms (両予算とも充足したまま)。
# frame budget と単調な唯一の軸は経過時間なので、それを実効の一次軸にする。
_TICK_DEADLINE_S = 0.008  # 半フレーム (60fps = 16.7ms)


class TeardownService(QObject):
    def __init__(
        self,
        on_finished: Callable[[str], None] | None = None,
        *,
        byte_budget: int = _BYTE_BUDGET,
        signal_budget: int = _SIGNAL_BUDGET,
        tick_deadline_s: float = _TICK_DEADLINE_S,
        now: Callable[[], float] = time.perf_counter,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_finished = on_finished
        self._budget = byte_budget
        self._signal_budget = signal_budget
        self._deadline = tick_deadline_s
        # クロックは注入可能 — テストは実時間で assert しない (マシン依存フレーク回避)。
        self._now = now
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
            s.timestamps.nbytes + _materialized_value_bytes(s)
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
        t0 = self._now()
        freed_bytes = 0
        freed_signals = 0
        deadline_hit = False
        while (
            self._groups
            and freed_bytes < self._budget
            and freed_signals < self._signal_budget
            and not deadline_hit
        ):
            key, sigs = self._groups[0]
            while (
                sigs
                and freed_bytes < self._budget
                and freed_signals < self._signal_budget
            ):
                sig = sigs.pop()
                # カウンタを pop の直後に更新するのは、会計が raise してもキューと
                # pending_signals() が乖離しないための安価な保険。
                self._pending_signals -= 1
                freed_signals += 1
                freed_bytes += sig.timestamps.nbytes + _materialized_value_bytes(sig)
                del sig  # drop the last strong ref -> the arrays free here
                # クロックは 256 信号ごとにだけ見る: 未展開シェル 1 本の解放は
                # ~1.6us なので、毎回 perf_counter を呼ぶとその自体が無視できない。
                if freed_signals & 0xFF == 0 and self._now() - t0 >= self._deadline:
                    deadline_hit = True
                    break
            if not sigs:
                self._groups.popleft()
                if self._on_finished is not None:
                    self._on_finished(key)
        if not self._groups:
            self._timer.stop()


def _materialized_value_bytes(sig: Signal) -> int:
    """未展開の値は 0。展開済み値+Signal 上の派生キャッシュ (float64 昇格等) を計上.

    未展開信号の sig.values を絶対に読まない (読むと遅延ロードを再誘発する)."""
    total = sig._values_source.nbytes_if_materialized
    seen: set[int] = set()
    sv = getattr(sig, "_sorted_view_cache", None)
    fv = getattr(sig, "_finite_view_cache", None)
    for pair in (sv, fv):
        if pair is None:
            continue
        for arr in pair:  # (timestamps, values) タプル
            if id(arr) not in seen:
                seen.add(id(arr))
                total += int(arr.nbytes)
    return total
