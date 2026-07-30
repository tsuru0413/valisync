from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import pytest

from tests.lazy_stubs import CountingLazy
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup

DEMO = Path("demo_data/quick_demo.mf4")
# NOTE: module 全体の pytestmark にはしない — CountingLazy 版は demo mf4 なしで
# CI でも走る必要がある (offset 側と同型の CI ガード)。
demo_only = pytest.mark.skipif(not DEMO.exists(), reason="demo mf4 not generated")


def test_namespaced_wrapper_shares_lazy_source_without_reading() -> None:
    """namespaced ラッパーが遅延ソースを共有し、値を読まない (CI ガード).

    ``signal_group_manager._namespaced`` の ``values_source=sig._values_source``
    を ``values=sig.values`` に戻すと、`signals()`/`signal_map()` を一度呼ぶだけで
    全ロード信号が eager 展開される。実 mf4 版 (下) は CI 非実行のため、
    スタブ版でここを直接ガードする。
    """
    src = CountingLazy(8)
    origin = Signal(
        name="s0",
        timestamps=np.arange(8, dtype=np.float64),
        values_source=src,  # type: ignore[arg-type]
        file_format="MDF4",
        bus_type="",
        source_file="/x.mf4",
    )
    mgr = SignalGroupManager()
    key = mgr.add(
        SignalGroup(
            signals=(origin,),
            source_path=Path("/x.mf4").resolve(),
            file_format="MDF4",
            loaded_at=datetime.datetime.now(),
        )
    )

    _ = mgr.signals()
    _ = mgr.signal_map()
    wrapper = mgr.group_signals(key)[0]

    assert wrapper._values_source is origin._values_source  # ソース共有
    assert src.reads == 0, "namespaced ラッパー構築が値を展開した"
    assert src.is_materialized is False


def _loaded_manager() -> tuple[SignalGroupManager, str]:
    sg = MdfLoader().load(DEMO).signal_group
    assert sg is not None
    mgr = SignalGroupManager()
    key = mgr.add(sg)
    return mgr, key


@demo_only
def test_group_signals_does_not_materialize() -> None:
    mgr, key = _loaded_manager()
    ns = mgr.group_signals(key)
    assert all(s._values_source.is_materialized is False for s in ns)


@demo_only
def test_signals_and_signal_map_do_not_materialize() -> None:
    mgr, _key = _loaded_manager()
    _ = mgr.signals()
    _ = mgr.signal_map()
    assert all(s._values_source.is_materialized is False for s in mgr.signals())


@demo_only
def test_wrapper_shares_origin_source_identity() -> None:
    sg = MdfLoader().load(DEMO).signal_group
    assert sg is not None
    mgr = SignalGroupManager()
    key = mgr.add(sg)
    origin = sg.signals[0]
    wrapper = next(
        w for w in mgr.group_signals(key) if w.name.endswith(f"::{origin.name}")
    )
    assert wrapper._values_source is origin._values_source
    # ラッパー経由の展開が共有ソースを 1 度だけ満たす
    _ = wrapper.values
    assert origin._values_source.is_materialized is True
