"""RangeStatIndex — 平方分割インデックスの範囲統計が numpy 直接計算と一致する証明的検証。

設計 spec §4.2 の命題1-6 を、finite_view 上のランダム範囲クエリで実証する。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from valisync.core.statistics.range_stat_index import RangeStatIndex

from .conftest import valid_signals

pytestmark = pytest.mark.property


def _reference(vs_range: np.ndarray) -> tuple[float, float, float, float, int]:
    n = len(vs_range)
    if n == 0:
        nan = float("nan")
        return nan, nan, nan, nan, 0
    return (
        float(np.mean(vs_range)),
        float(np.max(vs_range)),
        float(np.min(vs_range)),
        float(np.std(vs_range, ddof=0)),
        n,
    )


@given(
    valid_signals(allow_nan_values=True),
    st.floats(min_value=0.0, max_value=1.0),
    st.floats(min_value=0.0, max_value=1.0),
)
def test_index_matches_numpy_on_finite_view(signal, f1, f2):
    ts, vs = signal.finite_view()  # finite・昇順(命題1の前提)
    span = float(ts[-1] - ts[0]) if len(ts) else 1.0
    pad = span * 0.1 + 1.0
    lo = (float(ts[0]) if len(ts) else 0.0) - pad
    hi = (float(ts[-1]) if len(ts) else 0.0) + pad
    a = lo + f1 * (hi - lo)
    b = lo + f2 * (hi - lo)
    t_start, t_end = (a, b) if a <= b else (b, a)

    res = RangeStatIndex(ts, vs).query(t_start, t_end)

    in_range = vs[(ts >= t_start) & (ts <= t_end)]
    r_mean, r_max, r_min, r_std, r_count = _reference(in_range)
    assert res.count == r_count
    if r_count == 0:
        assert math.isnan(res.mean) and math.isnan(res.std)
        assert math.isnan(res.max) and math.isnan(res.min)
    else:
        # 絶対許容はデータスケールに比例させる。ほぼ定数・大平均のとき真の std は
        # ~0 だが float64 の丸めで numpy 二段パスも並列マージも |mean|·eps 程度の
        # ノイズフロアに乗る(どちらも真値ではない)。その床を超えて一致を要求すると
        # 本質的でない不一致で落ちるため、床 = C·scale·eps で吸収する(実バグは
        # これより桁違いに大きい相対誤差を出す)。
        scale = max(1.0, abs(r_mean), abs(r_max), abs(r_min))
        noise = 256.0 * scale * float(np.finfo(np.float64).eps)
        assert res.mean == pytest.approx(r_mean, rel=1e-9, abs=noise)
        assert res.std == pytest.approx(r_std, rel=1e-9, abs=noise)
        assert res.max == r_max
        assert res.min == r_min


def test_empty_signal_query_is_nan():
    idx = RangeStatIndex(np.array([], dtype=np.float64), np.array([], dtype=np.float64))
    res = idx.query(0.0, 1.0)
    assert res.count == 0 and math.isnan(res.mean) and math.isnan(res.std)


def test_single_sample():
    idx = RangeStatIndex(np.array([1.0]), np.array([5.0]))
    res = idx.query(0.0, 2.0)
    assert res.count == 1
    assert res.mean == 5.0 and res.min == 5.0 and res.max == 5.0 and res.std == 0.0


def test_constant_signal_std_is_zero():
    ts = np.arange(1000, dtype=np.float64)
    vs = np.full(1000, 7.0, dtype=np.float64)
    res = RangeStatIndex(ts, vs).query(0.0, 999.0)
    assert res.count == 1000 and res.mean == 7.0 and res.std == 0.0
    assert res.min == 7.0 and res.max == 7.0


def test_large_mean_small_variance_no_cancellation():
    # 大平均・小分散: 素朴な Sum(v^2)-Sum(v)^2/n はキャンセルで壊れるが並列マージは安定。
    rng = np.random.default_rng(0)
    ts = np.arange(5000, dtype=np.float64)
    vs = 1e8 + rng.normal(0.0, 1e-3, 5000)
    res = RangeStatIndex(ts, vs).query(0.0, 4999.0)
    assert res.std == pytest.approx(float(np.std(vs, ddof=0)), rel=1e-6, abs=1e-9)


def test_range_on_block_boundaries():
    # n=10000 → block≈100。ちょうどブロック境界に一致/跨ぐ範囲で完全ブロック経路を突く。
    ts = np.arange(10000, dtype=np.float64)
    vs = np.sin(ts * 0.01).astype(np.float64)
    idx = RangeStatIndex(ts, vs)
    for a, b in [(0.0, 9999.0), (100.0, 200.0), (150.0, 850.0), (99.0, 101.0)]:
        res = idx.query(a, b)
        in_range = vs[(ts >= a) & (ts <= b)]
        assert res.count == len(in_range)
        assert res.mean == pytest.approx(float(np.mean(in_range)), rel=1e-9, abs=1e-12)
        assert res.std == pytest.approx(
            float(np.std(in_range, ddof=0)), rel=1e-9, abs=1e-12
        )
        assert res.min == float(np.min(in_range))
        assert res.max == float(np.max(in_range))
