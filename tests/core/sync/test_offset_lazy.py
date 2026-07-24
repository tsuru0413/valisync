from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.sync.synchronizer import TimeSynchronizer

DEMO = Path("demo_data/quick_demo.mf4")
pytestmark = pytest.mark.skipif(not DEMO.exists(), reason="demo mf4 not generated")


def test_apply_offset_shares_lazy_source_no_materialize() -> None:
    sg = MdfLoader().load(DEMO, confirm_expansion=None).signal_group
    assert sg is not None
    base = sg.signals[0]
    shifted = TimeSynchronizer().apply_offset(base, file_offset=1.5)
    assert shifted._values_source is base._values_source
    assert base._values_source.is_materialized is False  # 展開しない
    np.testing.assert_allclose(shifted.timestamps, base.timestamps + 1.5)


def test_apply_offset_zero_returns_same_signal() -> None:
    sg = MdfLoader().load(DEMO, confirm_expansion=None).signal_group
    assert sg is not None
    base = sg.signals[0]
    assert TimeSynchronizer().apply_offset(base, 0.0, 0.0) is base
