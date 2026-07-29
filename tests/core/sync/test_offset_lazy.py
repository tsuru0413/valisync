from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.lazy_stubs import CountingLazy
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.models import Signal
from valisync.core.sync.synchronizer import TimeSynchronizer

DEMO = Path("demo_data/quick_demo.mf4")
# NOTE: module 全体の pytestmark にはしない — 下の CountingLazy 版は demo mf4 なしで
# CI でも走る必要がある (これが唯一の CI ガード)。実 mf4 依存のテストだけ個別に gate。
demo_only = pytest.mark.skipif(not DEMO.exists(), reason="demo mf4 not generated")


def _lazy_signal(length: int = 8) -> tuple[Signal, CountingLazy]:
    src = CountingLazy(length)
    sig = Signal(
        name="s",
        timestamps=np.arange(length, dtype=np.float64),
        values_source=src,  # type: ignore[arg-type]
        file_format="MDF4",
        bus_type="",
        source_file="/x.mf4",
    )
    return sig, src


def test_apply_offset_shares_lazy_source_without_reading() -> None:
    """offset 適用が遅延ソースを**共有**し、値を一切読まない (CI ガード).

    ``synchronizer.apply_offset`` の ``values_source=signal._values_source`` を
    ``values=signal.values`` に戻すと、全体オフセット (scope=group) の一回で
    ``GraphPanelVM._signal_map`` / ``session.unified_timeline`` が base map 全件に
    apply_offset を掛けるため **264k 信号が丸ごと eager 展開**され、増分の成果が
    静かに全消しになる。実 mf4 版 (下) は demo 依存で CI 非実行のため、この
    スタブ版が唯一の CI ガードになる。
    """
    base, src = _lazy_signal()
    shifted = TimeSynchronizer().apply_offset(base, file_offset=1.5)

    assert shifted is not base
    assert shifted._values_source is base._values_source  # ソース共有 (コピーでない)
    assert src.reads == 0, "offset 適用が値を展開した (遅延ソース共有が壊れている)"
    assert src.is_materialized is False
    np.testing.assert_allclose(shifted.timestamps, base.timestamps + 1.5)


def test_apply_offset_zero_shares_identity_without_reading() -> None:
    base, src = _lazy_signal()
    assert TimeSynchronizer().apply_offset(base, 0.0, 0.0) is base
    assert src.reads == 0


@demo_only
def test_apply_offset_shares_lazy_source_no_materialize() -> None:
    sg = MdfLoader().load(DEMO).signal_group
    assert sg is not None
    base = sg.signals[0]
    shifted = TimeSynchronizer().apply_offset(base, file_offset=1.5)
    assert shifted._values_source is base._values_source
    assert base._values_source.is_materialized is False  # 展開しない
    np.testing.assert_allclose(shifted.timestamps, base.timestamps + 1.5)


@demo_only
def test_apply_offset_zero_returns_same_signal() -> None:
    sg = MdfLoader().load(DEMO).signal_group
    assert sg is not None
    base = sg.signals[0]
    assert TimeSynchronizer().apply_offset(base, 0.0, 0.0) is base
