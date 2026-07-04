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
    round-trip as 1D but fails the ``astype(float64)`` conversion.
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
