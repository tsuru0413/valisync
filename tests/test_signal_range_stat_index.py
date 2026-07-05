"""Signal.range_stat_index() の遅延キャッシュと delegate 共有。"""

from __future__ import annotations

import numpy as np

from valisync.core.models import Signal
from valisync.core.statistics import RangeStatIndex


def _sig(vs):
    ts = np.arange(len(vs), dtype=np.float64)
    return Signal(
        name="s",
        timestamps=ts,
        values=np.asarray(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
    )


def test_range_stat_index_is_cached():
    s = _sig([1.0, 2.0, 3.0, 4.0])
    idx = s.range_stat_index()
    assert isinstance(idx, RangeStatIndex)
    assert s.range_stat_index() is idx  # same object reused


def test_query_matches_compute_semantics():
    s = _sig([10.0, 20.0, 30.0])
    res = s.range_stat_index().query(0.0, 2.0)
    assert res.count == 3 and res.mean == 20.0


def test_wrapper_shares_delegate_index():
    base = _sig([1.0, 2.0, 3.0, 4.0])
    wrapper = _sig([1.0, 2.0, 3.0, 4.0])
    object.__setattr__(wrapper, "_sorted_view_delegate", base)
    assert wrapper.range_stat_index() is base.range_stat_index()
