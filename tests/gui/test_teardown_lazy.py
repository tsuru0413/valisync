from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from tests.lazy_stubs import CountingLazy
from valisync.core.models import Signal, SignalGroup
from valisync.gui.workers.teardown_service import TeardownService


def _lazy_group(n_signals: int, length: int) -> tuple[SignalGroup, list[CountingLazy]]:
    ts = np.arange(length, dtype=np.float64)
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


def test_pending_bytes_does_not_materialize(qtbot) -> None:  # type: ignore[no-untyped-def]
    svc = TeardownService()
    g, srcs = _lazy_group(50, 100)
    svc.enqueue("k", g)
    _ = svc.pending_bytes()
    assert all(s.reads == 0 for s in srcs)  # 会計で展開しない


def test_drain_does_not_materialize(qtbot) -> None:  # type: ignore[no-untyped-def]
    finished: list[str] = []
    svc = TeardownService(on_finished=finished.append)
    g, srcs = _lazy_group(50, 100)
    svc.enqueue("k", g)
    qtbot.waitUntil(lambda: finished == ["k"], timeout=3000)
    assert all(s.reads == 0 for s in srcs)  # drain で展開しない
