"""Helpers for synthesising MDF4 files in tests via asammdf's write API.

Generating files programmatically (rather than committing binary fixtures)
keeps the repo free of blobs and lets each test parametrise bus type, channel
groups and duplicate names. The bus-type constants mirror asammdf's
``Source.BUS_TYPE_*`` so the loader's CAN/Ethernet detection can be exercised;
XCP is detected from the source *name* heuristic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from asammdf import MDF
from asammdf import Signal as ASignal
from asammdf.blocks.source_utils import Source

CAN = Source.BUS_TYPE_CAN
ETHERNET = Source.BUS_TYPE_ETHERNET
NONE = Source.BUS_TYPE_NONE


def _make_source(name: str, bus_type: int | None) -> Source | None:
    if bus_type is None:
        return None
    return Source(name, "", "", Source.SOURCE_BUS, bus_type)


def write_mdf4(path: Path, channels: list[dict[str, Any]]) -> Path:
    """Write *channels* to an MDF4 file, each channel in its own channel group.

    Each channel dict supports keys: ``name`` (required), ``timestamps``,
    ``values``, ``bus_type`` (asammdf constant or None), ``source_name``,
    ``unit``, ``comment``.
    """
    mdf = MDF()
    try:
        for ch in channels:
            ts = np.asarray(ch.get("timestamps", [0.0, 1.0]), dtype=np.float64)
            vs = np.asarray(ch.get("values", [0.0, 1.0]), dtype=np.float64)
            sig = ASignal(
                samples=vs,
                timestamps=ts,
                name=ch["name"],
                unit=ch.get("unit", ""),
                comment=ch.get("comment", ""),
                source=_make_source(
                    ch.get("source_name", ch["name"]), ch.get("bus_type")
                ),
            )
            mdf.append([sig])
        mdf.save(Path(path), overwrite=True)
    finally:
        mdf.close()
    return Path(path)


def write_mdf4_non_monotonic(tmp_path: Path) -> Path:
    """Write an MDF4 file with one non-monotonic/duplicate-ts channel plus a clean one.

    asammdf's writer accepts out-of-order timestamps verbatim (no validation
    or re-sort on append), so this reproduces a real "last received wins"
    CAN-bus recording without needing raw byte fixtures or monkeypatching.
    """
    return write_mdf4(
        tmp_path / "messy.mf4",
        [
            {
                "name": "messy",
                "timestamps": [0.0, 2.0, 1.0, 1.0],
                "values": [1.0, 2.0, 3.0, 4.0],
                "bus_type": CAN,
            },
            {
                "name": "clean",
                "timestamps": [0.0, 1.0],
                "values": [5.0, 6.0],
                "bus_type": CAN,
            },
        ],
    )


def write_mdf4_non_finite_ts(tmp_path: Path) -> Path:
    """Write an MDF4 file with one NaN-timestamp channel plus a clean one.

    asammdf's writer accepts NaN timestamps verbatim (no validation on append),
    so this reproduces a corrupted time axis without raw byte fixtures — the
    loader must skip this channel with an error diagnostic (spec §7) rather
    than let a non-finite axis leak into sorted_view/downstream sorting.
    """
    return write_mdf4(
        tmp_path / "nants.mf4",
        [
            {
                "name": "broken",
                "timestamps": [0.0, float("nan"), 2.0],
                "values": [1.0, 2.0, 3.0],
                "bus_type": CAN,
            },
            {
                "name": "clean",
                "timestamps": [0.0, 1.0],
                "values": [5.0, 6.0],
                "bus_type": CAN,
            },
        ],
    )


def write_mdf4_all_channels_bad(tmp_path: Path) -> Path:
    """Write an MDF4 file whose only channel is unusable, so 0 channels survive.

    Previously used a 2D uint8 byte-array channel (``ndim == 2`` was an
    unconditional skip). LD-12 (第3弾) now explodes 2D samples into
    per-column signals instead of skipping them, so that fixture no longer
    yields an "all bad" file. A byte-string channel (non-numeric dtype)
    stays genuinely unusable regardless of LD-12 — it survives asammdf's
    round-trip as 1D but is rejected by the loader's numeric ``dtype.kind``
    gate (FU-20: non-numeric channels are skipped with a warning).
    """
    path = tmp_path / "allbad.mf4"
    mdf = MDF()
    try:
        ts = np.array([0.0, 1.0], dtype=np.float64)
        vs = np.array([b"abcd", b"efgh"], dtype="S4")
        sig = ASignal(samples=vs, timestamps=ts, name="raw_bytes", encoding="latin-1")
        mdf.append([sig])
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_value2text(tmp_path: Path) -> Path:
    """TABX (value2text) 変換付き enum チャンネル + 通常チャンネル.

    現行ローダーは value2text をテキスト化して 'non-numeric, skipped' で
    チャンネルごと落とす (LD-13)。刷新後は生値 [0,1,2,1] で生存し、
    metadata['value_labels'] に対応表が入るのが新契約。
    """
    from asammdf.blocks.conversion_utils import from_dict

    conv = from_dict(
        {
            "val_0": 0,
            "text_0": "OFF",
            "val_1": 1,
            "text_1": "LEFT",
            "val_2": 2,
            "text_2": "RIGHT",
        }
    )
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.array([0, 1, 2, 1], dtype=np.int16),
                    timestamps=ts,
                    name="TurnSig",
                    conversion=conv,
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean"
                )
            ]
        )
        path = tmp_path / "v2t.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_ttab(tmp_path: Path) -> Path:
    """TTAB (text→value) 変換付きチャンネル + 通常チャンネル.

    TTAB は value2text の**逆向き** — raw 表現がテキスト、物理値が数値。asammdf は
    ``ignore_value2text_conversions`` で TABX/RTABX/TRANS/BITFIELD を短絡するが
    ``CONVERSION_TYPE_TTAB`` には同ガードが無く (v4_blocks.py:4337)、常に
    テキスト→数値へ写す。よって ``raw=True`` プローブの dtype は ``|S8``、
    ``raw=False`` (= 本読みと同じ側) の dtype は ``float64`` になる。

    ローダーの数値性ゲートを raw プローブ側で判定すると、このチャンネルは
    「非数値型のためスキップ」で消滅する (物理サンプルは数値なので誤り)。
    ``from_dict`` は TTAB を作れないため ``ChannelConversion`` を直接組む。
    """
    from asammdf.blocks import v4_constants as v4c
    from asammdf.blocks.v4_blocks import ChannelConversion

    texts = (b"OFF", b"LEFT", b"RIGHT")
    kwargs: dict[str, Any] = {
        "conversion_type": v4c.CONVERSION_TYPE_TTAB,
        "links_nr": 4 + len(texts),  # 共通リンク 4 + text_i
        "val_default": -1.0,
    }
    for i in range(len(texts)):
        kwargs[f"text_{i}"] = 0  # リンクアドレスは save 時に解決される
        kwargs[f"val_{i}"] = float(i) * 10.0
    conv = ChannelConversion(**kwargs)
    for i, text in enumerate(texts):
        conv.referenced_blocks[f"text_{i}"] = text

    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.array([b"OFF", b"LEFT", b"RIGHT", b"LEFT"], dtype="S8"),
                    timestamps=ts,
                    name="StateTxt",
                    conversion=conv,
                    encoding="latin-1",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean"
                )
            ]
        )
        path = tmp_path / "ttab.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_linear_conversion(tmp_path: Path) -> Path:
    """線形変換 (phys = 0.01 * raw) 付き int16 チャンネル + 通常チャンネル.

    値の本読みが ``raw=False`` を落とすと生カウントが 100 倍ずれて返る — その
    サイレント破損を **CI が実行できる** 形で捕まえるための fixture
    (demo_data 依存の `test_mdf_loader_lazy` は gitignore 済みで CI では skip)。
    既存の唯一の変換 fixture ``write_mdf4_value2text`` は TABX なので
    ``ignore_value2text_conversions`` で短絡され、raw フラグに構造的に鈍感。
    """
    from asammdf.blocks.conversion_utils import from_dict

    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.array([0, 7980, -1234, 32767], dtype=np.int16),
                    timestamps=ts,
                    name="Scaled",
                    unit="km/h",
                    conversion=from_dict({"a": 0.01, "b": 0.0}),
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean"
                )
            ]
        )
        path = tmp_path / "linconv.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_shared_group(tmp_path: Path) -> Path:
    """同一チャンネルグループに 2ch (A/B, 同一時刻軸) — 共有マスタ検証用."""
    ts = np.arange(0.0, 1.0, 0.1)
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(samples=np.arange(10.0), timestamps=ts, name="A"),
                ASignal(samples=np.arange(10.0) * 2.0, timestamps=ts, name="B"),
            ]
        )  # 1回の append = 1グループ
        path = tmp_path / "shared.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_shared_group_wide(tmp_path: Path) -> Path:
    """同一チャンネルグループに単一フィールド構造化チャンネル 2ch (A/B) — ci 軸の
    キャッシュ検証用.

    ``write_mdf4_shared_group`` の非スカラー版。E-4a はスカラー (1-D 非構造化)
    チャンネルをキャッシュ対象から除外する (レビュー I4) ため、スカラーの A/B
    では ci を落とす変異 (S4) がそもそも ``ChannelSampleCache.put`` へ到達せず、
    キー計算の破壊が実害 (別チャンネルの値が返る) を生まない = テストが変異に
    盲目になる。

    **2-D を使うなら uint8 でなければ往復しない** (本ファイル冒頭の 3-D の注記と
    ``test_column_roundtrip.py`` の同旨の注記と同じ制約)。float64 の 2-D は
    **同一 append に 1 本だけでも** ``(N, w) -> (N,)`` へ潰れ、先頭 N 要素
    (= 先頭 N/w 行) だけが返る。逆に uint8 の 2-D なら**幅が違っても同一 append に
    複数混ぜて問題ない** — いずれも実測。ここで 2-D でなく単一フィールド構造化
    1-D を採るのは、``write_mdf4_shared_group`` の float64 な A/B と値の型を揃えた
    まま ``samples.dtype.names`` を truthy (= I4 のもう一方のキャッシュ対象条件)
    にできるためで、書き込みの制約が理由ではない。
    """
    ts = np.arange(0.0, 1.0, 0.1)
    a = np.array([(v,) for v in np.arange(10.0)], dtype=[("x", "<f8")])
    b = np.array([(v,) for v in np.arange(10.0) * 2.0], dtype=[("x", "<f8")])
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(samples=a, timestamps=ts, name="A"),
                ASignal(samples=b, timestamps=ts, name="B"),
            ]
        )  # 1回の append = 1グループ
        path = tmp_path / "shared_struct.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_2d_solo(path: Path, offset: int) -> Path:
    """単一の 2D チャンネル ("Mat") だけを持つ MDF4 — handle 軸のキャッシュ検証用.

    ``test_cache_key_separates_two_files_with_identical_positions`` は元々
    1-D スカラー ("Spd") の 2 ファイルだったが、E-4a がスカラーチャンネルを
    キャッシュ対象から除外する (レビュー I4) ため、handle 軸を落とす変異 (S3) が
    ``put``/``get`` を経由せずテストが盲目になる (``write_mdf4_shared_group_wide``
    と同じ理由)。1 チャンネル構成にするのは、(gi, ci) が「master 直後の唯一の
    チャンネル」として 2 ファイルで確実に一致するようにするため。``offset`` で
    2 ファイルの値を分ける (uint8 なので 0/100 程度に収める — 255 を超えない)。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mat = (
        np.array([[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]], dtype=np.uint8)
        + offset
    )
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=mat, timestamps=ts, name="Mat")])
        mdf.save(Path(path), overwrite=True)
    finally:
        mdf.close()
    return Path(path)


