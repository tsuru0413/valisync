"""Signal.sorted_view — 記録どおり保持+整列ビュー(spec §4.1)の単体テスト."""

from __future__ import annotations

import numpy as np
import pytest

from valisync.core.models import Signal


def _sig(ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        name="s",
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def test_non_monotonic_signal_is_accepted():
    sig = _sig([0.0, 2.0, 1.0], [10.0, 20.0, 30.0])  # 旧実装では ValueError
    assert len(sig.timestamps) == 3


def test_sorted_view_sorts_and_is_strictly_monotonic():
    sig = _sig([0.0, 2.0, 1.0], [10.0, 20.0, 30.0])
    ts, vs = sig.sorted_view()
    assert ts.tolist() == [0.0, 1.0, 2.0]
    assert vs.tolist() == [10.0, 30.0, 20.0]
    assert np.all(np.diff(ts) > 0)


def test_sorted_view_keep_last_on_duplicates():
    # 同一タイムスタンプは記録順で最後の値が残る(CAN 後勝ち・spec §3-3)
    sig = _sig([0.0, 1.0, 1.0, 2.0], [1.0, 2.0, 3.0, 4.0])
    ts, vs = sig.sorted_view()
    assert ts.tolist() == [0.0, 1.0, 2.0]
    assert vs.tolist() == [1.0, 3.0, 4.0]


def test_sorted_view_fast_path_returns_raw_arrays():
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    ts, vs = sig.sorted_view()
    assert ts is sig.timestamps  # zero-copy(参照同一・is 比較)
    assert vs is sig.values
    assert sig.is_monotonic


def test_sorted_view_cached_and_raw_unchanged():
    raw_ts = [0.0, 2.0, 1.0]
    sig = _sig(raw_ts, [1.0, 2.0, 3.0])
    first = sig.sorted_view()
    assert sig.sorted_view()[0] is first[0]  # キャッシュ(再計算しない)
    assert sig.timestamps.tolist() == raw_ts  # 生データ無改変
    assert not sig.is_monotonic


def test_sorted_view_len0_and_len1():
    assert _sig([], []).sorted_view()[0].tolist() == []
    assert _sig([5.0], [1.0]).sorted_view()[0].tolist() == [5.0]
    assert _sig([], []).is_monotonic


def test_all_identical_timestamps_collapse_to_one():
    sig = _sig([1.0, 1.0, 1.0], [7.0, 8.0, 9.0])
    ts, vs = sig.sorted_view()
    assert ts.tolist() == [1.0]
    assert vs.tolist() == [9.0]  # keep-last


def test_non_finite_timestamps_still_rejected():
    with pytest.raises(ValueError, match="non-finite"):
        _sig([0.0, float("nan")], [1.0, 2.0])


def test_sorted_view_arrays_are_readonly():
    ts, vs = _sig([0.0, 2.0, 1.0], [1.0, 2.0, 3.0]).sorted_view()
    assert not ts.flags.writeable
    assert not vs.flags.writeable


# ─── finite_view (AN-01/02/03 共通土台) ──────────────────────────────────────


def test_finite_view_all_finite_is_zero_copy() -> None:
    """全値有限なら sorted_view の配列をそのまま返す (zero-copy)."""
    sig = _sig([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    sv = sig.sorted_view()
    fv = sig.finite_view()
    assert fv[0] is sv[0] and fv[1] is sv[1]


def test_finite_view_drops_nan_and_inf() -> None:
    """NaN/Inf の値を持つサンプルを除去し時刻と値が対応する."""
    sig = _sig([0.0, 1.0, 2.0, 3.0], [1.0, np.nan, np.inf, 4.0])
    ts, vs = sig.finite_view()
    assert ts.tolist() == [0.0, 3.0]
    assert vs.tolist() == [1.0, 4.0]


def test_finite_view_all_non_finite_is_empty() -> None:
    """全値が非有限なら空ビュー."""
    ts, vs = _sig([0.0, 1.0], [np.nan, np.inf]).finite_view()
    assert ts.tolist() == [] and vs.tolist() == []


def test_finite_view_cached() -> None:
    """2 回目の呼び出しは同一オブジェクト (キャッシュ)."""
    sig = _sig([0.0, 1.0], [np.nan, 2.0])
    first = sig.finite_view()
    assert sig.finite_view()[0] is first[0]


def test_finite_view_readonly_when_filtered() -> None:
    """フィルタ発生時の配列は read-only."""
    ts, vs = _sig([0.0, 1.0], [np.nan, 2.0]).finite_view()
    assert not ts.flags.writeable and not vs.flags.writeable


def test_finite_view_delegate_shared_with_namespaced_wrapper() -> None:
    """_sorted_view_delegate を持つラッパーは元 Signal の finite_view を共有."""
    orig = _sig([0.0, 1.0, 2.0], [1.0, np.nan, 3.0])
    wrapper = _sig([0.0, 1.0, 2.0], [1.0, np.nan, 3.0])
    object.__setattr__(wrapper, "_sorted_view_delegate", orig)
    assert wrapper.finite_view()[0] is orig.finite_view()[0]
