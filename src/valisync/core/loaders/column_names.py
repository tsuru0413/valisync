"""LD-14 の列名文法の単一の真実 (ColumnSpec とその上の生成).

従来は mdf_loader の ``_flatten`` と ``_leaf_column_count`` が同じ規則を 2 箇所で
手写ししており、共有コードも突合 assert も無かった。列展開を遅延化すると
「名前を生成する側」と「名前から列を引く側」が分離するため、乖離はサイレントに
誤った列を返す。本モジュールを唯一の実装とし、順序は _flatten と一致させる。

生成 (``spec_from_probe`` / ``leaf_names`` / ``leaf_count``) と逆変換
(``parse_leaf``) を対で持つ。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import numpy as np

_NUMERIC_KINDS = "iufb"  # Signal が扱える dtype (それ以外は列キー空間に載せない)


@dataclass(frozen=True)
class ColumnSpec:
    """1 物理チャンネルの列構造 (値を持たない・1 レコードプローブから作る)."""

    kind: str  # "leaf" | "array" | "struct"
    dtype_kind: str = ""  # leaf のみ: numpy dtype.kind
    axis_len: int = 0  # array のみ: 先頭の非サンプル軸の長さ
    child: ColumnSpec | None = None  # array のみ: 1 段剥がした後の構造
    fields: tuple[tuple[str, ColumnSpec], ...] = ()  # struct のみ (順序保存)


@dataclass(frozen=True, slots=True)
class ColumnRecord:
    """物理チャンネル 1 本の鋳造に必要な最小情報 (値は持たない)。

    ローダーが持つ 2 つのキー空間を橋渡しする唯一の置き場: 列キー / 表示名は
    LD-08 dedup 済み (同名 2 本なら ``sig[0]`` / ``sig[1]``) だが、asammdf の
    ``select`` は**生チャンネル名と (gi, ci)** を要求する。表示名からは生名も
    位置も復元できない (dedup は非可逆) ため、ロード時にここへ残す。
    """

    raw_base_name: str  # asammdf のチャンネル名 (LD-08 dedup 前の生名)
    group_index: int
    channel_index: int
    spec: ColumnSpec


def spec_from_probe(arr: np.ndarray) -> ColumnSpec:
    """samples (axis 0 = サンプル) から列構造を作る。_flatten と同じ規則・同じ順序。

    構造化を ndim より先に判定するのは _flatten と同一 (構造化 1D は struct 扱い)。
    """
    if arr.dtype.names:
        return ColumnSpec(
            kind="struct",
            fields=tuple((f, spec_from_probe(arr[f])) for f in arr.dtype.names),
        )
    if arr.ndim <= 1:
        return ColumnSpec(kind="leaf", dtype_kind=arr.dtype.kind)
    axis_len = int(arr.shape[1])
    if axis_len == 0:
        # 0 幅軸は実サンプルを 1 つも持たないため arr[:, 0] が IndexError になる。
        # _flatten は range(0) が空になり自然に [] を返す (展開不能列は空リスト・LD-14)。
        # leaf_names/leaf_count も axis_len==0 で child を実際には辿らないが、
        # dtype/残り軸の形だけは実データ無しで分かるため空プローブで正しく構造化する。
        child_probe = np.empty((0, *arr.shape[2:]), dtype=arr.dtype)
    else:
        child_probe = arr[:, 0]
    return ColumnSpec(
        kind="array", axis_len=axis_len, child=spec_from_probe(child_probe)
    )


def leaf_names(base: str, spec: ColumnSpec) -> Iterator[str]:
    """数値リーフの列名を _flatten と同じ順序で生成する (ジェネレータ)."""
    if spec.kind == "struct":
        for name, sub in spec.fields:
            yield from leaf_names(f"{base}.{name}", sub)
    elif spec.kind == "array":
        assert spec.child is not None
        for i in range(spec.axis_len):
            yield from leaf_names(f"{base}[{i}]", spec.child)
    elif spec.dtype_kind in _NUMERIC_KINDS:
        yield base


def leaf_count(spec: ColumnSpec) -> int:
    """数値リーフの本数 (名前を生成せずに数える)."""
    if spec.kind == "struct":
        return sum(leaf_count(sub) for _n, sub in spec.fields)
    if spec.kind == "array":
        assert spec.child is not None
        return spec.axis_len * leaf_count(spec.child)
    return 1 if spec.dtype_kind in _NUMERIC_KINDS else 0


def parse_leaf(
    display_key: str, specs: Mapping[str, ColumnSpec]
) -> tuple[str, ColumnSpec] | None:
    """列キーを (物理表示名, リーフの ColumnSpec) へ復元する。解決不能なら None。

    **'.' で split しない** — asammdf のフィールド名はチャンネル名そのもので '.' を
    合法に含む (例 dtype.names == ('Radar.ObjList', 'Radar.ObjList.dx'))。逆変換は
    既知集合への最長一致で行う: (1) 物理表示名の最長プレフィクスで base を確定
    (最長優先 = Mat[0] 衝突時は実チャンネルが勝つ)、(2) 残余を ColumnSpec が持つ
    実フィールド名と [i] トークンで消費する。曖昧・消費しきれない場合は None を返し、
    決して別の列を返さない。

    **precondition — specs のキー空間**: ``specs`` は生チャンネル名 (mdf_loader の
    ``base_name``) をキーとする Mapping でなければならない。LD-08 の ``[idx]``
    曖昧化済み表示名 (``signal_name``) をキーにしてはいけない — mdf_loader の
    セレクタ (``sel_leaves = _flatten(base_name, samples)``) は生名からリーフを
    引くため、この2つのキー空間はそれぞれ内部一貫だが混ぜてはならない。
    健全性の限界: 2 つの物理チャンネルが同じ生名を共有する場合
    (``name_total[base_name] > 1`` の LD-08 重複ケース)、生名キーの単純な
    ``Mapping`` はその2チャンネルをサイレントに衝突させ、構造の異なる方の
    チャンネルの spec を誤って返しうる。これは呼び出し側の前提条件であり
    ``parse_leaf`` 自身では検出できない — 呼び出し側は生名の一意性を保証するか、
    (gi, ci) ごとに解決した spec を渡す必要がある。

    ルックアップは O(len(key)) (specs 全体の O(number of channels) 走査ではない)。
    """
    for i in range(len(display_key), 0, -1):
        spec = specs.get(display_key[:i])
        if spec is not None:
            leaf = _consume(display_key[i:], spec)
            if leaf is not None:
                return (display_key[:i], leaf)
    return None


def _consume(rest: str, spec: ColumnSpec) -> ColumnSpec | None:
    """spec を辿って rest を消費する。消費しきってリーフに達したらそのリーフを返す。"""
    if spec.kind == "struct":
        # フィールド名は '.' を含みうるので、既知フィールドの最長一致で消費する
        for name, sub in sorted(spec.fields, key=lambda p: len(p[0]), reverse=True):
            token = f".{name}"
            if rest.startswith(token):
                got = _consume(rest[len(token) :], sub)
                if got is not None:
                    return got
        return None
    if spec.kind == "array":
        assert spec.child is not None
        if not rest.startswith("["):
            return None
        end = rest.find("]")
        if end < 0:
            return None
        index_text = rest[1:end]
        # isdigit() 単独は上付き数字 ('²' 等) にも True を返すが int() はそれを
        # ValueError で拒否する — isascii() を併せて非 ASCII 数字を弾く
        # (解決失敗は必ず None・例外を投げてはならない契約)。
        if not (index_text.isascii() and index_text.isdigit()):
            return None
        # isdigit() は '-' を含まない (常に >= 0) ため上限のみ確認すればよい。
        if not (int(index_text) < spec.axis_len):
            return None
        return _consume(rest[end + 1 :], spec.child)
    # leaf: 残余が空で、かつ数値リーフのときだけ成立
    if rest:
        return None
    return spec if spec.dtype_kind in _NUMERIC_KINDS else None
