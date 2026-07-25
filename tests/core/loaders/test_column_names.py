from __future__ import annotations

import numpy as np

from valisync.core.loaders.column_names import (
    leaf_count,
    leaf_names,
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
    ]
    for arr in cases:
        spec = spec_from_probe(arr)
        assert list(leaf_names("B", spec)) == _numeric_flatten_names("B", arr)
        assert leaf_count(spec) == len(_numeric_flatten_names("B", arr))
