from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from valisync.core.models import Signal, SignalGroup
from valisync.gui.workers.teardown_service import TeardownService


class _CountingLazy:
    """array() が呼ばれたら記録する遅延ソース (テスト用)."""

    def __init__(self, n: int) -> None:
        self._n = n
        self.reads = 0
        self._cache: np.ndarray | None = None

    @property
    def is_materialized(self) -> bool:
        return self._cache is not None

    @property
    def length(self) -> int:
        return self._n

    @property
    def nbytes_if_materialized(self) -> int:
        return 0 if self._cache is None else self._cache.nbytes

    def array(self) -> np.ndarray:
        self.reads += 1
        self._cache = np.zeros(self._n, dtype=np.float64)
        return self._cache


def _lazy_group(n_signals: int, length: int) -> tuple[SignalGroup, list[_CountingLazy]]:
    ts = np.arange(length, dtype=np.float64)
    srcs = [_CountingLazy(length) for _ in range(n_signals)]
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
