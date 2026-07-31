"""LD-14 の列名文法の単一の真実 (ColumnSpec とその上の生成).

従来は mdf_loader の ``_flatten`` と展開列数カウンタが同じ規則を 2 箇所で
手写ししており、共有コードも突合 assert も無かった。列展開を遅延化すると
「名前を生成する側」と「名前から列を引く側」が分離するため、乖離はサイレントに
誤った列を返す。本モジュールを唯一の実装とし、順序は _flatten と一致させる。

生成 (``spec_from_probe`` / ``leaf_names`` / ``leaf_count``) と逆変換
(``parse_leaf``) を対で持つ。E-4a からは **位置** (``ColumnPath`` /
``leaf_paths`` / ``apply_path``) も同じ順序規則の上に載る — 名前で引く経路と
位置で引く経路が別々の順序を持つと、同じ列キーが読みごとに別の列を返す。
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


@dataclass(frozen=True, slots=True)
class ColumnPath:
    """全リーフ空間における 1 リーフへの経路 (フィールド名と添字の列)。

    **整数序数では表現できない** — 構造化 × 配列の入れ子 (``Name.field[i]`` /
    ``Name[i][j]``) があるため「n 番目のリーフ」という 1 個の数では位置が定まらない。
    ``str`` = 構造化フィールド名 / ``int`` = 配列の添字 (剥がすのは常に軸 1。
    軸 0 はサンプル軸である)。

    名前 (列キー) は永続キーのまま (LD-14)。位置は**ロードごとに導出する派生値**で
    あり保存しない — チャンネル構造が変わればロード時に作り直される。
    """  # noqa: RUF002 — 乗算記号は設計 spec §5.6 と同じ字面を保つため意図的

    steps: tuple[str | int, ...]


def leaf_paths(spec: ColumnSpec) -> Iterator[tuple[str, ColumnPath]]:
    """(リーフ名サフィックス, 経路) を _flatten と同じ順序で生成する (ジェネレータ)。

    **列挙空間は _flatten と同じ「全リーフ」** — ``leaf_names`` が返すのは数値リーフ
    だけで、混在構造 (``Q``: x=f8 + tag=S2) では両者がずれる。位置は「デコード済み
    配列のどこを引くか」なので dtype で間引いてはならない (間引くと後続のリーフが
    1 つずつ手前へずれ、**別の列を黙って返す**)。数値判定は経路ではなく引いた配列の
    dtype で行う。

    **base を取らない**のは、サフィックスが base 非依存だからである。列キーは LD-08
    dedup 済み表示名から作り (``leaf_names(display, spec)``)、読みは生名を使う
    (``_flatten(raw, samples)``) — 2 つのキー空間で base は違うが、サフィックスと
    位置は共通なので、ここで dedup 規則を写す必要が無い。

    ジェネレータなのは ``leaf_names`` と同じ理由 — 広幅チャンネル (prod は 1,100 列)
    で全サフィックスを常に実体化しないため。
    """
    yield from _leaf_paths("", (), spec)


def _leaf_paths(
    suffix: str, steps: tuple[str | int, ...], spec: ColumnSpec
) -> Iterator[tuple[str, ColumnPath]]:
    """leaf_paths の再帰本体。名前と経路を**同時に**伸ばして順序の一致を構造的に保つ。"""
    if spec.kind == "struct":
        for name, sub in spec.fields:
            yield from _leaf_paths(f"{suffix}.{name}", (*steps, name), sub)
    elif spec.kind == "array":
        assert spec.child is not None
        for i in range(spec.axis_len):
            yield from _leaf_paths(f"{suffix}[{i}]", (*steps, i), spec.child)
    else:
        yield (suffix, ColumnPath(steps))


def apply_path(samples: np.ndarray, path: ColumnPath) -> np.ndarray:
    """samples (axis 0 = サンプル) から経路のリーフ列を **独立配列**で取り出す。

    **必ず base を持たない配列を返す (E-4 spec §5.4 の所有権の不変条件)**: 共有
    キャッシュの 2-D 配列を view のまま返すと、``_freeze`` が read-only 入力を素通し
    する性質と相まって view が ``LazyMdfValues._cache`` へ焼き付く。すると (1) LRU が
    evict しても列 Signal が base 経由で 2-D 全体を保持し RSS が 1 バイトも下がらず
    (2) ``nbytes_if_materialized`` が view の nbytes を返して teardown のバイト軸が
    黙って死ぬ。**値一致の検証は view でも全部通る**ので、ここを緩めても値のテストは
    緑のままである。

    連続スライス (幅 1 の 2-D・単一フィールド構造化) では ``ascontiguousarray`` が
    コピーを作らないため、明示的な copy が要る。経路が空 (スカラーチャンネル) かつ
    入力が既に独立配列なら入力そのものを返す — 列 = チャンネル全体で余分に生かす親が
    無く、不変条件 (base is None) は満たされる。

    **自分が作った配列は read-only にして返す**: 呼び出し側 (``LazyMdfValues.
    _column_of``) が通す ``sample_source._freeze`` は ``writeable`` を見て
    ``array.copy()`` するので、writeable のまま返すと**同じ列を 2 回コピーする**
    (実測: 非連続スライスへの ``ascontiguousarray`` は writeable=True のコピーを
    返し、``_freeze`` がもう 1 回コピーする)。E-4a が縮めようとしている列読みの
    ホットパスで毎列 2x のアロケーション + memcpy になるため、**ここで凍結して
    ``_freeze`` を素通しにするのが正**。この 2 行を「凍結は ``_freeze`` の仕事」と
    考えて消さないこと — 消すと二重コピーが黙って戻る。
    """
    out = samples
    for step in path.steps:
        # int は軸 1 を剥がす (_flatten の arr[:, i] と同一) — 軸 0 はサンプル軸
        out = out[step] if isinstance(step, str) else out[:, step]
    out = np.ascontiguousarray(out)
    if out.base is not None:
        out = out.copy()
    if out is not samples:
        # 凍結するのは **この関数が作った配列だけ**。経路が空で入力そのものを返す
        # 場合まで凍結すると、呼び出し側が渡した配列の可変性を横から奪う
        # (production ではその配列は共有前に read-only 化済みなので、この分岐でも
        # _freeze は素通しし、やはりコピーは 0 回である)。
        out.flags.writeable = False
    return out


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

    **E-3 以降の正しい呼び方 (鋳造経路)**: 列キーは *表示空間* にある
    (``Signal.name`` 由来・dedup 済みチャンネルなら ``sig[1][2]``)。それを全チャンネル
    分の生名キー ``Mapping`` へそのまま渡してはならない — 上の限界にそのまま落ちる。
    ``SignalGroupManager.column_records`` (キー = LD-08 dedup 済み表示名) で
    **先に物理チャンネルを確定**し、生名は当該 ``ColumnRecord.raw_base_name`` から
    取る。そのうえで本関数へ渡すのは
    ``parse_leaf(raw_base_name + 残余, {raw_base_name: record.spec})`` の
    **単一エントリ Mapping** — これが上で言う「(gi, ci) ごとに解決した spec」であり、
    エントリが 1 本しかないので衝突は構造的に起こり得ない。失敗モードは例外でなく
    **別チャンネルのデータ**なので、この順序は守ること。

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