def write_mdf4_2d(tmp_path: Path) -> Path:
    """2D (Nx3) uint8 配列チャンネル + 通常チャンネル — LD-12 展開検証用.

    列 i の値は [i, i+10, i+20, i+30] で列ごとに識別可能。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mat = np.array(
        [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]], dtype=np.uint8
    )
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=mat, timestamps=ts, name="Mat")])
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean"
                )
            ]
        )
        path = tmp_path / "mat2d.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_wide_2d(tmp_path: Path, cols: int = 1025) -> Path:
    """幅 cols の 2D uint8 チャンネル (上限 1024 超) + 通常チャンネル — LD-14 用.

    3D は asammdf public write で round-trip 不可なので、per-channel 1024 ガードの
    end-to-end 検証は幅広 2D (列数 > 1024) で行う。列 i の 0 行目 = i%256。
    """
    ts = np.array([0.0, 0.1, 0.2], dtype=np.float64)
    mat = np.tile(np.arange(cols, dtype=np.uint8), (3, 1))  # (3, cols)
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=mat, timestamps=ts, name="Wide")])
        mdf.append(
            [ASignal(samples=np.array([1.0, 2.0, 3.0]), timestamps=ts, name="Clean")]
        )
        path = tmp_path / "wide2d.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_duplicate_wide(tmp_path: Path, cols: int = 1025) -> Path:
    """同名 "W" の 2 チャンネル (先=幅 cols の 2D / 後=スカラー) + Clean — C-f 用.

    1024 ガードが生きている間は先頭の広幅 "W" がヘッドレスで丸ごとスキップされ、
    生き残るスカラー側が LD-08 の idx 0 を取って ``W[0]`` になる。ガード退役後は
    両方が載るのでスカラーは ``W[1]`` へ動く — この永続キーの移動 (spec C-f:
    意図的リネーム・移行パスなし) を固定するための fixture。prod_demo には重複名が
    無い (scripts/generate_demo_mf4.py の全チャンネル名は一意) ため、実データでは
    この組み合わせを作れず、合成 fixture が唯一の観測点になる。

    列 j の値は j % 256 (write_mdf4_wide_2d と同じ規則) で列ごとに識別できる。
    先に append したチャンネルが小さい gi を取ることに依存する — 順序が入れ替わると
    dedup インデックスが逆になり、テストは (無言の pass ではなく) FAIL する。
    """
    ts = np.array([0.0, 0.1, 0.2], dtype=np.float64)
    mat = np.tile(np.arange(cols, dtype=np.uint8), (3, 1))  # (3, cols)
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=mat, timestamps=ts, name="W")])
        mdf.append(
            [ASignal(samples=np.array([7.0, 8.0, 9.0]), timestamps=ts, name="W")]
        )
        mdf.append(
            [ASignal(samples=np.array([1.0, 2.0, 3.0]), timestamps=ts, name="Clean")]
        )
        path = tmp_path / "dupwide.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_non_monotonic_2d(tmp_path: Path) -> Path:
    """非単調/重複タイムスタンプの 2D (Nx3) チャンネル + 同時刻軸の通常チャンネル.

    診断 fan-out 集約 (E-3) の RED fixture。列展開時代は Mat[0..2] の 3 件へ増幅
    されていた非単調警告が物理チャンネル 1 件へ畳まれること、同じ時刻軸を持つ
    1-D チャンネル (Clean) の 1 件は文言ごと不変であることを、1 ファイルで対に
    固定する (prod では 1 グループ最大 96,000 件の増幅だった)。
    """
    ts = np.array([0.0, 2.0, 1.0, 1.0], dtype=np.float64)
    mat = np.array(
        [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]], dtype=np.uint8
    )
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=mat, timestamps=ts, name="Mat")])
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean"
                )
            ]
        )
        path = tmp_path / "messy2d.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_dup_2d(tmp_path: Path) -> Path:
    """同名 (W) の 2D uint8 チャンネル 2 本 — LD-08 dedup と LD-14 展開の合成.

    ローダーの規則から、表示名は dedup 済みの ``W[0]`` / ``W[1]``、selector 側の
    リーフ名は生名由来の ``W[0]`` / ``W[1]`` (= 列インデックス) になる。**2 つのキー
    空間が同じ文字列に見えて別物**になる唯一のケースであり、鋳造がキー空間を
    取り違えると解決不能になるか別チャンネルの列を返す。

    列の値は
    ``W[0][0]=[0,2,4,6]`` / ``W[0][1]=[1,3,5,7]`` /
    ``W[1][0]=[100,102,104,106]`` / ``W[1][1]=[101,103,105,107]``
    で、どのチャンネルのどの列を読んだかが値だけで判別できる。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        for base in (0, 100):
            samples = np.array(
                [
                    [base + 0, base + 1],
                    [base + 2, base + 3],
                    [base + 4, base + 5],
                    [base + 6, base + 7],
                ],
                dtype=np.uint8,
            )
            mdf.append([ASignal(samples=samples, timestamps=ts, name="W", unit="m")])
        path = tmp_path / "dup2d.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_display_name_collision(tmp_path: Path) -> Path:
    """LD-08 の ``[i]`` 曖昧化が **実チャンネル名** と衝突する配置 — I-1 の RED fixture.

    ① 文字どおり ``W[0]`` という 1-D チャンネル (時刻軸 10..13 s・値 5..8)
    ② 同名 ``W`` の 2D uint8 チャンネル 2 本 (時刻軸 0.0..0.3 s)

    ローダーの規則から ② は ``W[0]`` / ``W[1]`` へ曖昧化され、先に登録される ① と
    表示名が衝突する。**時刻軸をわざと別にし、長さは揃える**のが要点: 衝突を通すと
    鋳造列 ``W[0][1]`` が「値は ② の列 / 時刻は ① の軸」になり、``LazyMdfValues`` の
    長さ検証 (``len(col) != length``) もすり抜ける = 例外なしの誤データ (時間軸だけ
    別チャンネル) が観測できる。

    ① を先に append するのは gi の順序 = ローダーの登録順を決めるため。列の値は
    ``write_mdf4_dup_2d`` と同じ base+offset 規則 (どの配列のどの列かが値で分かる)。
    """
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.array([5.0, 6.0, 7.0, 8.0]),
                    timestamps=np.array([10.0, 11.0, 12.0, 13.0]),
                    name="W[0]",
                )
            ]
        )
        ts = np.array([0.0, 0.1, 0.2, 0.3])
        for base in (0, 100):
            samples = np.array(
                [
                    [base + 0, base + 1],
                    [base + 2, base + 3],
                    [base + 4, base + 5],
                    [base + 6, base + 7],
                ],
                dtype=np.uint8,
            )
            mdf.append([ASignal(samples=samples, timestamps=ts, name="W")])
        path = tmp_path / "namecollide.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_single_column_shapes(tmp_path: Path) -> Path:
    """「展開したのに列が 1 本」になる 3 形状 + スカラー — C1 の RED fixture.

    ローダー実測: Mono[0] (形状 (N,1) の 2D) / P.x (単一数値フィールド構造化) /
    Q.x (数値+文字列の混在構造化 — 非数値リーフは dtype ゲートで落ちる) / Clean。
    いずれも column_count == 1 かつ orig != physical_channel なので、合成した
    base_key (g::Mono / g::P / g::Q) を葉キーにすると「見えるのに永久に
    描かれない行」になる (実 Signal として存在しない)。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.arange(4, dtype=np.uint8).reshape(4, 1),
                    timestamps=ts,
                    name="Mono",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [(1.0,), (2.0,), (3.0,), (4.0,)], dtype=[("x", "<f8")]
                    ),
                    timestamps=ts,
                    name="P",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [(1.0, b"ab"), (2.0, b"cd"), (3.0, b"ef"), (4.0, b"gh")],
                        dtype=[("x", "<f8"), ("tag", "S2")],
                    ),
                    timestamps=ts,
                    name="Q",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean"
                )
            ]
        )
        path = tmp_path / "single_cols.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_all_non_numeric_struct(tmp_path: Path) -> Path:
    """全リーフが非数値の**構造化**チャンネル + 通常チャンネル — D2 の第 3 クラス.

    E-3 の診断 supersede は 3 クラスある: (1) 全リーフ数値の容器 (warning なし)、
    (2) 混在容器 ``Q`` (旧: リーフ単位 warning 1 件 → 新: 0 件)、(3) **全リーフ
    非数値の容器**。(3) は旧コードがリーフごとに各リーフの scalar dtype で warning を
    出していたのに対し、新コードは親レベルの warning を **1 件**、しかも親の複合
    dtype で出す。既存 16 fixture のどれもこの形状を持たないため機械比較は構造的に
    盲目だった (spec D2)。``Q`` (混在) では numeric>0 なので (3) は再現できない。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [(b"ab", b"xyz"), (b"cd", b"uvw")] * 2,
                        dtype=[("tag", "S2"), ("code", "S3")],
                    ),
                    timestamps=ts,
                    name="R",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean"
                )
            ]
        )
        path = tmp_path / "allnonnum.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_interleaved_arrays(tmp_path: Path) -> Path:
    """配列 / スカラー / 配列 の順 — 列 span が連続性に依存しないことの pin.

    ローダー実測: A[0], A[1], S, B[0], B[1]。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        for name, samples in (
            ("A", np.array([[0, 1], [2, 3], [4, 5], [6, 7]], dtype=np.uint8)),
            ("S", np.array([1.0, 2.0, 3.0, 4.0])),
            ("B", np.array([[8, 9], [10, 11], [12, 13], [14, 15]], dtype=np.uint8)),
        ):
            mdf.append([ASignal(samples=samples, timestamps=ts, name=name)])
        path = tmp_path / "interleaved.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_flatten_fixture(tmp_path: Path) -> Path:
    """平坦化 realgui (E-2 Task 5) の fixture — 5 物理チャンネル / 9 列.

    ローダー実測 (実 asammdf ラウンドトリップで確認済み):
    ``ACC.Speed``, ``ACC.Accel``, ``Mat[0..2]``, ``Pos.xa``, ``Pos.xb``,
    ``Pos.yc``, ``Scalar`` — 物理チャンネルは
    ``ACC.Speed / ACC.Accel / Mat / Pos / Scalar`` の 5 本。

    狙う mutation は **_base_of によるドット分割グルーピングの復活**
    (E-2 前は orig の最初の ``[`` / ``.`` までを base にしていた)。接頭辞を共有する
    2 本 (``ACC.Speed`` / ``ACC.Accel``) が無いと SignalTreeModel._rebuild の
    単一リーフ畳み込みで旧実装でも ``"ACC.Speed"`` がトップ行に見えてしまい、
    オラクルが mutation を殺せない。2 本あれば旧実装のトップ行は ``"ACC"`` に
    なるので、期待値 ``["ACC.Speed", "ACC.Accel", ...]`` が確実に RED になる。

    ``Pos`` は「英数字だけの実打鍵で一部の列だけを絞り込む」ための構造化チャンネル
    (``x`` は他のどのチャンネル名にも現れないので 1 打鍵で ``Pos.xa`` / ``Pos.xb``
    だけが残り ``Pos.yc`` は落ちる)。記号打鍵を避けるのは
    ``ord('[') == 0x5B == VK_LWIN`` でスタートメニューが開き、以後の実クリックが
    別ウィンドウへ流れるため (共有マシン上の不透明なフレーク)。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]),
                    timestamps=ts,
                    name="ACC.Speed",
                    unit="km/h",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([5.0, 6.0, 7.0, 8.0]),
                    timestamps=ts,
                    name="ACC.Accel",
                    unit="m/s2",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]],
                        dtype=np.uint8,
                    ),
                    timestamps=ts,
                    name="Mat",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [
                            (1.0, 2.0, 3.0),
                            (4.0, 5.0, 6.0),
                            (7.0, 8.0, 9.0),
                            (10.0, 11.0, 12.0),
                        ],
                        dtype=[("xa", "<f8"), ("xb", "<f8"), ("yc", "<f8")],
                    ),
                    timestamps=ts,
                    name="Pos",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([9.0, 8.0, 7.0, 6.0]),
                    timestamps=ts,
                    name="Scalar",
                )
            ]
        )
        path = tmp_path / "flatten.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_structured(tmp_path: Path) -> Path:
    """構造化 dtype (x,y) チャンネル — フィールド展開検証用."""
    ts = np.array([0.0, 0.1, 0.2])
    rec = np.array(
        [(1.0, 10.0), (2.0, 20.0), (3.0, 30.0)], dtype=[("x", "<f8"), ("y", "<f8")]
    )
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=rec, timestamps=ts, name="Pt")])
        path = tmp_path / "struct.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_two_wide_channels(
    tmp_path: Path, rows: int = 1000, cols: int = 64
) -> Path:
    """幅 cols の 2D uint8 チャンネル 2 本 (WideA / WideB) — E-4a ①ゲート用.

    デコード済み 2-D 配列 1 本 = ``rows * cols`` バイト (uint8) と **実体サイズが既知**
    になるのが要点。E-4a の ①ゲートは LRU 予算を注入して evict を起こす (実データでは
    256 MB に広幅が ~19 本入り発火しない・spec D6) ので、予算を「1 本は載り 2 本は
    載らない」値に決めるにはエントリの実体サイズが要る。2 本あるのは「別チャンネルを
    読むと古い方が落ちる」を観測するため。

    値は ``WideA[j][r] = (r + 7j) % 251`` / ``WideB[j][r] = (r + 7j + 128) % 251``。
    どの **チャンネルのどの列** を読んだかが値だけで判別でき、位置パスが隣の列や別
    チャンネルを返す誤りを値で捕まえられる (長さも dtype も一致するので、LazyMdfValues
    の長さ検証は素通りする = 値でしか捕まらない)。251 は素数で 7 とも rows/cols とも
    互いに素なので、列間・チャンネル間の値列が偶然一致しない。
    """
    ts = np.arange(rows, dtype=np.float64) * 0.01
    r = np.arange(rows, dtype=np.int64)[:, None]
    j = np.arange(cols, dtype=np.int64)[None, :]
    mdf = MDF()
    try:
        for name, base in (("WideA", 0), ("WideB", 128)):
            samples = ((r + 7 * j + base) % 251).astype(np.uint8)
            mdf.append([ASignal(samples=samples, timestamps=ts, name=name, unit="m")])
        path = tmp_path / "twowide.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return Path(path)


