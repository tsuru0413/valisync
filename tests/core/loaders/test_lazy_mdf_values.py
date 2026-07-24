from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest
from asammdf import MDF

from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.models.sample_source import LazyMdfValues, SampleReadError

DEMO = Path("demo_data/quick_demo.mf4")
pytestmark = pytest.mark.skipif(not DEMO.exists(), reason="demo mf4 not generated")


def test_mdf_handle_close_is_idempotent() -> None:
    h = MdfHandle(MDF(str(DEMO)))
    assert h.is_closed is False
    h.close()
    assert h.is_closed is True
    h.close()  # 多重 close 安全
    assert h.is_closed is True


def test_mdf_handle_has_lock() -> None:
    h = MdfHandle(MDF(str(DEMO)))
    assert isinstance(h.lock, type(threading.Lock()))
    h.close()


def _eager_samples(name: str, gi: int, ci: int) -> np.ndarray:
    # 現行ローダーと同一意味論の eager 読み (変換適用・value2text スキップ)
    m = MDF(str(DEMO))
    try:
        sig = m.select(
            [(name, gi, ci)],
            raw=False,
            ignore_value2text_conversions=True,
            copy_master=False,
        )[0]
        return np.ascontiguousarray(sig.samples)
    finally:
        m.close()


def _first_scalar_channel() -> tuple[str, int, int, int]:
    # 1D 数値チャンネルを 1 本見つける (name, gi, ci, length)
    m = MDF(str(DEMO))
    try:
        for gi, g in enumerate(m.groups):
            master_ci = m.masters_db.get(gi)
            for ci, ch in enumerate(g.channels):
                if ci == master_ci:
                    continue
                probe = m.get(group=gi, index=ci, samples_only=True, raw=True)[0]
                if probe.ndim == 1 and probe.dtype.kind in "iufb":
                    return ch.name, gi, ci, g.channel_group.cycles_nr
        raise AssertionError("no scalar channel found")
    finally:
        m.close()


def test_lazy_is_not_materialized_until_array_called() -> None:
    name, gi, ci, length = _first_scalar_channel()
    h = MdfHandle(MDF(str(DEMO)))
    src = LazyMdfValues(h, name, gi, ci, length=length)
    assert src.is_materialized is False
    assert src.length == length
    assert src.nbytes_if_materialized == 0
    got = src.array()
    assert src.is_materialized is True
    assert src.nbytes_if_materialized == got.nbytes
    assert src.array() is got  # キャッシュ (再読みしない)
    h.close()


def test_lazy_values_match_eager_scaled_values() -> None:
    name, gi, ci, length = _first_scalar_channel()
    h = MdfHandle(MDF(str(DEMO)))
    got = LazyMdfValues(h, name, gi, ci, length=length).array()
    np.testing.assert_array_equal(got, _eager_samples(name, gi, ci))
    assert got.flags.writeable is False
    h.close()


def test_lazy_read_failure_raises_sample_read_error() -> None:
    name, gi, ci, length = _first_scalar_channel()
    h = MdfHandle(MDF(str(DEMO)))
    h.mdf = None  # 読み時に AttributeError -> SampleReadError へ変換される
    with pytest.raises(SampleReadError):
        LazyMdfValues(h, name, gi, ci, length=length).array()


def test_lazy_reads_are_serialized_by_handle_lock() -> None:
    # 同一ハンドルへの並行 array() が select を直列化することを、再入で失敗する
    # スタブで検証する。
    name, gi, ci, length = _first_scalar_channel()
    h = MdfHandle(MDF(str(DEMO)))
    real_select = h.mdf.select
    active = {"in": False}
    reentered = {"hit": False}

    def guarded_select(*a, **k):  # type: ignore[no-untyped-def]
        if active["in"]:
            reentered["hit"] = True
        active["in"] = True
        try:
            return real_select(*a, **k)
        finally:
            active["in"] = False

    h.mdf.select = guarded_select  # type: ignore[assignment]
    srcs = [LazyMdfValues(h, name, gi, ci, length=length) for _ in range(8)]
    threads = [threading.Thread(target=s.array) for s in srcs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert reentered["hit"] is False  # lock で直列化され再入なし
    h.close()
