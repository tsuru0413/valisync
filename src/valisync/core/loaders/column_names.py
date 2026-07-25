"""LD-14 の列名文法の単一の真実 (ColumnSpec とその上の生成).

従来は mdf_loader の ``_flatten`` と ``_leaf_column_count`` が同じ規則を 2 箇所で
手写ししており、共有コードも突合 assert も無かった。列展開を遅延化すると
「名前を生成する側」と「名前から列を引く側」が分離するため、乖離はサイレントに
誤った列を返す。本モジュールを唯一の実装とし、順序は _flatten と一致させる。

現時点では生成 (``spec_from_probe`` / ``leaf_names`` / ``leaf_count``) のみを
提供する。名前→列の逆変換 (``parse_leaf``) は後続タスクで追加する。
"""

from __future__ import annotations

from collections.abc import Iterator
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
