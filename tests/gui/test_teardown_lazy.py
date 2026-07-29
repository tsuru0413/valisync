from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from tests.lazy_stubs import CountingLazy
from valisync.core.models import Signal, SignalGroup
from valisync.gui.workers.teardown_service import TeardownService


def _lazy_group(n_signals: int, length: int) -> tuple[SignalGroup, list[CountingLazy]]:
    ts = np.arange(length, dtype=np.float64)
    # 本番 (MDF) は Signal 構築前に master を凍結する (mdf_loader.py)。凍結しないと
    # Signal.__init__ が writeable な配列を信号ごとに copy するのでグループが master を
    # 共有せず、会計の identity-dedup が原理的に観測できない (fixture が本番と別物になる)。
    ts.flags.writeable = False
    srcs = [CountingLazy(length) for _ in range(n_signals)]
    sigs = tuple(
        Signal(
            name=f"s{i}",
            timestamps=ts,
            values_source=s,  # type: ignore[arg-type]
            file_format="MDF4",
            bus_type="",
            source_file="/x.mf4",
        )
        for i, s in enumerate(srcs)
    )
    g = SignalGroup(
        signals=sigs,
        source_path=Path("/x.mf4").resolve(),
        file_format="MDF4",
        loaded_at=datetime.datetime.now(),
    )
    return g, srcs


def test_pending_bytes_counts_a_materialized_lazy_value_without_reading_others(
    qtbot,  # type: ignore[no-untyped-def]
) -> None:
    """遅延ソース混在グループでの ``pending_bytes()`` の会計を pin する。

    「展開しない」だけを見る形 (旧 test_pending_bytes_does_not_materialize) は
    **完全に冗長**だった: 同じ変異は下の ``test_drain_does_not_materialize`` が
    実 ``_drain`` 経由で殺し、``pending_bytes()`` 経路そのものも
    ``test_teardown_pacing.py::test_shared_master_is_counted_once_per_group``
    (``_ZeroByteSource.array()`` が AssertionError を投げる) が殺す。

    冗長でない部分はここ: **遅延ソースが展開済みのときにそのバイトが載る**こと。
    既存の展開済み会計テスト (test_materialized_value_is_added_to_the_master /
    test_shared_value_array_is_counted_once) は ``EagerValues`` しか通しておらず、
    「``array_if_materialized()`` が遅延ソースでも実配列を返す」= teardown 会計の
    id-dedup の土台は遅延側では未検証だった。共有 master は 1 回だけ、未展開の
    49 本は 0 バイト、展開済み 1 本だけが値ぶんを足す — の 3 点を同時に固定する。
    """
    svc = TeardownService()
    g, srcs = _lazy_group(50, 100)
    assert len({id(s.timestamps) for s in g.signals}) == 1, (
        "fixture premise broken: master が凍結されておらず共有されていない"
    )
    read_once = srcs[0].array()  # 1 本だけ先に展開 (プロット済み信号の相当)
    assert srcs[0].reads == 1

    svc.enqueue("k", g)
    master_bytes = g.signals[0].timestamps.nbytes
    assert svc.pending_bytes() == master_bytes + read_once.nbytes

    # 会計は残り 49 本を展開していない (読みは上で作った 1 回のまま)
    assert [s.reads for s in srcs] == [1] + [0] * 49


def test_drain_does_not_materialize(qtbot) -> None:  # type: ignore[no-untyped-def]
    finished: list[str] = []
    svc = TeardownService(on_finished=finished.append)
    g, srcs = _lazy_group(50, 100)
    svc.enqueue("k", g)
    qtbot.waitUntil(lambda: finished == ["k"], timeout=3000)
    assert all(s.reads == 0 for s in srcs)  # drain で展開しない
