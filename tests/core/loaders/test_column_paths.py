"""位置パス (ColumnPath) と LD-14 列名文法の同一性を実 mf4 で固定する (E-4a T1)。

T2 が読み経路をキャッシュ + 位置パスへ移すと ``LazyMdfValues.array()`` は
``_flatten`` を呼ばなくなる。すると ``test_column_roundtrip.py`` が独立オラクルの
根拠にしていた「``_flatten`` は反転後も production が使い続ける」という論拠が失われ、
全数ラウンドトリップは**誰も使わない関数と解決器を突き合わせる**形になる。

本モジュールがその橋渡しである — ``leaf_paths`` の走査が ``_flatten`` の出力と
**順序込み・値込み**で一致することを実データで pin する。``_flatten`` と読み経路を
繋ぎ止める唯一の紐なので、削除・弱体化してはならない。

**所有権 (spec §5.4)**: ``apply_path`` は必ず ``base`` を持たない配列を返す。共有
キャッシュのスライスが view のまま ``LazyMdfValues._cache`` へ焼き付くと、evict しても
RSS が下がらず ``nbytes_if_materialized`` が実体の 1/1000 を返す。**値一致の検証は
view でも全部通る** (実測: copy を外しても本モジュールの値比較 26 リーフは全て緑) ため、
所有権は独立の assert でしか捕まらない。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from asammdf import MDF
from asammdf import Signal as ASignal

from tests.mdf4_helpers import (
    write_mdf4_2d,
    write_mdf4_all_non_numeric_struct,
    write_mdf4_single_column_shapes,
    write_mdf4_structured,
)
from valisync.core.loaders.column_names import (
    ColumnPath,
    apply_path,
    leaf_names,
    leaf_paths,
    spec_from_probe,
)
from valisync.core.loaders.mdf_loader import _flatten

_ARRAY_CHANNEL = "Radar.ObjList"  # フィールド名が '.' を含む CABLOCK 配列チャンネル
_AXIS_LEN = 3
# 遅延読み (LazyMdfValues.array()) と同一の正準オプション。オラクルが production と
# 別の側 (raw=True 等) を読むと「両方同じだけ壊れている」を見逃す。
_SELECT_OPTIONS: dict[str, Any] = {
    "raw": False,
    "ignore_value2text_conversions": True,
    "copy_master": False,
}


def _write_nested_array_mf4(tmp_path: Path) -> Path:
    """構造化 × 配列の入れ子を持つ CABLOCK 配列チャンネルを 1 本書く。

    ``tests/mdf4_helpers`` の既存 fixture はすべて struct か array の**片方**しか
    持たない。両方が入れ子になって初めて経路が (フィールド名 str, 添字 int) の
    混在列になり、「整数序数では位置を表現できない」(spec §5.6) が実データで見える。
    サブ配列付きフィールドで渡すのが要点 — スカラーフィールドの構造化 Signal だと
    asammdf は別表現に落とし、このハザードを再現しない。
    """  # noqa: RUF002 — 乗算記号は設計 spec §5.6 と同じ字面を保つため意図的
    n = 4
    ts = np.arange(n, dtype=np.float64)
    dtype = np.dtype(
        [
            (_ARRAY_CHANNEL, "<u1", (_AXIS_LEN,)),
            (f"{_ARRAY_CHANNEL}.dx", "<f8", (_AXIS_LEN,)),
        ]
    )
    samples = np.zeros(n, dtype=dtype)
    for k in range(n):
        for i in range(_AXIS_LEN):
            samples[_ARRAY_CHANNEL][k, i] = 10 * k + i + 1
            samples[f"{_ARRAY_CHANNEL}.dx"][k, i] = 100 * (i + 1) + k
    out = tmp_path / "nested_array.mf4"
    with MDF(version="4.10") as mdf:
        mdf.append([ASignal(samples, ts, name=_ARRAY_CHANNEL, unit="m")])
        mdf.save(out, overwrite=True)
    return out


def _channel_samples(path: Path) -> dict[str, np.ndarray]:
    """{生チャンネル名: samples} を asammdf 直叩きで読む (production を経由しない)。

    LD-08 の dedup 済み表示名を使わないのは ``leaf_paths`` が base 非依存
    (サフィックスと位置しか返さない) だからである — base の決め方は呼び出し側の
    責務で、ここで dedup 規則を写しても契約の被覆は 1 つも増えない。
    """
    out: dict[str, np.ndarray] = {}
    with MDF(str(path), time_from_zero=False) as mdf:
        entries = [
            (mdf.groups[phys_gi].channels[ci].name, phys_gi, ci)
            for vgi in mdf.virtual_groups
            for phys_gi, channel_indexes in mdf.included_channels(vgi)[vgi].items()
            for ci in channel_indexes
        ]
        for raw_name, gi, ci in entries:
            asig = mdf.select([(raw_name, gi, ci)], **_SELECT_OPTIONS)[0]
            # copy_master=False は asammdf 内部を指しうる — MDF を閉じた後も
            # 参照が生きるようここでコピーする。
            out[raw_name] = np.array(asig.samples)
    return out


@pytest.mark.parametrize(
    ("writer", "expected_leaves"),
    [
        (write_mdf4_2d, 4),  # 2-D 幅 3 (非連続スライス) + スカラー
        (write_mdf4_structured, 2),  # 構造化 (x, y)
        (write_mdf4_single_column_shapes, 5),  # (N,1) 2-D / 単一フィールド / 混在 Q
        (write_mdf4_all_non_numeric_struct, 3),  # 全リーフ非数値 R + スカラー
        (_write_nested_array_mf4, 12),  # 入れ子 6 + 併存する要素チャンネル 6
    ],
)
def test_leaf_paths_walk_matches_flatten_on_real_mf4(
    writer: Callable[[Path], Path], expected_leaves: int, tmp_path: Path
) -> None:
    """全リーフ: 走査順・列名・dtype・値が ``_flatten`` と一致する (実 mf4)。

    **これが位置パスと LD-14 列名文法を繋ぐ唯一の紐**である (モジュール docstring)。
    母数 (``expected_leaves``) を明示するのは、走査が空でもループ内の assert が
    すべて空回りして緑になるため — 手計算せず実測して貼ること。
    """
    leaves = 0
    for raw_name, samples in _channel_samples(writer(tmp_path)).items():
        spec = spec_from_probe(samples)
        expected = _flatten(raw_name, samples)
        walked = list(leaf_paths(spec))
        assert [raw_name + suffix for suffix, _p in walked] == [
            name for name, _c in expected
        ], raw_name
        for (_suffix, path), (name, column) in zip(walked, expected, strict=True):
            got = apply_path(samples, path)
            assert got.dtype == column.dtype, name
            np.testing.assert_array_equal(got, column, err_msg=name)
            assert got.base is None, name  # spec §5.4 (詳細は専用テスト)
            leaves += 1
    assert leaves == expected_leaves, writer.__name__


@pytest.mark.parametrize(
    ("raw_name", "suffix", "naive"),
    [
        ("Mono", "[0]", lambda a: a[:, 0]),  # (N,1) の 2-D 列は**連続** view
        ("P", ".x", lambda a: a["x"]),  # 単一フィールド構造化も**連続** view
    ],
)
def test_apply_path_returns_an_independent_array_for_view_shaped_leaves(
    raw_name: str,
    suffix: str,
    naive: Callable[[np.ndarray], np.ndarray],
    tmp_path: Path,
) -> None:
    """spec §5.4: 命中パスは ``base`` を持たない独立配列を返す。

    ``write_mdf4_single_column_shapes`` を使うのが必須 — 実測で **base が残りうるのは
    ``Mono[0]`` と ``P.x`` の 2 リーフだけ**である。幅 3 以上の 2-D や複数フィールド
    構造化はスライスが非連続で ``ascontiguousarray`` が必ず実コピーするため、copy を
    外しても ``base is None`` のまま通る (= ``write_mdf4_2d`` だけで書いたテストは
    この所有権違反に構造的に盲目)。
    """
    samples = _channel_samples(write_mdf4_single_column_shapes(tmp_path))[raw_name]
    path = dict(leaf_paths(spec_from_probe(samples)))[suffix]

    # 前提の実証: 素の走査は **view を返す** (この fixture が本当にガードを
    # 踏んでいることの証拠。踏んでいなければ下の assert は空虚な緑になる)。
    plain = naive(samples)
    assert np.ascontiguousarray(plain).base is not None, raw_name

    out = apply_path(samples, path)
    assert out.base is None, raw_name
    # 二重コピー防止 (spec §5.4 の付随契約): 自分が作った配列は read-only で返すので
    # ``sample_source._freeze`` が素通しする。writeable のまま返すと同じ列を
    # **2 回**コピーする (E-4a が縮めようとしている列読みのホットパス)。
    assert out.flags.writeable is False, raw_name
    np.testing.assert_array_equal(out, plain)


def test_leaf_paths_covers_non_numeric_leaves_that_leaf_names_drops(
    tmp_path: Path,
) -> None:
    """列挙空間の明示 (spec §5.6): パスは全リーフ・``leaf_names`` は数値リーフのみ。

    ずれる形は 2 つあり、片方だけでは片肺になる: 混在構造 ``Q`` (x: f8 + tag: S2 —
    数値が残る) と全非数値構造 ``R`` (tag: S2 + code: S3 — 数値が 1 本も無い)。
    パスを数値で間引くと 2 本目以降が 1 つずつ手前へずれ、**別の列を黙って返す**。
    """
    mixed = _channel_samples(write_mdf4_single_column_shapes(tmp_path))["Q"]
    q_spec = spec_from_probe(mixed)
    assert [suffix for suffix, _p in leaf_paths(q_spec)] == [".x", ".tag"]
    assert list(leaf_names("Q", q_spec)) == ["Q.x"]  # 非数値は列キー空間に無い

    all_text = _channel_samples(write_mdf4_all_non_numeric_struct(tmp_path))["R"]
    r_spec = spec_from_probe(all_text)
    assert [suffix for suffix, _p in leaf_paths(r_spec)] == [".tag", ".code"]
    assert list(leaf_names("R", r_spec)) == []

    # 数値判定は経路でなく**引いた配列の dtype**で行う (ColumnPath は dtype を持たない)
    numeric = [
        "Q" + suffix
        for suffix, path in leaf_paths(q_spec)
        if apply_path(mixed, path).dtype.kind in "iufb"
    ]
    assert numeric == list(leaf_names("Q", q_spec))
    assert apply_path(mixed, dict(leaf_paths(q_spec))[".tag"]).dtype.kind == "S"


def test_nested_array_paths_are_field_names_and_indices(tmp_path: Path) -> None:
    """``_flatten`` を一切通さない手書きオラクル — steps と値を直接固定する。

    全数テストは参照側も ``_flatten`` なので、**順序規則そのもの**が両側同時に
    変わると盲目になる (``test_column_roundtrip`` の
    ``test_literal_values_pin_the_key_to_column_mapping`` と同じ理由)。
    位置が整数序数で表せないこと (spec §5.6) もここで直接見える — steps は
    (フィールド名 str, 添字 int) の混在列である。
    """
    samples = _channel_samples(_write_nested_array_mf4(tmp_path))[_ARRAY_CHANNEL]
    walked = list(leaf_paths(spec_from_probe(samples)))
    assert [(suffix, path.steps) for suffix, path in walked] == [
        (f".{_ARRAY_CHANNEL}[0]", (_ARRAY_CHANNEL, 0)),
        (f".{_ARRAY_CHANNEL}[1]", (_ARRAY_CHANNEL, 1)),
        (f".{_ARRAY_CHANNEL}[2]", (_ARRAY_CHANNEL, 2)),
        (f".{_ARRAY_CHANNEL}.dx[0]", (f"{_ARRAY_CHANNEL}.dx", 0)),
        (f".{_ARRAY_CHANNEL}.dx[1]", (f"{_ARRAY_CHANNEL}.dx", 1)),
        (f".{_ARRAY_CHANNEL}.dx[2]", (f"{_ARRAY_CHANNEL}.dx", 2)),
    ]
    # fixture の値定義 (10*k+i+1 / 100*(i+1)+k) から手で書き下した期待値
    by_suffix = dict(walked)
    np.testing.assert_array_equal(
        apply_path(samples, by_suffix[f".{_ARRAY_CHANNEL}[1]"]), [2, 12, 22, 32]
    )
    np.testing.assert_array_equal(
        apply_path(samples, by_suffix[f".{_ARRAY_CHANNEL}.dx[2]"]),
        [300.0, 301.0, 302.0, 303.0],
    )


def test_apply_path_does_not_freeze_an_array_the_caller_owns() -> None:
    """空経路の分岐で呼び出し側の配列の可変性を横から奪わない (T1 レビュー I1).

    ``apply_path`` は自分が作った配列だけを凍結する。この ``out is not samples``
    ガードは T1 の sabotage 一式が 1 つも突いておらず、削除しても全スイートが緑
    だった — 契約の中で唯一検出器を持たない場所だったのでここで塞ぐ。

    今日の production では E-4a T2 が ``cache.put`` の前に凍結するので、この分岐に
    来る配列は既に read-only であり、ガードを消しても実害は出ない。**それがまさに
    このテストが要る理由**で、キャッシュ側が凍結をやめた瞬間 (S11 の方向) にガードは
    再び唯一の防波堤に戻る。その時に初めて壊れていたと気付くのでは遅い。
    """
    arr = np.zeros(3, dtype=np.float64)  # スカラーチャンネル = 空経路
    out = apply_path(arr, ColumnPath(()))

    assert out is arr  # 余計なコピーもしない
    assert arr.flags.writeable
