from __future__ import annotations

import numpy as np

from valisync.core.loaders.column_names import (
    ColumnPath,
    ColumnSpec,
    apply_path,
    leaf_count,
    leaf_names,
    leaf_paths,
    parse_leaf,
    spec_from_probe,
)
from valisync.core.loaders.mdf_loader import _all_leaf_count, _flatten


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


def test_all_leaf_count_counts_all_leaves_including_non_numeric() -> None:
    # _all_leaf_count は「N 本に展開」info 診断の母数で dtype 盲目 (全リーフを数える)。
    # leaf_count (数値のみ) とは意図的に別物である。
    arr = np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")])
    assert _all_leaf_count(spec_from_probe(arr)) == 2
    assert leaf_count(spec_from_probe(arr)) == 1


def test_leaf_paths_walk_all_leaves_in_flatten_order() -> None:
    """``leaf_paths`` は ``_flatten`` と同じ**全リーフ**空間・同じ順序 (数値だけではない)。

    ``test_leaf_names_order_matches_flatten`` と同じ case リストを使うのが要点 —
    非数値を含むケースで両者は**意図的にずれる** (spec §5.6)。パスから数値列を
    得るときは経路ではなく**引いた配列の dtype** で判定する。

    ``base is None`` を全ケースで見るのは、1 サンプルの合成配列ではどの
    リーフスライスも自明に連続 = view になり (実測)、copy を外すと全ケースが
    赤くなるため — 実 mf4 側 (4 サンプル) では view になるリーフが 2 本しか
    無いので、合成側は独立した第 2 の検出器になる。
    """
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
        walked = list(leaf_paths(spec))
        assert ["B" + suffix for suffix, _p in walked] == [
            name for name, _c in _flatten("B", arr)
        ], arr.dtype
        for suffix, path in walked:
            got = apply_path(arr, path)
            np.testing.assert_array_equal(got, dict(_flatten("B", arr))["B" + suffix])
            assert got.base is None, (arr.dtype, suffix)
        numeric = [
            "B" + suffix
            for suffix, path in walked
            if apply_path(arr, path).dtype.kind in "iufb"
        ]
        assert numeric == list(leaf_names("B", spec)), arr.dtype

    # 反 vacuous: 非数値を含むケースで 2 つの空間が実際にずれている
    mixed = spec_from_probe(np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")]))
    assert len(list(leaf_paths(mixed))) == 2
    assert len(list(leaf_names("B", mixed))) == 1


def test_apply_path_peels_the_non_sample_axis() -> None:
    """整数 step は**軸 1** (非サンプル軸) を剥がす — 軸 0 はサンプル軸である。

    ``samples[i]`` へ取り違えると「1 サンプル分の横断面」が返る。長さが変わるので
    ``LazyMdfValues`` の長さ検証が拾える形もあるが、行数と列数がたまたま等しい
    チャンネルでは黙って別データになる (例外の出ない誤波形)。
    """
    arr = np.array(
        [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]], dtype=np.uint8
    )
    out = apply_path(arr, ColumnPath((1,)))
    np.testing.assert_array_equal(out, [1, 11, 21, 31])
    assert len(out) == len(arr)  # サンプル数 4 (列数 3 ではない)


def test_nested_array_path_steps_are_indices_in_peel_order() -> None:
    """``Name[i][j]`` は asammdf の public write API で往復できない (既存の記録と同根)。

    多段配列の経路だけは合成 ndarray で固定する — 実データで裏取りできていない
    事実として明示する (``test_column_roundtrip`` の
    ``test_nested_index_arm_is_synthetic_because_asammdf_flattens_subarrays`` と同じ扱い)。
    """
    arr = np.zeros((4, 2, 3), dtype=np.uint8)
    for k in range(4):
        arr[k] = np.arange(6, dtype=np.uint8).reshape(2, 3) + 10 * k
    walked = list(leaf_paths(spec_from_probe(arr)))
    assert [(suffix, path.steps) for suffix, path in walked] == [
        (f"[{i}][{j}]", (i, j)) for i in range(2) for j in range(3)
    ]
    # 値も剥がし順どおり (arr[:, 1][:, 2] = 5 + 10k) — サンプル軸の取り違えも落ちる
    np.testing.assert_array_equal(apply_path(arr, ColumnPath((1, 2))), [5, 15, 25, 35])
