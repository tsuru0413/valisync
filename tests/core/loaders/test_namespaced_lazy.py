from __future__ import annotations

from pathlib import Path

import pytest

from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager

DEMO = Path("demo_data/quick_demo.mf4")
pytestmark = pytest.mark.skipif(not DEMO.exists(), reason="demo mf4 not generated")


def _loaded_manager() -> tuple[SignalGroupManager, str]:
    sg = MdfLoader().load(DEMO, confirm_expansion=None).signal_group
    assert sg is not None
    mgr = SignalGroupManager()
    key = mgr.add(sg)
    return mgr, key


def test_group_signals_does_not_materialize() -> None:
    mgr, key = _loaded_manager()
    ns = mgr.group_signals(key)
    assert all(s._values_source.is_materialized is False for s in ns)


def test_signals_and_signal_map_do_not_materialize() -> None:
    mgr, _key = _loaded_manager()
    _ = mgr.signals()
    _ = mgr.signal_map()
    assert all(s._values_source.is_materialized is False for s in mgr.signals())


def test_wrapper_shares_origin_source_identity() -> None:
    sg = MdfLoader().load(DEMO, confirm_expansion=None).signal_group
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