# ─── 影に隠れる列 (E-4c spec §3) ──────────────────────────────────────────────
#
# 「最長一致で実チャンネルが勝ち、配列側のその列が列キーでは指せなくなる」配置。
# **loud-fail (LD-08 の [i] 曖昧化が実チャンネル名と衝突する
# write_mdf4_display_name_collision) とは別レジーム**である: あちらは表示名が
# 完全一致してチャンネルが 1 本まるごと拒否されるが、こちらは表示名がすべて
# 一意で誰も拒否されず、**配列の 1 列だけが静かに到達不能になる**。

_SHADOW_TS = np.array([0.0, 0.1, 0.2, 0.3])
# 列 i の値は [i, i+10, i+20, i+30] (write_mdf4_2d と同じ規則)。
_SHADOW_MAT = np.array(
    [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]], dtype=np.uint8
)


def _shadow_file(tmp_path: Path, name: str, scalar_name: str) -> Path:
    """幅 3 の 2-D ``Mat`` + 1-D ``scalar_name`` + ``Clean`` を書く共有本体。

    ``scalar_name`` を ``Mat[0]`` にすると衝突、``Mat[7]`` にすると範囲外
    (到達不能列が存在しない) — 2 つの fixture の差はその 1 点だけなので、
    「衝突あり/なし」の対照が名前 1 つの差に凝縮される。

    1-D 側は dtype (float64 vs uint8)・unit (deg vs mm)・値をすべて親と別に
    しておく: どちらが勝ったかを取り違えたら必ず露見する。
    """
    mdf = MDF(version="4.10")
    try:
        # 追加順は契約の一部: 配列 ``Mat`` を**先**に置く。実チャンネルが後から
        # 来ても最長一致で勝つ (順序に依存しない) ことが検出側の前提。
        mdf.append(
            [ASignal(samples=_SHADOW_MAT, timestamps=_SHADOW_TS, name="Mat", unit="mm")]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([7.0, 8.0, 9.0, 10.0]),
                    timestamps=_SHADOW_TS,
                    name=scalar_name,
                    unit="deg",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]),
                    timestamps=_SHADOW_TS,
                    name="Clean",
                )
            ]
        )
        path = tmp_path / name
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_shadowed_leaf(tmp_path: Path) -> Path:
    """配列 ``Mat`` (3 列) と実チャンネル ``Mat[0]`` の共存 — 衝突 1 件の RED fixture."""
    return _shadow_file(tmp_path, "shadowed.mf4", "Mat[0]")


