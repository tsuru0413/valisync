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
