"""ドレインは 1 ティックで予算を超えない (増分B・FU-16 の再来防止)。

バイト会計を正直にすると未展開の遅延グループは実質 0 バイトになり、330,004
シェルが 1 ティックで解放されて実測 649ms のフリーズになる。信号数の上限は
オプションではなく必須。**時間ではなく信号数で assert する** (マシン依存回避) —
デッドライン軸だけは注入した偽クロックで assert する (実時間は使わない)。
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from valisync.core.models import Signal, SignalGroup
from valisync.core.models.sample_source import EagerValues
from valisync.gui.workers.teardown_service import TeardownService


class _ZeroByteSource:
    """未展開の遅延ソース相当: 会計上 0 バイト."""

    is_materialized = False
    nbytes_if_materialized = 0

    def __init__(self, n: int) -> None:
        self.length = n

    def array(self) -> np.ndarray:  # pragma: no cover - 呼ばれてはいけない
        raise AssertionError("teardown must not materialize")

    def array_if_materialized(self) -> np.ndarray | None:
        # Task 5 で SampleSource に追加されるメンバ (会計の id-dedup 用)。
        # 会計は getattr フォールバックを使わず直接呼ぶので、ここに無いと
        # AttributeError で loud-fail する。
        return None


def _group_of(sigs: tuple[Signal, ...]) -> SignalGroup:
    return SignalGroup(
        signals=sigs,
        source_path=Path("/x.mf4").resolve(),
        file_format="MDF4",
        loaded_at=datetime.datetime.now(),
    )


def _lazy_group(n_signals: int, *, freeze_master: bool = True) -> SignalGroup:
    ts = np.arange(4, dtype=np.float64)
    if freeze_master:
        # 本番は Signal 構築前に master を凍結する (mdf_loader.py:487)。凍結しないと
        # Signal.__init__ (signal.py:77) が writeable な配列を信号ごとに copy するため
        # グループは master を共有せず、Task 5 の dedup テストが原理的に通らない。
        ts.flags.writeable = False
    sigs = tuple(
        Signal(
            name=f"s{i}",
            timestamps=ts,
            values_source=_ZeroByteSource(4),  # type: ignore[arg-type]
            file_format="MDF4",
            bus_type="",
            source_file="/x.mf4",
        )
        for i in range(n_signals)
    )
    return _group_of(sigs)


def _eager_group(n_signals: int, length: int) -> SignalGroup:
    """展開済み値を持つグループ (1 信号あたりの解放コストが約 3 倍の regime)。"""
    ts = np.arange(length, dtype=np.float64)
    ts.flags.writeable = False
    sigs = tuple(
        Signal(
            name=f"s{i}",
            timestamps=ts,
            values_source=EagerValues(np.arange(length, dtype=np.float64)),
            file_format="MDF4",
            bus_type="",
            source_file="/x.mf4",
        )
        for i in range(n_signals)
    )
    return _group_of(sigs)


def test_one_tick_never_frees_more_than_the_signal_budget(qtbot) -> None:  # type: ignore[no-untyped-def]
    # now を固定してデッドライン軸を無効化し、信号数軸だけを測る
    svc = TeardownService(signal_budget=100, now=lambda: 0.0)
    svc.enqueue("k", _lazy_group(1000))
    before = svc.pending_signals()
    svc._drain()  # 1 ティックぶんだけ回す
    freed = before - svc.pending_signals()
    assert freed == 100, f"1 ティックで {freed} 信号を解放した (上限 100)"


def test_drain_completes_across_ticks(qtbot) -> None:  # type: ignore[no-untyped-def]
    finished: list[str] = []
    svc = TeardownService(on_finished=finished.append, signal_budget=100)
    svc.enqueue("k", _lazy_group(1000))
    qtbot.waitUntil(lambda: finished == ["k"], timeout=5000)
    assert svc.pending_signals() == 0


def test_default_signal_budget_is_8000(qtbot) -> None:  # type: ignore[no-untyped-def]
    """count 軸の既定値 (ユーザー決定 3・ハード上限)。

    now を固定するのは必須 — 既定のまま実クロックで走らせるとデッドライン軸
    (8ms) が先に効いて 8,000 に届かず、count 軸を測れない。
    """
    svc = TeardownService(now=lambda: 0.0)
    svc.enqueue("k", _lazy_group(20000))
    before = svc.pending_signals()
    svc._drain()
    assert before - svc.pending_signals() == 8000


def test_tick_stops_at_the_deadline_with_a_fake_clock(qtbot) -> None:  # type: ignore[no-untyped-def]
    """デッドライン軸は偽クロックで assert する (実時間で assert しない)。

    spec の「時間で assert しない」制約はテストのオラクルについての制約であり、
    production 機構を時間軸にすることは禁じていない。
    """
    ticks = iter(range(10_000))
    svc = TeardownService(
        byte_budget=1 << 62,  # バイト軸を実質無効化
        signal_budget=10_000,  # 信号軸も 1 ティックで足りる大きさ
        tick_deadline_s=0.008,
        now=lambda: next(ticks) * 0.001,  # 呼ばれるたび +1ms
    )
    svc.enqueue("k", _lazy_group(10_000))
    before = svc.pending_signals()
    svc._drain()
    freed = before - svc.pending_signals()
    # 256 信号ごとに 1 回だけクロックを見るので、8 回目 (=2,048 信号) で 8ms に到達する。
    assert 0 < freed < 10_000, f"デッドラインで止まっていない (freed={freed})"


def test_one_tick_stops_over_materialized_signals_too(qtbot) -> None:  # type: ignore[no-untyped-def]
    """展開済み値 + sorted/finite/range_stat_index を持つ信号でも上限で止まる。

    シェルだけを流す他のテストは 1.6us regime しか通らない (実測: 展開済みは
    3.0us、+range_stat_index で 3.9-4.8us — 同じ予算でティックは 24-38ms になる)。
    """
    svc = TeardownService(signal_budget=100, byte_budget=1 << 62, now=lambda: 0.0)
    group = _eager_group(300, length=64)
    for sig in group.signals:
        sig.sorted_view()
        sig.finite_view()
        sig.range_stat_index()
    svc.enqueue("k", group)
    before = svc.pending_signals()
    svc._drain()
    assert before - svc.pending_signals() == 100
