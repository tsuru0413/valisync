from __future__ import annotations

import datetime
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from asammdf import MDF

from valisync.core.models import Diagnostic, LoadResult, Signal, SignalGroup
from valisync.core.models.load_result import LoadCancelled

# Maps asammdf BusType int values to Signal.bus_type strings.
# asammdf v4_constants.BusType: CAN=2, ETHERNET=7.
_BUS_TYPE_MAP: dict[int, str] = {
    2: "CAN",
    7: "Ethernet",
}


def _detect_bus_type(source: Any) -> str:
    if source is None:
        return ""
    # XCP runs over various buses; detect by source name heuristic
    if "xcp" in (getattr(source, "name", "") or "").lower():
        return "XCP"
    return _BUS_TYPE_MAP.get(getattr(source, "bus_type", 0), "")


def _extract_metadata(asammdf_sig: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if asammdf_sig.unit:
        meta["unit"] = asammdf_sig.unit
    if asammdf_sig.comment:
        meta["comment"] = asammdf_sig.comment
    display_name = getattr(asammdf_sig, "display_name", None)
    if display_name:
        meta["display_name"] = display_name
    source = getattr(asammdf_sig, "source", None)
    if source is not None:
        meta["channel_group_name"] = getattr(source, "path", "") or ""
        meta["source_bus_type"] = getattr(source, "bus_type", 0)
        meta["source_name"] = getattr(source, "name", "") or ""
    conversion = getattr(asammdf_sig, "conversion", None)
    if conversion is not None:
        meta["conversion_info"] = str(conversion)
    return meta


class Mdf4Loader:
    """MDF4 file loader using asammdf. Reads all channel groups in one pass."""

    _READ_OPTIONS: ClassVar[dict[str, Any]] = {
        "time_from_zero": False,
        "ignore_value2text_conversions": True,
    }

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".mf4"

    def load(
        self,
        file_path: Path,
        cancel: Callable[[], bool] | None = None,
    ) -> LoadResult:
        if not file_path.exists() or not file_path.is_file():
            return LoadResult(
                signal_group=None,
                diagnostics=(
                    Diagnostic(
                        level="error",
                        message=f"File not found or not accessible: {file_path}",
                    ),
                ),
            )

        try:
            mdf = MDF(str(file_path), **self._READ_OPTIONS)
        except Exception as exc:
            return LoadResult(
                signal_group=None,
                diagnostics=(
                    Diagnostic(
                        level="error",
                        message=f"Failed to parse MDF4 '{file_path.name}': {exc}",
                    ),
                ),
            )

        try:
            # skip_master=True: exclude time-axis channels from signal iteration.
            # copy_master=True: materialize timestamps as numpy arrays before close().
            # Channel data reads are the dominant cost, so accumulate one channel
            # at a time to allow a cooperative-cancel check per channel (spec §4.1).
            raw = []
            for ch in mdf.iter_channels(skip_master=True, copy_master=True):
                if cancel is not None and cancel():
                    raise LoadCancelled(f"load cancelled: {file_path.name}")
                raw.append(ch)
        except LoadCancelled:
            # Must not be swallowed by the broad except below (LoadCancelled is
            # an Exception too) — propagate so the caller sees a cancel, not a
            # generic "failed to read channels" diagnostic.
            raise
        except Exception as exc:
            return LoadResult(
                signal_group=None,
                diagnostics=(
                    Diagnostic(
                        level="error",
                        message=f"Failed to read channels from '{file_path.name}': {exc}",
                    ),
                ),
            )
        finally:
            mdf.close()

        # Count total occurrences per base name for duplicate disambiguation
        name_total: dict[str, int] = {}
        for s in raw:
            name_total[s.name] = name_total.get(s.name, 0) + 1

        name_seen: dict[str, int] = {}
        signals: list[Signal] = []
        diagnostics: list[Diagnostic] = []
        abs_path = str(file_path.resolve())

        for asammdf_sig in raw:
            if cancel is not None and cancel():
                raise LoadCancelled(f"load cancelled: {file_path.name}")
            base_name = asammdf_sig.name
            idx = name_seen.get(base_name, 0)
            name_seen[base_name] = idx + 1
            signal_name = (
                f"{base_name}[{idx}]" if name_total[base_name] > 1 else base_name
            )

            samples = asammdf_sig.samples
            if samples.ndim != 1:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"Signal '{base_name}' has {samples.ndim}D samples"
                            " (expected 1D), skipped"
                        ),
                    )
                )
                continue

            try:
                timestamps = asammdf_sig.timestamps.astype(np.float64)
                values = samples.astype(np.float64)
            except (ValueError, TypeError) as exc:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=f"Signal '{base_name}' has non-numeric values, skipped: {exc}",
                    )
                )
                continue

            try:
                signal = Signal(
                    name=signal_name,
                    timestamps=timestamps,
                    values=values,
                    file_format="MDF4",
                    bus_type=_detect_bus_type(getattr(asammdf_sig, "source", None)),
                    source_file=abs_path,
                    metadata=_extract_metadata(asammdf_sig),
                )
                signals.append(signal)
            except ValueError as exc:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=f"Signal '{signal_name}' failed validation, skipped: {exc}",
                    )
                )

        signal_group = SignalGroup(
            signals=tuple(signals),
            source_path=file_path.resolve(),
            file_format="MDF4",
            loaded_at=datetime.datetime.now(),
        )
        return LoadResult(signal_group=signal_group, diagnostics=tuple(diagnostics))
