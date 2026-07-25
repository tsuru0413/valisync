from __future__ import annotations

import numpy as np

from valisync.core.loaders.column_names import (
    ColumnSpec,
    leaf_count,
    leaf_names,
    parse_leaf,
    spec_from_probe,
)
from valisync.core.loaders.mdf_loader import _flatten


def test_scalar_channel_has_single_leaf() -> None:
    spec = spec_from_probe(np.zeros(1, dtype=np.float64))
    assert spec.kind == "leaf"
    assert list(leaf_names("Spd", spec)) == ["Spd"]
    assert leaf_count(spec) == 1


def test_2d_channel_expands_per_column() -> None:
    spec = spec_from_probe(np.zeros((1, 3), dtype=np.uint8))
    assert list(leaf_names("Mat", spec)) == ["Mat[0]", "Mat[1]", "Mat[2]"]
    assert leaf_count(spec) == 3


def test_3d_channel_peels_axes_left_to_right() -> None:
    spec = spec_from_probe(np.zeros((1, 2, 2), dtype=np.int16))
    assert list(leaf_names("M", spec)) == ["M[0][0]", "M[0][1]", "M[1][0]", "M[1][1]"]
    assert leaf_count(spec) == 4


def test_structured_channel_uses_field_names() -> None:
    arr = np.zeros(1, dtype=[("x", "<f8"), ("y", "<f8")])
    spec = spec_from_probe(arr)
    assert list(leaf_names("P", spec)) == ["P.x", "P.y"]


def test_structured_field_names_may_contain_dots() -> None:
    # asammdf のフィールド名はチャンネル名そのもので '.' を含む (Critical 2)
    arr = np.zeros(1, dtype=[("Radar.ObjList", "<u1"), ("Radar.ObjList.dx", "<f8")])
    spec = spec_from_probe(arr)
    assert list(leaf_names("Radar.ObjList", spec)) == [
        "Radar.ObjList.Radar.ObjList",
        "Radar.ObjList.Radar.ObjList.dx",
    ]


def test_non_numeric_leaves_are_excluded() -> None:
    # 非数値リーフは Signal を作れないので列キー空間から外す (LD-12 と整合)
    arr = np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")])
    spec = spec_from_probe(arr)
    assert list(leaf_names("C", spec)) == ["C.ok"]
    assert leaf_count(spec) == 1


def test_struct_of_array_composes() -> None:
    arr = np.zeros(1, dtype=[("v", "<f8", (2,))])
    spec = spec_from_probe(arr)
    assert list(leaf_names("S", spec)) == ["S.v[0]", "S.v[1]"]


def test_zero_width_axis_expands_to_no_leaves() -> None:
    # 0 幅の非サンプル軸は展開不能列 (LD-14) — _flatten は range(0) が空で
    # 自然に [] を返す。spec_from_probe は arr[:, 0] で IndexError にならず
    # 同じく空を返さなければならない。
    spec = spec_from_probe(np.zeros((1, 0), dtype=np.float64))
    assert list(leaf_names("Z", spec)) == []
    assert leaf_count(spec) == 0


def test_zero_width_axis_inside_struct_field_expands_to_no_leaves() -> None:
    arr = np.zeros(1, dtype=[("ok", "<f8"), ("empty", "<f8", (0,))])
    spec = spec_from_probe(arr)
    assert list(leaf_names("S", spec)) == ["S.ok"]
    assert leaf_count(spec) == 1


def _numeric_flatten_names(base: str, arr: np.ndarray) -> list[str]:
    # _flatten は dtype 盲目なので、比較のため数値リーフだけに絞る
    return [n for n, col in _flatten(base, arr) if col.dtype.kind in "iufb"]


def test_leaf_names_order_matches_flatten() -> None:
    cases = [
        np.zeros(1, dtype=np.float64),
        np.zeros((1, 3), dtype=np.uint8),
        np.zeros((1, 2, 2), dtype=np.int16),
        np.zeros(1, dtype=[("x", "<f8"), ("y", "<f8")]),
        np.zeros(1, dtype=[("v", "<f8", (2,))]),
        np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")]),
        np.zeros(1, dtype=[("Radar.ObjList", "<u1"), ("Radar.ObjList.dx", "<f8")]),
        np.zeros((1, 0), dtype=np.float64),
    ]
    for arr in cases:
        spec = spec_from_probe(arr)
        assert list(leaf_names("B", spec)) == _numeric_flatten_names("B", arr)
        assert leaf_count(spec) == len(_numeric_flatten_names("B", arr))


def _specs(*pairs: tuple[str, np.ndarray]) -> dict[str, ColumnSpec]:
    return {name: spec_from_probe(arr) for name, arr in pairs}


def test_parse_leaf_round_trips_every_generated_name() -> None:
    cases = {
        "Spd": np.zeros(1, dtype=np.float64),
        "Mat": np.zeros((1, 3), dtype=np.uint8),
        "M": np.zeros((1, 2, 2), dtype=np.int16),
        "P": np.zeros(1, dtype=[("x", "<f8"), ("y", "<f8")]),
        "Radar.ObjList": np.zeros(
            1, dtype=[("Radar.ObjList", "<u1"), ("Radar.ObjList.dx", "<f8")]
        ),
    }
    specs = {n: spec_from_probe(a) for n, a in cases.items()}
    for base, spec in specs.items():
        names = list(leaf_names(base, spec))
        # generator must not alias two columns
        assert len(set(names)) == len(names), names
        for name in names:
            got = parse_leaf(name, specs)
            assert got is not None, name
            assert got[0] == base, name


def test_parse_leaf_prefers_the_real_channel_on_collision() -> None:
    # 2D の Mat の第0列と、"Mat[0]" という名前の 1D チャンネルが衝突する
    specs = _specs(
        ("Mat", np.zeros((1, 2), dtype=np.uint8)),
        ("Mat[0]", np.zeros(1, dtype=np.float64)),
    )
    got = parse_leaf("Mat[0]", specs)
    assert got is not None
    assert got[0] == "Mat[0]"  # 最長一致 = 実チャンネルが勝つ


def test_parse_leaf_returns_none_for_unknown_base_or_bad_index() -> None:
    specs = _specs(("Mat", np.zeros((1, 2), dtype=np.uint8)))
    assert parse_leaf("Nope[0]", specs) is None
    assert parse_leaf("Mat[9]", specs) is None  # 範囲外
    assert parse_leaf("Mat", specs) is None  # 親そのものは列ではない
    assert parse_leaf("Mat[0]x", specs) is None  # 残余を消費しきれない


def test_parse_leaf_rejects_non_ascii_digit_index_instead_of_raising() -> None:
    # '²' (上付き2) は str.isdigit() で True だが int() は ValueError を投げる。
    # 解決失敗は必ず None を返す契約 (例外を漏らしてはならない)。
    specs = _specs(("Mat", np.zeros((1, 2), dtype=np.uint8)))
    assert parse_leaf("Mat[²]", specs) is None


def test_parse_leaf_rejects_non_numeric_leaf() -> None:
    specs = _specs(("C", np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")])))
    assert parse_leaf("C.ok", specs) is not None
    assert parse_leaf("C.txt", specs) is None  # 非数値は列キー空間に無い
