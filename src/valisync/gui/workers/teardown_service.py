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
        self._last_tick_bytes = 0
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._drain)

    def pending_signals(self) -> int:
        return self._pending_signals

    @property
    def last_tick_bytes(self) -> int:
        """直近ティックで計上したバイト数 (バイト軸の唯一の観測点)."""
        return self._last_tick_bytes

    def pending_bytes(self) -> int:
        # Computed lazily over the still-held signals rather than tracked from
        # enqueue, so enqueue stays O(1). O(remaining) per call -- fine for the
        # small groups in tests; the prod drain-wait polls pending_signals().
        seen: set[int] = set()  # 呼び出しごとに新規 (寿命規約は _drain と同じ)
        return sum(
            _retained_bytes(s, seen) for _key, sigs in self._groups for s in sigs
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
        # seen はティック単位 (freed_bytes と同じ寿命)。id は生存中のオブジェクト間で
        # のみ一意なので、記録した配列より長生きする set は以後の全確保をエイリアス
        # する (実測 100% 再利用・memory gui_id_reuse_flake_object_recreation) —
        # ティックを跨ぐと後続グループが 0 バイト計上になりバイト軸が黙って死ぬ。
        # ティック内は安全: 会計対象の配列は全て live な Signal が保持しており、
        # _drain 内で ndarray を新規確保する経路も無い。共有 master がティックごと
        # 1 回計上される過大分は prod_demo で 64MiB 予算の 0.3% (direction-safe)。
        seen: set[int] = set()
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
                freed_bytes += _retained_bytes(sig, seen)
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
        # バイト軸を直接 assert できる唯一の観測点。pending_bytes は生存集合から
        # 都度再計算するため、共有配列があると _drain の会計と乖離しても差分に現れない。
        self._last_tick_bytes = freed_bytes
        if not self._groups:
            self._timer.stop()


def _retained_bytes(sig: Signal, seen: set[int]) -> int:
    """この Signal が保持しているバイト数 (既に数えた配列は id で除外).

    master はグループ内で identity 共有されるので、信号ごとに数えると prod_demo で
    実体 0.2 MiB に対し 10,316 MiB (約 5 万倍) を計上してしまう。
    未展開信号の sig.values は絶対に読まない (読むと遅延ロードを再誘発する) —
    値は array_if_materialized() で「展開済みのときだけ」取る。

    `_range_stat_index_cache` (RangeStatIndex のブロック配列 5 本) は計上しない:
    ブロック配列は √n スケールで小さく、元の ts/vs は finite_view と共有されるため
    二重計上になる。ただしこれは時間問題の解決ではない — 実測で RSI を持たせても
    バイト計上は変わらないままティックが 24→36ms に増える (だから第 3 軸の
    デッドラインが要る)。
    """
    total = 0
    ts = sig.timestamps
    if id(ts) not in seen:
        seen.add(id(ts))
        total += int(ts.nbytes)
    # getattr フォールバックは使わない — 名前がドリフトしたら実ソースで dedup が
    # 無言で消えるので、AttributeError で loud-fail させる。
    val = sig._values_source.array_if_materialized()
    if val is not None and id(val) not in seen:
        seen.add(id(val))
        total += int(val.nbytes)
    for pair in (
        getattr(sig, "_sorted_view_cache", None),
        getattr(sig, "_finite_view_cache", None),
    ):
        if pair is None:
            continue
        for arr in pair:  # (timestamps, values) タプル
            if id(arr) not in seen:
                seen.add(id(arr))
                total += int(arr.nbytes)
    return total
