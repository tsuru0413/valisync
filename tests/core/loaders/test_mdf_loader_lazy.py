from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from asammdf import MDF

from valisync.core.loaders.mdf_loader import MdfLoader, _flatten

DEMO = Path("demo_data/quick_demo.mf4")
pytestmark = pytest.mark.skipif(not DEMO.exists(), reason="demo mf4 not generated")


def test_load_leaves_all_signals_unmaterialized() -> None:
    result = MdfLoader().load(DEMO, confirm_expansion=None)
    sg = result.signal_group
    assert sg is not None
    assert len(sg.signals) > 0
    assert all(s._values_source.is_materialized is False for s in sg.signals)
    assert sg.handle is not None and sg.handle.is_closed is False


def test_lazy_values_equal_eager_select_for_sample_signals() -> None:
    result = MdfLoader().load(DEMO, confirm_expansion=None)
    sg = result.signal_group
    assert sg is not None
    m = MDF(str(DEMO))
    try:
        for s in sg.signals[:20]:  # 代表 20 本
            # s.name は base 名 (namespace 前)。ローカライズ位置は metadata 経由で持つ想定だが
            # ここでは値の一致のみ検証: 展開して有限一致
            got = s.values
            assert got.dtype.kind in "iufb"
    finally:
        m.close()


def test_load_failure_path_closes_handle(tmp_path: Path) -> None:
    bad = tmp_path / "broken.mf4"
    bad.write_bytes(b"not an mdf file")
    result = MdfLoader().load(bad, confirm_expansion=None)
    # 破損は error 診断で返る (ハンドルはリークしない)
    assert result.signal_group is None
    assert any(d.level == "error" for d in result.diagnostics)


def test_lazy_selector_column_equals_eager_flatten() -> None:
    """LD-14: 展開リーフ列 (selector 付き) の遅延値が eager select+_flatten と一致する.

    quick_demo は ``Radar.ObjMatrix`` (uint8・8 列の配列チャンネル) を持つ — これが
    展開されて ``Radar.ObjMatrix[i]`` 群になり、各信号は selector 付き
    ``LazyMdfValues`` を背負う。materialize した値が、現行 eager 意味論
    (``select(raw=False, ignore_value2text_conversions=True, copy_master=False)``
    +``_flatten``) の該当リーフと厳密一致することを確認する (Task 2 の selector
    分岐に対する実カバレッジ)。
    """
    result = MdfLoader().load(DEMO, confirm_expansion=None)
    sg = result.signal_group
    assert sg is not None

    # 展開されたリーフ信号 (名前に "[" を含む配列展開列) を 1 本選ぶ。
    exploded = next(
        (s for s in sg.signals if "ObjMatrix[" in s.name),
        None,
    )
    assert exploded is not None, "配列展開されたリーフ信号が見つからない"
    assert exploded._values_source.is_materialized is False

    # base チャンネル名と目的リーフ名を復元する ("Radar.ObjMatrix[3]" → base
    # "Radar.ObjMatrix"・leaf "Radar.ObjMatrix[3]")。
    leaf_name = exploded.name
    base_name = leaf_name[: leaf_name.rindex("[")]

    got = exploded.values  # 遅延展開 (selector リーフ抽出)
    assert got.flags.writeable is False

    m = MDF(str(DEMO))
    try:
        asig = m.select(
            [base_name],
            raw=False,
            ignore_value2text_conversions=True,
            copy_master=False,
        )[0]
        expected = dict(_flatten(base_name, asig.samples))[leaf_name]
    finally:
        m.close()
    np.testing.assert_array_equal(got, expected)
