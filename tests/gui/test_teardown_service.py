from __future__ import annotations

import gc
import weakref
from datetime import datetime
from pathlib import Path

import numpy as np

from valisync.core.models import Signal, SignalGroup
from valisync.gui.workers.teardown_service import TeardownService


def _sig(name: str, n: int) -> Signal:
    return Signal(
        name=name,
        timestamps=np.zeros(n, dtype=np.float64),
        values=np.zeros(n, dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def _group(sigs: tuple[Signal, ...]) -> SignalGroup:
    return SignalGroup(
        signals=sigs,
        source_path=Path("x.csv").resolve(),
        file_format="CSV",
        loaded_at=datetime(2026, 1, 1),
    )


def _drain_all(svc: TeardownService, qtbot) -> None:
    qtbot.waitUntil(lambda: svc.pending_bytes() == 0, timeout=5000)


def test_drains_in_byte_budget_slices(qtbot) -> None:
    """1 tick は byte 予算＋最大1配列を超えない（巨大配列 1 本は単独 tick）。"""  # noqa: RUF002
    # 各 Signal ~8 MB (1e6 f64 ×2). budget 16MB -> tick あたり ~2-3 signal.  # noqa: RUF003
    sigs = tuple(_sig(f"s{i}", 1_000_000) for i in range(10))
    svc = TeardownService(byte_budget=16 * 1024 * 1024)
    slice_bytes: list[int] = []
    orig = svc._drain

    def _spy() -> None:
        before = svc.pending_bytes()
        orig()
        slice_bytes.append(before - svc.pending_bytes())

    svc._drain = _spy  # type: ignore[method-assign]
    svc.enqueue("g", _group(sigs))
    _drain_all(svc, qtbot)
    max_signal_bytes = 1_000_000 * 8 * 2
    for b in slice_bytes:
        assert b <= 16 * 1024 * 1024 + max_signal_bytes  # noqa: RUF003 # 予算＋最大1配列


def test_huge_array_gets_its_own_tick(qtbot) -> None:
    """予算より大きい 1 配列でも単独 tick で解放できる（件数分割の 576ms スパイク回避）。"""  # noqa: RUF002
    big = _sig("big", 5_000_000)  # ~80 MB
    svc = TeardownService(byte_budget=16 * 1024 * 1024)
    svc.enqueue("g", _group((big,)))
    _drain_all(svc, qtbot)
    assert svc.pending_bytes() == 0


def test_on_finished_fires_per_key_and_actually_frees(qtbot) -> None:
    done: list[str] = []
    svc = TeardownService(on_finished=done.append, byte_budget=1 * 1024 * 1024)
    s = _sig("s", 1_000_000)
    ref = weakref.ref(s.values)
    grp = _group((s,))
    del s
    svc.enqueue("g", grp)
    del grp
    _drain_all(svc, qtbot)
    gc.collect()
    assert done == ["g"]
    assert ref() is None  # 配列が実際に解放された


def test_multiple_keys_fifo_each_finishes(qtbot) -> None:
    done: list[str] = []
    svc = TeardownService(on_finished=done.append, byte_budget=4 * 1024 * 1024)
    svc.enqueue("a", _group((_sig("a1", 500_000), _sig("a2", 500_000))))
    svc.enqueue("b", _group((_sig("b1", 500_000),)))
    _drain_all(svc, qtbot)
    assert done == ["a", "b"]


def test_empty_group_finishes_immediately(qtbot) -> None:
    done: list[str] = []
    svc = TeardownService(on_finished=done.append)
    svc.enqueue("g", _group(()))
    assert done == ["g"]
    assert svc.pending_bytes() == 0


class _CountingArr:
    """ndarray-like whose .nbytes read is counted (proves WHO touches bytes)."""

    def __init__(self, nbytes: int, counter: list[int]) -> None:
        self._n = nbytes
        self._c = counter

    @property
    def nbytes(self) -> int:
        self._c[0] += 1
        return self._n


class _SpySignal:
    """Signal-like carrying counting arrays; not a real Signal (SignalGroup does
    not type-check its members, so this rides through unmodified)."""

    def __init__(self, nbytes: int, counter: list[int]) -> None:
        self.timestamps = _CountingArr(nbytes // 2, counter)
        self.values = _CountingArr(nbytes // 2, counter)


def test_enqueue_is_o1_defers_byte_access_to_drain(qtbot) -> None:
    """enqueue must not touch any signal's arrays (O(1) in signal count).

    Summing nbytes over every signal at enqueue time was a ~320 ms UI freeze at
    prod scale (264k) -- the residual the perf E2E caught. This locks the fix:
    enqueue reads ZERO signal arrays; all per-signal byte work happens in drain.
    """
    counter = [0]
    spies = tuple(_SpySignal(8, counter) for _ in range(100))
    grp = SignalGroup(
        signals=spies,  # type: ignore[arg-type]
        source_path=Path("x.csv").resolve(),
        file_format="CSV",
        loaded_at=datetime(2026, 1, 1),
    )
    svc = TeardownService()
    svc.enqueue("g", grp)
    assert counter[0] == 0  # enqueue touched no signal arrays
    assert svc.pending_signals() == 100
    qtbot.waitUntil(lambda: svc.pending_signals() == 0, timeout=5000)
    assert counter[0] > 0  # drain is what reads nbytes
