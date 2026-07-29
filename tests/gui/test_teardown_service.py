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
        after = svc.pending_bytes()
        slice_bytes.append(before - after)
        assert svc.last_tick_bytes == before - after

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


def test_minted_columns_drain_in_the_same_entry_and_finish_once(qtbot) -> None:
    """E-3: 鋳造列 (SignalGroup.signals の外) も同じペーシングで解放され、
    on_finished は 1 回だけ発火する。

    同一 key を 2 エントリに分けると 1 本目の完了で on_finished が撃たれ、その宛先の
    AppViewModel.mark_released は初回 pop で確定する (app_viewmodel.py:212-215) ので、
    列がまだ残っているのに releasing 行が消える。だから列は同じエントリへ連結する。
    """
    done: list[str] = []
    svc = TeardownService(on_finished=done.append, byte_budget=1 * 1024 * 1024)
    col = _sig("mf4_1::W[1]", 500_000)
    ref = weakref.ref(col.values)
    grp = _group((_sig("s", 500_000),))

    svc.enqueue("g", grp, columns=(col,))

    assert svc.pending_signals() == 2  # グループ 1 本 + 列 1 本
    assert done == []  # まだ 1 本も解放していない
    del grp, col
    _drain_all(svc, qtbot)
    gc.collect()
    assert done == ["g"]  # エントリが 1 つ = 発火も 1 回
    assert ref() is None  # 列の配列が実際に解放された (会計だけでなく解放も通っている)


def test_zero_columns_do_not_finish_a_still_draining_group_early(qtbot) -> None:
    """列ゼロの通常ファイルで on_finished が早期発火しない。

    列を「もう 1 つのエントリ」として積む実装だと、空タプルが即時 finish 分岐
    (enqueue の `if not sigs`) に落ち、グループがまだドレイン中なのに releasing
    スピナーが消える。列ゼロは production の既定経路なので、ここが本命の回帰点。
    """
    done: list[str] = []
    svc = TeardownService(on_finished=done.append, byte_budget=1 * 1024 * 1024)

    svc.enqueue("g", _group((_sig("a", 500_000), _sig("b", 500_000))), columns=())

    assert done == []  # ドレイン前に「解放完了」を宣言していない
    _drain_all(svc, qtbot)
    assert done == ["g"]


def test_columns_alone_do_not_take_the_empty_group_shortcut(qtbot) -> None:
    """signals が空で列だけ残るグループも即時 finish にしない。

    pin しているのは実データの形ではなく **extend が空判定より前にあること**そのもの:
    順序が逆だと列がペーシングを迂回して同期解放される (列は実体化済み = バイトが重い)。
    """
    done: list[str] = []
    svc = TeardownService(on_finished=done.append)
    col = _sig("mf4_1::W[1]", 1_000)

    svc.enqueue("g", _group(()), columns=(col,))

    assert done == []
    assert svc.pending_signals() == 1
    del col
    qtbot.waitUntil(lambda: svc.pending_signals() == 0, timeout=5000)
    assert done == ["g"]


class _CountingArr:
    """ndarray-like whose .nbytes read is counted (proves WHO touches bytes)."""

    def __init__(self, nbytes: int, counter: list[int]) -> None:
        self._n = nbytes
        self._c = counter

    @property
    def nbytes(self) -> int:
        self._c[0] += 1
        return self._n


class _CountingSource:
    """values_source-like whose .nbytes_if_materialized read is counted.

    Accounting now goes through SampleSource (lazy-load), not sig.values, so
    the spy must expose the same surface the real teardown code reads.
    """

    def __init__(self, nbytes: int, counter: list[int]) -> None:
        self._n = nbytes
        self._c = counter

    @property
    def nbytes_if_materialized(self) -> int:
        self._c[0] += 1
        return self._n

    def array_if_materialized(self) -> None:
        # None を返して「未展開」を装い、バイト数の観測点を nbytes スパイ
        # (_CountingArr) 側に残す。
        return None


class _SpySignal:
    """Signal-like carrying counting sources; not a real Signal (SignalGroup does
    not type-check its members, so this rides through unmodified)."""

    def __init__(self, nbytes: int, counter: list[int]) -> None:
        self.timestamps = _CountingArr(nbytes // 2, counter)
        self._values_source = _CountingSource(nbytes // 2, counter)


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
