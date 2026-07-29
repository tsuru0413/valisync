from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from asammdf import MDF

from valisync.core.loaders.mdf_loader import MdfLoader, _flatten
from valisync.core.session import Session

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
    """遅延読みした値が現行 eager 意味論の select と厳密一致する (増分の中核契約).

    ``LazyMdfValues.array()`` の select オプションが一つでもずれると値が無言で
    壊れる — 特に ``raw=True`` は数値変換 (factor/offset) を捨てた生カウントを返し、
    quick_demo の線形変換チャンネル (group 3/4・conversion_type==1) では 100 倍
    ずれる。よってこのテストは**変換つきチャンネルを必ず含む**こと自体を
    assert する (変換なしチャンネルだけでは同じ flip に対して盲目になる)。

    アドレス (base 名/gi/ci/selector) は production が信号に持たせた
    ``LazyMdfValues`` から取り、**値の読み方**だけを eager select と突き合わせる。
    """
    result = MdfLoader().load(DEMO, confirm_expansion=None)
    sg = result.signal_group
    assert sg is not None

    # 仮想グループごとに代表を拾う — 先頭 N 本だけだと group 0 に偏り、変換つき
    # チャンネル (group 3/4) を一本も踏まない。
    by_group: dict[int, list[Any]] = {}
    for s in sg.signals:
        by_group.setdefault(s._values_source._gi, []).append(s)  # type: ignore[union-attr]
    sampled = [s for sigs in by_group.values() for s in sigs[:4]]
    assert len(sampled) >= 20, f"代表サンプルが少なすぎる ({len(sampled)} 本)"

    m = MDF(str(DEMO))
    converted = 0
    try:
        for s in sampled:
            src = s._values_source
            base_name, gi, ci = src._name, src._gi, src._ci
            selector = src._selector
            # アドレスが信号名に対応していること (曖昧化 [idx]・展開 [i] を許容)
            assert s.name == base_name or s.name.startswith(f"{base_name}[")

            asig = m.select(
                [(base_name, gi, ci)],
                raw=False,
                ignore_value2text_conversions=True,
                copy_master=False,
            )[0]
            expected = (
                dict(_flatten(base_name, asig.samples))[selector[-1]]
                if selector is not None
                else asig.samples
            )
            np.testing.assert_array_equal(
                s.values, expected, err_msg=f"遅延値が eager select と不一致: {s.name}"
            )
            if m.groups[gi].channels[ci].conversion is not None:
                converted += 1
    finally:
        m.close()

    assert converted > 0, (
        "変換つきチャンネルを一本も検証していない — raw=True 化による "
        "値スケール破壊に対してこのテストが盲目になる"
    )


def test_group_master_equals_get_master() -> None:
    """遅延ローダーの master が ``MDF.get_master(gi)`` と厳密一致する.

    master は ``get_master`` が開いたハンドルにグループの生レコードブロック全体を
    キャッシュする (prod_demo で +1,296MB) ため select 経由で読むよう変えた —
    取得経路を変えても値/長さ/dtype が寸分違わないことをここで固定する。診断
    (非有限・非単調・重複) も長さ (``LazyMdfValues.length``) もこの配列が土台。

    仮想グループごとに、そのグループ由来の信号が持つ timestamps (グループ内で
    共有される同一オブジェクト) を ``get_master(gi)`` と突き合わせる。
    """
    loader = MdfLoader()
    result = loader.load(DEMO, confirm_expansion=None)
    sg = result.signal_group
    assert sg is not None

    m = MDF(str(DEMO), time_from_zero=False)
    try:
        # 信号名 → 属する仮想グループ。ローダーと同じ entries 走査で対応付ける
        # (曖昧化 [idx]・展開 [i] があるため base 名の前方一致で解決する)。
        checked = 0
        for gi in m.virtual_groups:
            entries = loader._group_entries(m, gi)
            if not entries:
                continue
            base_names = {name for name, _g, _c in entries}
            produced = next(
                (
                    s
                    for s in sg.signals
                    if any(
                        s.name == b or s.name.startswith(f"{b}[") for b in base_names
                    )
                ),
                None,
            )
            if produced is None:
                continue  # 全チャンネルが skip された (非数値/展開上限超) グループ
            expected = m.get_master(gi)
            got = produced.timestamps
            assert got.dtype == np.float64
            assert len(got) == len(expected)
            np.testing.assert_array_equal(got, expected)
            checked += 1
        assert checked > 0, "検証できた仮想グループが 0 (テストが空回りしている)"
    finally:
        m.close()


def test_unparsable_file_returns_error_diagnostic_without_group(tmp_path: Path) -> None:
    """``MDF()`` 自体が失敗する経路は error 診断 + signal_group=None で返る。

    **名前を実体に合わせた (旧 test_load_failure_path_closes_handle)**: この経路
    (mdf_loader.py の ``except`` — 「ハンドル未生成のためリークなし」) では
    MdfHandle がまだ 1 個も作られておらず、このテストもハンドルを一切見ていない。
    ハンドル寿命の名前を着ていた分、旧名は「close 経路が守られている」という
    誤った安心を与えていた (実際には ``handle.close()`` を全部消しても緑)。

    ハンドル寿命の契約は **demo 非依存で CI 実行される** 以下が所有する:
      - ``tests/test_loaders.py::test_load_error_path_closes_handle_no_leak``
        (ハンドル生成後の本読み失敗 → close)
      - ``tests/test_loaders.py::test_mdf_loader_cancel_raises`` /
        ``::test_mdf_loader_cancel_during_group_load_closes_handle`` (キャンセル経路)
      - ``tests/core/test_handle_release.py`` (unload 経路)
    """
    bad = tmp_path / "broken.mf4"
    bad.write_bytes(b"not an mdf file")
    result = MdfLoader().load(bad, confirm_expansion=None)
    assert result.signal_group is None
    assert any(d.level == "error" for d in result.diagnostics)


def test_lazy_selector_column_equals_eager_flatten() -> None:
    """LD-14: 鋳造列 (selector 付き) の遅延値が eager select+_flatten と一致する.

    E-3 反転後、展開列は SignalGroup に居ない — ColumnRecord からの鋳造が
    selector 分岐の production 経路になった。quick_demo の Radar.ObjMatrix
    (uint8・8 列) をその実カバレッジに使う。
    """
    session = Session()
    key = session.load(DEMO, confirm_expansion=None).key
    base_name = "Radar.ObjMatrix"
    leaf_name = f"{base_name}[3]"
    col = session.resolve_signal(f"{key}::{leaf_name}")
    assert col is not None, "配列列が鋳造できない"
    assert col._values_source.is_materialized is False

    got = col.values  # 遅延展開 (selector リーフ抽出)
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