def write_mdf4_out_of_range_leaf_name(tmp_path: Path) -> Path:
    """配列 ``Mat`` (3 列) と実チャンネル ``Mat[7]`` — **範囲外なので衝突 0 件**.

    ``Mat[7]`` は字面こそ配列のリーフ名の形だが、幅 3 の配列に第 7 列は無い。
    到達不能になる列が存在しないので診断も出してはならない (spec §3.2)。
    """
    return _shadow_file(tmp_path, "out_of_range.mf4", "Mat[7]")


def write_mdf4_shadowed_leaf_at_last_valid_index(tmp_path: Path) -> Path:
    """配列 ``Mat`` (3 列: 添字 0-2) と実チャンネル ``Mat[2]`` (最後の有効添字) — 衝突 1 件.

    ``write_mdf4_out_of_range_leaf_name_at_boundary`` (``Mat[3]``) と対にして
    ``parse_leaf`` の範囲チェック ``index < spec.axis_len`` の上限をちょうど
    挟み撃ちする。``Mat[7]`` のような遠い範囲外では ``<=`` への劣化変異を
    検出できない (7 は axis_len=3 よりずっと大きいので劣化しても引っかからない)。
    """
    return _shadow_file(tmp_path, "shadowed_last_index.mf4", "Mat[2]")


