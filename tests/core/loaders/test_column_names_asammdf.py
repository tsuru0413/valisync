"""asammdf で実書き出し→実読み戻ししたドット付きフィールド名で往復を固定する。

手書きの合成 dtype 名では再現しない性質を 2 つ被覆する (Critical 2):

1. asammdf は配列チャンネル (CABLOCK) の第 0 フィールド名に**チャンネル名そのもの**
   を使うため、フィールド名が '.' を含む。実測 dtype.names ==
   ``('Radar.ObjList', 'Radar.ObjList.dx')`` — '.' で split すると 3 セグメントに
   見えるが実フィールドは 2 本。
2. 同じファイルの読み戻しには、要素チャンネル ``Radar.ObjList[0]`` や
   ``Radar.ObjList.dx[0]`` が**物理チャンネルとして併存**する。これは親の列キー
   空間と字面が衝突するため、最長一致 (実チャンネルが勝つ) が実データで要る。

両 demo ファイルは構造化チャンネル 0 本でこの不変条件を一切被覆しないため、
'.' split の素朴実装でも全テストがグリーンになる。本モジュールは demo-gate せず
自前で tmp_path に小さな mf4 を書いて実往復させる。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from asammdf import MDF
from asammdf import Signal as ASignal

from valisync.core.loaders.column_names import (
    ColumnSpec,
    leaf_names,
    parse_leaf,
    spec_from_probe,
)
from valisync.core.loaders.mdf_loader import MdfLoader

_CHANNEL = "Radar.ObjList"
_AXIS_LEN = 3

# 本番と同じ probe オプション定義を再利用する — 手写しコピーだと production の
# _PROBE_OPTIONS が変わってもこのフィクスチャは追随せず実挙動から乖離しうる。
_PROBE_OPTIONS = MdfLoader._PROBE_OPTIONS


def _write_array_mf4(tmp_path: Path) -> Path:
    """ドット付きチャンネル名の CABLOCK 配列チャンネルを 1 本だけ持つ mf4 を書く。

    サブ配列付きフィールド (``("Radar.ObjList", "<u1", (3,))``) で渡すのが要点 —
    スカラーフィールドの構造化 Signal だと asammdf は別表現に落とし、フィールド名が
    チャンネル名になる本ハザードを再現しない。
    """
    n = 4
    ts = np.arange(n, dtype=np.float64)
    dtype = np.dtype(
        [(_CHANNEL, "<u1", (_AXIS_LEN,)), (f"{_CHANNEL}.dx", "<f8", (_AXIS_LEN,))]
    )
    samples = np.zeros(n, dtype=dtype)
    samples[_CHANNEL] = 3
    samples[f"{_CHANNEL}.dx"] = 1.25
    out = tmp_path / "array.mf4"
    with MDF(version="4.10") as mdf:
        mdf.append([ASignal(samples, ts, name=_CHANNEL, unit="m")])
        mdf.save(out, overwrite=True)
    return out


def _read_specs(path: Path) -> dict[str, ColumnSpec]:
    """mdf_loader と同じ列挙・同じ probe オプションで {物理表示名: ColumnSpec} を作る。"""
    specs: dict[str, ColumnSpec] = {}
    with MDF(str(path), time_from_zero=False) as mdf:
        for gi in mdf.virtual_groups:
            included = mdf.included_channels(gi)[gi]
            entries = [
                (mdf.groups[phys_gi].channels[ci].name, phys_gi, ci)
                for phys_gi, channel_indexes in included.items()
                for ci in channel_indexes
            ]
            for (name, _g, _c), probe in zip(
                entries, mdf.select(entries, **_PROBE_OPTIONS), strict=True
            ):
                specs[name] = spec_from_probe(probe.samples)
    return specs


def test_asammdf_array_channel_really_has_dotted_field_names(tmp_path: Path) -> None:
    """ハザードの前提そのものを実データで固定する (前提が崩れたら即座に赤くする)."""
    specs = _read_specs(_write_array_mf4(tmp_path))
    spec = specs[_CHANNEL]
    assert spec.kind == "struct"
    field_names = [f for f, _s in spec.fields]
    assert field_names == [_CHANNEL, f"{_CHANNEL}.dx"], field_names
    # '.' を含むフィールド名が実在すること = 合成 dtype では再現しない性質
    assert any("." in f for f in field_names), field_names
    # 実フィールドは 2 本だが、'.' split では観測されたフィールド名自体が
    # 3 セグメントに見える (合成文字列でなく実データで固定する)
    assert len(field_names[1].split(".")) == 3, field_names


def test_dotted_field_names_round_trip(tmp_path: Path) -> None:
    specs = _read_specs(_write_array_mf4(tmp_path))
    spec = specs[_CHANNEL]
    names = list(leaf_names(_CHANNEL, spec))
    assert names, "structured channel produced no leaves"
    assert f"{_CHANNEL}.{_CHANNEL}.dx[0]" in names, names
    assert len(set(names)) == len(names), names  # generator must not alias two columns
    for name in names:
        got = parse_leaf(name, specs)
        assert got is not None, f"could not parse {name!r}"
        assert got[0] == _CHANNEL, f"{name!r} resolved to {got[0]!r}"


def test_every_physical_channel_round_trips_including_element_siblings(
    tmp_path: Path,
) -> None:
    """要素チャンネル (``Radar.ObjList[0]`` 等) が併存しても各リーフが自分の base へ戻る。

    ``Radar.ObjList[0]`` は親 ``Radar.ObjList`` の列キーと字面が衝突しうる実チャンネル
    — 最長一致で実チャンネルが勝たなければ、別の列を黙って返してしまう。
    """
    specs = _read_specs(_write_array_mf4(tmp_path))
    # 要素チャンネルが実際に併存していることを実証 (無ければ衝突を被覆していない)
    assert f"{_CHANNEL}[0]" in specs, sorted(specs)
    assert f"{_CHANNEL}.dx[0]" in specs, sorted(specs)

    for base, spec in specs.items():
        for name in leaf_names(base, spec):
            got = parse_leaf(name, specs)
            assert got is not None, f"could not parse {name!r}"
            assert got[0] == base, f"{name!r} resolved to {got[0]!r} (want {base!r})"


def test_parent_column_key_is_not_confused_with_element_channel(
    tmp_path: Path,
) -> None:
    specs = _read_specs(_write_array_mf4(tmp_path))
    # 実チャンネル名そのもの → 実チャンネルが勝つ (親の列ではない)
    got = parse_leaf(f"{_CHANNEL}.dx[0]", specs)
    assert got is not None
    assert got[0] == f"{_CHANNEL}.dx[0]"
    # 親の列キーは親へ
    got_parent = parse_leaf(f"{_CHANNEL}.{_CHANNEL}.dx[0]", specs)
    assert got_parent is not None
    assert got_parent[0] == _CHANNEL
    # 存在しない列は None (別の列を返してはならない)
    assert parse_leaf(f"{_CHANNEL}.{_CHANNEL}.dx[{_AXIS_LEN}]", specs) is None
    assert parse_leaf(f"{_CHANNEL}.dx[0].nope", specs) is None
