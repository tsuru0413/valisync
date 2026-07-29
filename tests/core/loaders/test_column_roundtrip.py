"""列キー ↔ 列データの全数ラウンドトリップ・オラクル (E-3 反転より前に固定する)。

**なぜ独立参照を eager ローダーに置かないか**: E-3 でローダーは物理チャンネル 1 本に
つき Signal 1 個しか発行しなくなる。eager 展開の結果を参照にすると、参照そのものが
反転で消えてテストが書き換え対象になる。代わりに asammdf の ``select`` と ``_flatten``
の直叩きを参照に置く — ``_flatten`` は反転後も ``LazyMdfValues.array()`` が使い続ける
(``sample_source.py`` の遅延 import) ため、**反転を跨いで同一のオラクル**になる。

**二重名の契約**を両側とも直接固定する: 表示キーは LD-08 dedup 済み名から、selector は
**生**チャンネル名から導く。前者を誤ると ``dup[0]``/``dup[1]`` が解決できない。後者は
**展開されるチャンネルが dedup されたときにしか観測できない** — 同名 1 本きりなら
表示名 = 生名で両者が一致してしまい、selector を表示キーから導く実装がそのまま通る。
そこで同名の 2-D チャンネル ``Mat2`` を 2 本置く: 列キーは ``Mat2[0][i]`` (dedup 済み
表示名由来) だが selector は ``Mat2[i]`` (生名由来) でなければならず、字面が食い違う。
表示キー由来の selector に倒すと遅延読みが ``SampleReadError`` になる
(``test_deduplicated_exploded_channel_pins_both_name_spaces``)。

**反転前は「鋳造テストとしては」vacuous** である: ``_mint_column`` が None を返す現状、
``resolve()`` は既存の ``_namespaced_map`` (eager 展開済み列) が答えている。それは想定内で、
本モジュールの反転前の役割は「反転後に満たすべき全数の期待値を、実装非依存の形で先に
凍結する」こと。鋳造経路の honest-RED は反転タスク (T6) 側で sabotage により実証する。

**構造的な弱点 (記録)**: ``Name[i][j]`` だけは asammdf の public write API で往復できない
(``tests/mdf4_helpers.py`` の 3-D 不可の注記と同根)。(2,3) サブ配列フィールドを書いても
読み戻しは (6,) へ潰れる — 本モジュールはその実測自体をテストで固定したうえで、
``[i][j]`` の腕のみ合成 ndarray で確認する。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from asammdf import MDF
from asammdf import Signal as ASignal

from valisync.core.loaders.column_names import leaf_names, parse_leaf, spec_from_probe
from valisync.core.loaders.mdf_loader import _flatten
from valisync.core.models import Signal
from valisync.core.session import Session

_TS = np.array([0.0, 0.1, 0.2, 0.3])
_ARRAY_CHANNEL = "Radar.ObjList"  # フィールド名が '.' を含む CABLOCK 配列チャンネル
_AXIS_LEN = 3
# comment は「両側とも空文字」で通ってしまう vacuous な腕になりやすいので、
# 1-D チャンネル (Scaled) と展開親 (Pos) の両方に実値を置く。unit と同じ強さで
# 「metadata を落としたら RED」にするための値であり、往復は実測で厳密一致する。
_SCALED_COMMENT = "車速 (物理値・0.01 係数)"
_POS_COMMENT = "位置ベクトル (前方=+X)"
# 遅延読み (LazyMdfValues.array()) と同一の正準オプション。オラクルが production と
# 別の側 (raw=True 等) を読むと、値の比較が「両方同じだけ壊れている」を見逃す。
_SELECT_OPTIONS: dict[str, Any] = {
    "raw": False,
    "ignore_value2text_conversions": True,
    "copy_master": False,
}
# 実測で凍結した数値列キーの全数 (36 本・sorted 順)。下限 (>=) では「腕が 1 つ
# 消えた」を隠すので全数一致で固定する。末尾寄りの Radar.ObjList[i] /
# Radar.ObjList.dx[i] は展開列ではなく、asammdf が CABLOCK 配列に対して同一
# グループへ実在させる **要素チャンネル** (1-D の実チャンネル)。
# 先頭の Mat2[j][i] は「dedup 済み表示名の下に生えた展開列」— sorted では '2' <
# '[' なので Mat[i] より前に来る。手計算せず measure して貼ること (母数の
# 手計算は過去 2 回とも外れている)。
_EXPECTED_COLUMN_KEYS = [
    "Mat2[0][0]",
    "Mat2[0][1]",
    "Mat2[0][2]",
    "Mat2[1][0]",
    "Mat2[1][1]",
    "Mat2[1][2]",
    "Mat2[1][3]",
    "Mat[0]",
    "Mat[1]",
    "Mat[2]",
    "Mix.x",
    "Nest.g[0]",
    "Nest.g[1]",
    "Nest.g[2]",
    "Nest.g[3]",
    "Nest.g[4]",
    "Nest.g[5]",
    "Pos.xa",
    "Pos.xb",
    "Radar.ObjList.Radar.ObjList.dx[0]",
    "Radar.ObjList.Radar.ObjList.dx[1]",
    "Radar.ObjList.Radar.ObjList.dx[2]",
    "Radar.ObjList.Radar.ObjList[0]",
    "Radar.ObjList.Radar.ObjList[1]",
    "Radar.ObjList.Radar.ObjList[2]",
    "Radar.ObjList.dx[0]",
    "Radar.ObjList.dx[1]",
    "Radar.ObjList.dx[2]",
    "Radar.ObjList[0]",
    "Radar.ObjList[1]",
    "Radar.ObjList[2]",
    "Scaled",
    "ShA",
    "ShB",
    "dup[0]",
    "dup[1]",
]


def _write_roundtrip_mf4(tmp_path: Path) -> Path:
    """全腕を 1 ファイルに詰めた fixture を asammdf で実書き出しする。

    ``tests/mdf4_helpers`` の既存ヘルパを使わないのは、この fixture が
    (a) 名前が意図的に衝突する複数チャンネルを **同一ファイル** に持つ必要があり、
    (b) 反転タスクが触る約 20 の fixture サイトと寿命を共有したくないため。

    追加順は契約の一部: 2-D ``Mat`` の**後に** 1-D ``Mat[0]`` を置く。反転前の
    ``_namespaced_map`` は last-wins なので、この順序でのみ「実チャンネルが勝つ」
    (反転後は最長一致で構造的に勝つ) 期待値が両側で一致する。
    """
    from asammdf.blocks.conversion_utils import from_dict

    n = len(_TS)
    array_samples = np.zeros(
        n,
        dtype=np.dtype(
            [
                (_ARRAY_CHANNEL, "<u1", (_AXIS_LEN,)),
                (f"{_ARRAY_CHANNEL}.dx", "<f8", (_AXIS_LEN,)),
            ]
        ),
    )
    for k in range(n):
        for i in range(_AXIS_LEN):
            array_samples[_ARRAY_CHANNEL][k, i] = 10 * k + i + 1
            array_samples[f"{_ARRAY_CHANNEL}.dx"][k, i] = 100 * (i + 1) + k

    nested = np.zeros(n, dtype=np.dtype([("g", "<u1", (2, 3))]))
    for k in range(n):
        nested["g"][k] = np.arange(6, dtype=np.uint8).reshape(2, 3) + 10 * k

    mdf = MDF(version="4.10")
    try:
        # Name[i]: 2-D uint8 (列 i = [i, 10+i, 20+i, 30+i])
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]],
                        dtype=np.uint8,
                    ),
                    timestamps=_TS,
                    name="Mat",
                    unit="mm",
                )
            ]
        )
        # Mat[0] 衝突: 上の第 0 列と字面が同じ 1-D 実チャンネル (dtype も unit も別物)
        mdf.append(
            [
                ASignal(
                    samples=np.array([7.0, 8.0, 9.0, 10.0]),
                    timestamps=_TS,
                    name="Mat[0]",
                    unit="deg",
                )
            ]
        )
        # Name.field: 数値のみの構造化 (comment は展開列へ継承される側の対照)
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0)],
                        dtype=[("xa", "<f8"), ("xb", "<f8")],
                    ),
                    timestamps=_TS,
                    name="Pos",
                    unit="m",
                    comment=_POS_COMMENT,
                )
            ]
        )
        # 非数値混在: x は数値・tag は S2 (列キー空間に載ってはならない)
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [(1.0, b"ab"), (2.0, b"cd"), (3.0, b"ef"), (4.0, b"gh")],
                        dtype=[("x", "<f8"), ("tag", "S2")],
                    ),
                    timestamps=_TS,
                    name="Mix",
                )
            ]
        )
        # LD-08: 同名チャンネル 2 本 (別グループ = 別 master)
        for base in (100.0, 200.0):
            mdf.append(
                [
                    ASignal(
                        samples=np.array([base, base + 1, base + 2, base + 3]),
                        timestamps=_TS,
                        name="dup",
                        unit="V",
                    )
                ]
            )
        # LD-08 と LD-14 の交差: **展開されるチャンネルが dedup される**唯一の腕。
        # 表示名は Mat2[0]/Mat2[1] (dedup 済み) だが selector は生名 Mat2 から
        # 引かねばならない — 列キーが Mat2[0][i] / selector が Mat2[i] と字面から
        # 食い違う唯一の場所。列数 (3 / 4)・unit・値をすべて別にして、生名を共有する
        # 2 本の取り違えが必ず値か dtype か列数で露見するようにする。
        # 2-D は uint8 でなければ往復しない (float64 の (4,4) は読み戻しで (4,) へ
        # 潰れる — 実測。tests/mdf4_helpers.py の注記と同根)。
        for samples_2d, unit in (
            (
                np.array(
                    [[40, 41, 42], [50, 51, 52], [60, 61, 62], [70, 71, 72]],
                    dtype=np.uint8,
                ),
                "A",
            ),
            (
                np.array(
                    [
                        [81, 82, 83, 84],
                        [91, 92, 93, 94],
                        [101, 102, 103, 104],
                        [111, 112, 113, 114],
                    ],
                    dtype=np.uint8,
                ),
                "Nm",
            ),
        ):
            mdf.append(
                [ASignal(samples=samples_2d, timestamps=_TS, name="Mat2", unit=unit)]
            )
        # Name.field[i]: フィールド名が '.' を含む配列チャンネル
        # (要素チャンネル Radar.ObjList[i] が同グループに併存する)
        mdf.append([ASignal(array_samples, _TS, name=_ARRAY_CHANNEL, unit="m")])
        # サブ配列 (2,3) — 読み戻しで (6,) に潰れることの実測用
        mdf.append([ASignal(nested, _TS, name="Nest")])
        # 線形変換つきスカラー: 非 raw 読み (物理値) と conversion_info の正の対照
        mdf.append(
            [
                ASignal(
                    samples=np.array([0, 7980, -1234, 32767], dtype=np.int16),
                    timestamps=_TS,
                    name="Scaled",
                    unit="km/h",
                    comment=_SCALED_COMMENT,
                    conversion=from_dict({"a": 0.01, "b": 0.0}),
                )
            ]
        )
        # 1 グループに 2 チャンネル: master identity 共有をチャンネル跨ぎで被覆
        mdf.append(
            [
                ASignal(samples=np.arange(4.0), timestamps=_TS, name="ShA"),
                ASignal(samples=np.arange(4.0) * 2.0, timestamps=_TS, name="ShB"),
            ]
        )
        path = tmp_path / "roundtrip.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


@dataclass(frozen=True)
class _Col:
    """列キー 1 本ぶんの独立オラクル (production のローダーを一切経由しない)."""

    values: np.ndarray
    timestamps: np.ndarray
    unit: str
    comment: str
    virtual_group: int
    physical: str  # LD-08 dedup 済みの物理チャンネル表示名
    deduplicated: bool
    exploded: bool


def _oracle_columns(path: Path) -> dict[str, _Col]:
    """asammdf 直叩きで {列キー: オラクル} を作る (production の出力を見ない)。

    列挙は ``included_channels`` (構造化チャンネルの成分と master を除外済み)、
    表示名は LD-08 の dedup 規則、列名は ``_flatten`` — production と同じ規則を
    **独立に組み立てる**。衝突キーは実チャンネル優先 (最長一致と同規則) にするため、
    展開列を先に入れてから 1-D 実チャンネルで上書きする。
    """
    expanded: dict[str, _Col] = {}
    physical: dict[str, _Col] = {}
    with MDF(str(path), time_from_zero=False) as mdf:
        entries: list[tuple[str, int, int, int]] = []
        for vgi in mdf.virtual_groups:
            included = mdf.included_channels(vgi)[vgi]
            entries.extend(
                (mdf.groups[phys_gi].channels[ci].name, phys_gi, ci, vgi)
                for phys_gi, channel_indexes in included.items()
                for ci in channel_indexes
            )
        totals = Counter(name for name, _g, _c, _v in entries)
        seen: Counter[str] = Counter()
        for raw_name, phys_gi, ci, vgi in entries:
            idx = seen[raw_name]
            seen[raw_name] += 1
            deduplicated = totals[raw_name] > 1
            display = f"{raw_name}[{idx}]" if deduplicated else raw_name
            asig = mdf.select([(raw_name, phys_gi, ci)], **_SELECT_OPTIONS)[0]
            leaves = _flatten(display, asig.samples)
            exploded = asig.samples.ndim != 1 or bool(asig.samples.dtype.names)
            target = physical if not exploded else expanded
            for column_key, column in leaves:
                target[column_key] = _Col(
                    # copy_master=False は asammdf 内部を指しうる — MDF を閉じた後も
                    # 参照が生きるようここでコピーする。
                    values=np.array(column),
                    timestamps=np.array(asig.timestamps),
                    unit=asig.unit,
                    comment=asig.comment,
                    virtual_group=vgi,
                    physical=display,
                    deduplicated=deduplicated,
                    exploded=exploded,
                )
    return {**expanded, **physical}


def _numeric(columns: dict[str, _Col]) -> dict[str, _Col]:
    """列キー空間に載る (数値リーフの) 列だけを返す — _flatten は dtype 盲目."""
    return {k: c for k, c in columns.items() if c.values.dtype.kind in "iufb"}


@dataclass(frozen=True)
class _Loaded:
    session: Session
    key: str
    columns: dict[str, _Col]

    def resolve(self, column_key: str) -> Signal | None:
        return self.session.resolve_signal(f"{self.key}::{column_key}")


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Loaded]:
    path = _write_roundtrip_mf4(tmp_path_factory.mktemp("roundtrip"))
    columns = _oracle_columns(path)
    session = Session()
    key = session.load(path).key
    try:
        yield _Loaded(session=session, key=key, columns=columns)
    finally:
        # 遅延ロードは MDF を開いたまま保持する。閉じないと Windows では
        # tmp_path の後始末がファイルロックで失敗しうる。
        session.remove_group(key)


def test_oracle_covers_every_naming_arm(loaded: _Loaded) -> None:
    """母数と各腕の代表キーを先に固定する (オラクルが空でも通る vacuous 化の防止)."""
    numeric = _numeric(loaded.columns)
    assert sorted(numeric) == _EXPECTED_COLUMN_KEYS, sorted(numeric)  # 全数で凍結
    for column_key in (
        "Mat[1]",  # Name[i]
        "Pos.xa",  # Name.field
        "Nest.g[3]",  # Name.field[i]
        f"{_ARRAY_CHANNEL}.{_ARRAY_CHANNEL}.dx[2]",  # ドット付きフィールドの Name.field[i]
        f"{_ARRAY_CHANNEL}[1]",  # 併存する要素チャンネル (実チャンネル)
        "dup[0]",  # LD-08 dedup
        "dup[1]",
        "Mat2[0][2]",  # LD-08 dedup + LD-14 展開 (表示名 Mat2[0] / 生名 Mat2)
        "Mat2[1][3]",  # 同上・生名を共有する相方は列数が違う (4 列)
        "Mat[0]",  # Mat[0] 衝突
        "Scaled",  # 変換つきスカラー
        "ShA",  # master 共有グループ
        "ShB",
    ):
        assert column_key in numeric, sorted(numeric)
    # 非数値リーフが実在する (非数値の腕が空集合になっていない)
    assert loaded.columns["Mix.tag"].values.dtype.kind == "S"


def test_every_numeric_column_key_resolves_with_matching_values(
    loaded: _Loaded,
) -> None:
    """全数: 各列キーが解決でき、値・dtype・時刻列がオラクルと厳密一致する.

    **母数の保証は自前で持たない** — このループは ``_numeric(loaded.columns)`` が空でも
    通る。母数が 36 本であることは ``test_oracle_covers_every_naming_arm`` だけが固定して
    いるので、そちらを skip/xfail すると本テストを含む全数 3 本が同時に空洞化する。
    """
    for column_key, col in sorted(_numeric(loaded.columns).items()):
        sig = loaded.resolve(column_key)
        assert sig is not None, f"列キーが解決できない: {column_key!r}"
        assert sig.values.dtype == col.values.dtype, column_key
        np.testing.assert_array_equal(sig.values, col.values, err_msg=column_key)
        np.testing.assert_array_equal(
            sig.timestamps, col.timestamps, err_msg=column_key
        )


def test_group_master_is_shared_by_identity(loaded: _Loaded) -> None:
    """同一仮想グループの列は master ndarray を **同一オブジェクト** で共有する。

    ``source_info`` の ``id(s.timestamps)`` dedup がこの identity に依存しており、
    列ごとにコピーすると 264k 本ぶんの時刻列が実体化して会計も壊れる。

    **母数の保証は自前で持たない** — 全数 3 本の母数はいずれも
    ``test_oracle_covers_every_naming_arm`` の全数一致だけが固定している。
    """
    by_group: dict[int, list[tuple[str, Signal]]] = {}
    for column_key, col in sorted(_numeric(loaded.columns).items()):
        sig = loaded.resolve(column_key)
        assert sig is not None
        by_group.setdefault(col.virtual_group, []).append((column_key, sig))

    for items in by_group.values():
        ref_key, ref = items[0]
        assert ref.timestamps.flags.writeable is False, ref_key
        for column_key, sig in items[1:]:
            # id() の集合でなく参照を保持したまま `is` で比較する
            # (死んだオブジェクトのアドレス再利用による非決定フレークを避ける)。
            assert sig.timestamps is ref.timestamps, f"{column_key} vs {ref_key}"

    # 共有の 2 形態をどちらも被覆していること (同一チャンネルの列間 / 別チャンネル間)
    assert (
        loaded.columns["Mat[1]"].virtual_group == loaded.columns["Mat[2]"].virtual_group
    )
    assert loaded.columns["ShA"].virtual_group == loaded.columns["ShB"].virtual_group


def test_metadata_matches_oracle_for_every_column(loaded: _Loaded) -> None:
    """全数: physical_channel・unit・comment・name_deduplicated と LD-07 の非継承.

    **母数の保証は自前で持たない** — 全数 3 本の母数はいずれも
    ``test_oracle_covers_every_naming_arm`` の全数一致だけが固定している。

    **構造的な弱点 (記録)**: ``value_labels`` の非継承だけは **vacuous な否定**である。
    conversion_info には正の対照 (``Scaled``) を置けるが、value2text 変換は asammdf の
    public write API では実質書けない (raw 値 + comment 埋め込みはローダーの dead
    オプションで消える — LD-13 / memory ``mdf_authoring_2d_and_value2text_traps``)。
    したがって「展開列が value_labels を持たない」は「このファイルの誰も持たない」
    でも通る。対照を捏造せず、裏取りできていない事実として明示するに留める
    (``Name[i][j]`` の腕と同じ扱い)。
    """
    for column_key, col in sorted(_numeric(loaded.columns).items()):
        sig = loaded.resolve(column_key)
        assert sig is not None
        meta = sig.metadata
        assert meta["physical_channel"] == col.physical, column_key
        assert meta.get("unit", "") == col.unit, column_key
        assert meta.get("comment", "") == col.comment, column_key
        assert meta.get("name_deduplicated", False) == col.deduplicated, column_key
        if col.exploded:
            # LD-07: 展開列は value_labels も conversion_info も継承しない
            assert "value_labels" not in meta, column_key
            assert "conversion_info" not in meta, column_key
    # 正の対照 — 1-D チャンネルは conversion_info を持つ。これが無いと上の
    # 「継承しない」assert は「誰も持っていない」だけで通る vacuous な否定になる。
    scaled = loaded.resolve("Scaled")
    assert scaled is not None
    assert "conversion_info" in scaled.metadata
    # 正の対照 — comment に実値を持つ列が両形態 (1-D / 展開親からの継承) で存在する。
    # 全列が "" だと上の comment 比較は「両側とも空」で通る vacuous な腕になる。
    assert loaded.columns["Scaled"].comment == _SCALED_COMMENT
    assert loaded.columns["Pos.xa"].comment == _POS_COMMENT
    assert scaled.metadata["comment"] == _SCALED_COMMENT


def test_non_numeric_leaf_is_not_a_column_key(loaded: _Loaded) -> None:
    """``_flatten`` は dtype 盲目だが、列キー空間には数値リーフしか載らない。

    S2 フィールドが列キーになると「見えるのに永久に描かれない行」になる。判定は
    リーフ単位であり、同じチャンネルの数値リーフは巻き添えにしてはならない。
    """
    assert loaded.resolve("Mix.tag") is None
    assert loaded.resolve("Mix.x") is not None


def test_element_channel_wins_over_parent_column_key(loaded: _Loaded) -> None:
    """``Mat[0]`` は 2-D ``Mat`` の第 0 列と 1-D 実チャンネルの両方が名乗る。

    最長一致 = 実チャンネル優先。dtype (float64 vs uint8)・unit (deg vs mm)・値が
    すべて違うので、取り違えると必ず RED になる。
    """
    sig = loaded.resolve("Mat[0]")
    assert sig is not None
    assert sig.metadata["physical_channel"] == "Mat[0]"  # 親 "Mat" ではない
    assert sig.metadata["unit"] == "deg"  # 親は "mm"
    assert sig.values.dtype == np.float64  # 親の列は uint8
    np.testing.assert_array_equal(sig.values, [7.0, 8.0, 9.0, 10.0])
    assert loaded.columns["Mat[0]"].physical == "Mat[0]"  # オラクル側も実チャンネル


def test_literal_values_pin_the_key_to_column_mapping(loaded: _Loaded) -> None:
    """手書きの期待値 — ``_flatten`` を一切通さない独立オラクル。

    全数テストは参照側も ``_flatten`` を使うため、列の**順序規則そのもの**が
    反転すると両側が同じだけ壊れて盲目になる。ここだけは fixture の値定義から
    手で書き下した配列で固定する。
    """
    expected: dict[str, list[float]] = {
        "Mat[1]": [1, 11, 21, 31],
        "Mat[2]": [2, 12, 22, 32],
        "Pos.xa": [1.0, 3.0, 5.0, 7.0],
        "Pos.xb": [2.0, 4.0, 6.0, 8.0],
        "Mix.x": [1.0, 2.0, 3.0, 4.0],
        "Nest.g[3]": [3, 13, 23, 33],
        "dup[0]": [100.0, 101.0, 102.0, 103.0],
        "dup[1]": [200.0, 201.0, 202.0, 203.0],
        "Mat2[0][2]": [42, 52, 62, 72],
        "Mat2[1][0]": [81, 91, 101, 111],
        "Mat2[1][3]": [84, 94, 104, 114],
        f"{_ARRAY_CHANNEL}.{_ARRAY_CHANNEL}[1]": [2, 12, 22, 32],
        f"{_ARRAY_CHANNEL}.{_ARRAY_CHANNEL}.dx[2]": [300.0, 301.0, 302.0, 303.0],
        f"{_ARRAY_CHANNEL}[1]": [2, 12, 22, 32],
    }
    for column_key, values in expected.items():
        sig = loaded.resolve(column_key)
        assert sig is not None, column_key
        np.testing.assert_array_equal(sig.values, values, err_msg=column_key)


def test_scaled_channel_is_read_as_physical_values(loaded: _Loaded) -> None:
    """非 raw 読みの固定 — raw=True へ倒れると生カウント (100 倍ずれ) が返る."""
    sig = loaded.resolve("Scaled")
    assert sig is not None
    np.testing.assert_allclose(sig.values, [0.0, 79.8, -12.34, 327.67])


def test_ld08_duplicate_names_resolve_to_distinct_columns(loaded: _Loaded) -> None:
    """同名 2 本は別の物理チャンネル — 表示キーは dedup 済み名から作る."""
    first, second = loaded.resolve("dup[0]"), loaded.resolve("dup[1]")
    assert first is not None and second is not None
    assert first.metadata["name_deduplicated"] is True
    assert second.metadata["name_deduplicated"] is True
    np.testing.assert_array_equal(first.values, [100.0, 101.0, 102.0, 103.0])
    np.testing.assert_array_equal(second.values, [200.0, 201.0, 202.0, 203.0])
    assert first.timestamps is not second.timestamps  # 別グループ = 別 master


def test_deduplicated_exploded_channel_pins_both_name_spaces(loaded: _Loaded) -> None:
    """dedup された展開チャンネル — 列キーは表示名から、selector は**生名**から作る (二重名の本丸)。

    ``dup`` は 1-D なので selector の側を何も言わない (列キー = 表示名そのもの)。
    展開チャンネルは ``Mat`` / ``Pos`` / ``Mix`` / ``Radar.ObjList`` / ``Nest`` の
    どれも名前が一意で、そこでも表示名 = 生名になる。**両方が同時に起きる**この腕
    だけが「selector を表示キーから導いた実装」を落とせる:

    - 列キー (表示空間): ``Mat2[0][i]`` / ``Mat2[1][i]`` — LD-08 dedup 済み表示名由来
    - selector (読み空間): ``Mat2[i]`` — 生チャンネル名由来

    表示キーから selector を導くと ``_flatten("Mat2", samples)`` のリーフに
    ``Mat2[0][i]`` は存在せず、値アクセスが ``SampleReadError`` になる。
    加えて生名 ``Mat2`` を共有する 2 本は列数 (3 / 4)・unit・値が別なので、
    生名キーの単純な Mapping で 2 本を取り違えると必ず露見する
    (``column_names.parse_leaf`` の docstring が自認する健全性の限界)。
    """

    def _resolved(column_key: str) -> Signal:
        sig = loaded.resolve(column_key)
        assert sig is not None, column_key
        return sig

    first = [_resolved(f"Mat2[0][{i}]") for i in range(3)]
    second = [_resolved(f"Mat2[1][{i}]") for i in range(4)]

    for sig in first:
        assert sig.metadata["physical_channel"] == "Mat2[0]"  # 生名 "Mat2" ではない
        assert sig.metadata["name_deduplicated"] is True
        assert sig.metadata["unit"] == "A"
    for sig in second:
        assert sig.metadata["physical_channel"] == "Mat2[1]"
        assert sig.metadata["name_deduplicated"] is True
        assert sig.metadata["unit"] == "Nm"  # 相方は "A" — 取り違えは unit で露見

    # 値 (= selector が正しいリーフを引けている唯一の証拠)
    np.testing.assert_array_equal(first[0].values, [40, 50, 60, 70])
    np.testing.assert_array_equal(second[0].values, [81, 91, 101, 111])

    # 列数が違う (3 / 4) — 生名を共有する 2 本を 1 つの spec で代表させると崩れる
    assert loaded.resolve("Mat2[0][3]") is None  # 相方の 4 列目は名乗れない

    # 生 selector 空間 (Mat2[0..3]) が表示空間へ漏れていない。漏れているなら
    # 「表示キーを生名から作った」ことの直接の証拠になる。
    for i in range(4):
        assert loaded.resolve(f"Mat2[{i}]") is None, i

    # 別グループ = 別 master (dup と同じ性質を展開チャンネルでも確認)
    assert first[0].timestamps is not second[0].timestamps


def test_nested_index_arm_is_synthetic_because_asammdf_flattens_subarrays(
    loaded: _Loaded,
) -> None:
    """``Name[i][j]`` は asammdf の public write API で往復できない (弱点の記録)。

    (2,3) のサブ配列フィールドを書いても読み戻しは (6,) へ潰れ、実測リーフは
    ``Nest.g[0..5]`` の **1 段**である。よってこの腕だけはファイル往復ではなく
    合成 ndarray で固定する — 実データで裏取りできていない事実を明示する。
    """
    assert sorted(k for k in loaded.columns if k.startswith("Nest.")) == [
        f"Nest.g[{i}]" for i in range(6)
    ]

    arr = np.zeros((4, 2, 3), dtype=np.uint8)
    arr[:] = np.arange(6, dtype=np.uint8).reshape(2, 3)
    spec = spec_from_probe(arr)
    names = list(leaf_names("W", spec))
    assert names == [f"W[{i}][{j}]" for i in range(2) for j in range(3)]
    # 生成順が _flatten と一致する (列キー空間の単一の真実)
    assert [name for name, _col in _flatten("W", arr)] == names
    for name in names:
        got = parse_leaf(name, {"W": spec})
        assert got is not None, name
        assert got[0] == "W", name