def write_mdf4_out_of_range_leaf_name_at_boundary(tmp_path: Path) -> Path:
    """配列 ``Mat`` (3 列) と実チャンネル ``Mat[3]`` (添字がちょうど 1 つ外) — 衝突 0 件.

    ``Mat[3]`` は axis_len (3) と数値が一致するため、範囲チェックが
    ``index < axis_len`` から ``index <= axis_len`` へ劣化した場合に唯一
    誤って通ってしまう値。``write_mdf4_shadowed_leaf_at_last_valid_index``
    (``Mat[2]``) と対で境界を固定する。
    """
    return _shadow_file(tmp_path, "out_of_range_boundary.mf4", "Mat[3]")


def write_mdf4_multistage_shadow(tmp_path: Path) -> Path:
    """多段名の衝突 2 件 — 判定が ``parse_leaf`` と同じ walk を使う証拠.

    1. ``W[0][1]``: 同名 ``W`` の 2-D が LD-08 で ``W[0]``/``W[1]`` へ曖昧化された
       うえで、文字どおり ``W[0][1]`` という 1-D 実チャンネルが同居する。親の
       **表示名** (``W[0]``) と **生名** (``W``) が食い違う唯一の腕で、判定が
       ``raw_base_name`` を使わずに表示名で ``parse_leaf`` を引くと解決不能に
       落ちて検出が消える (二重名の契約)。
    2. ``Nest.g[3]``: 構造化フィールド + 配列添字の **2 段**サフィックス。
       ``parse_leaf`` の struct 分岐と array 分岐を両方通らないと検出できない。

    ``Nest`` の (2,3) サブ配列が読み戻しで (6,) に潰れるのは asammdf の既知挙動
    (``test_column_roundtrip.py`` の同旨の注記) — リーフは ``Nest.g[0..5]`` の
    **1 段**になるので、``[3]`` は実在する位置である。
    """
    n = len(_SHADOW_TS)
    nested = np.zeros(n, dtype=np.dtype([("g", "<u1", (2, 3))]))
    for k in range(n):
        nested["g"][k] = np.arange(6, dtype=np.uint8).reshape(2, 3) + 10 * k
    mdf = MDF(version="4.10")
    try:
        # 実チャンネル "W[0][1]" を親 "W" (この下の2回の append) より**先**に置く
        # のが本 fixture の唯一のゲート: 検出は load() の**末尾**で
        # column_records 確定後に全実チャンネルを走査する設計 (spec §3.4) なので、
        # 追加順に関わらず両方が確定済みの状態で判定できる。もし検出が group 単位
        # の**都度**判定 (group-tail) に退行していたら、"W[0][1]" 登録時点では
        # まだ "W" が存在せず衝突を見逃す — この順序を親→子に並べ替えると、
        # group-tail 退行でも「たまたま」拾えてしまい被覆が無言で消える。
        mdf.append(
            [
                ASignal(
                    samples=np.array([5.0, 6.0, 7.0, 8.0]),
                    timestamps=_SHADOW_TS,
                    name="W[0][1]",
                    unit="deg",
                )
            ]
        )
        for base in (0, 100):
            samples = np.array(
                [
                    [base + 0, base + 1],
                    [base + 2, base + 3],
                    [base + 4, base + 5],
                    [base + 6, base + 7],
                ],
                dtype=np.uint8,
            )
            mdf.append(
                [ASignal(samples=samples, timestamps=_SHADOW_TS, name="W", unit="m")]
            )
        mdf.append([ASignal(nested, _SHADOW_TS, name="Nest")])
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.5, 2.5, 3.5, 4.5]),
                    timestamps=_SHADOW_TS,
                    name="Nest.g[3]",
                    unit="V",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]),
                    timestamps=_SHADOW_TS,
                    name="Clean",
                )
            ]
        )
        path = tmp_path / "multistage.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf3(tmp_path: Path, version: str = "3.30") -> Path:
    """asammdf で MDF 3.x 実ファイルを書き出す (LD-02 の版横断読み取り検証用)."""
    t = np.arange(0.0, 5.0, 0.1, dtype=np.float64)
    mdf = MDF(version=version)
    try:
        mdf.append(
            [ASignal(samples=np.sin(t).astype(np.float64), timestamps=t, name="Sine3x")]
        )
        path = tmp_path / "signal_mdf3.mdf"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path
