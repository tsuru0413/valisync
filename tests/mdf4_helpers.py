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

    A byte-array channel (2D uint8 samples) round-trips through asammdf as
    ``ch.samples.ndim == 2``, which ``Mdf4Loader`` already skips as non-1D —
    this exercises the "0 channels" path without needing a corrupt file.
    """
    path = tmp_path / "allbad.mf4"
    mdf = MDF()
    try:
        ts = np.array([0.0, 1.0], dtype=np.float64)
        vs = np.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype=np.uint8)
        sig = ASignal(samples=vs, timestamps=ts, name="raw_bytes")
        mdf.append([sig])
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path
