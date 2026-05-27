from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np

from valisync.core.models import Signal

#: Header name for the leading timestamp column (Req 7.3).
_TIMESTAMP_HEADER = "timestamp"


def _fmt(value: float) -> str:
    """Round-trippable float formatting (recovers the exact float64 on re-parse)."""
    return repr(float(value))


class CsvExporter:
    """CSV exporter. Writes Signal data as a single CSV file.

    Columns are the timestamp (first) followed by one column per Signal value
    (Req 7.2, 7.3). Writing is atomic: output is staged in a temporary file and
    renamed into place, so a failure never leaves a partial file (Req 7.7).
    """

    def export(
        self,
        signals: list[Signal],
        output_path: Path,
        use_unified_timeline: bool = False,
    ) -> None:
        if use_unified_timeline:
            rows = self._rows_unified_timeline(signals)
        else:
            rows = self._rows_shared_timeline(signals)
        self._atomic_write(Path(output_path), rows)

    def _rows_unified_timeline(self, signals: list[Signal]) -> list[str]:
        """Align all signals onto the sorted union of their timestamps (Req 7.4).

        A signal that has no sample at a given unified timestamp yields an empty
        cell (no interpolation).
        """
        names = [s.name for s in signals]
        header = ",".join([_TIMESTAMP_HEADER, *names])

        unified = np.unique(np.concatenate([s.timestamps for s in signals]))
        # Per-signal lookup from exact timestamp to value.
        lookups = [
            dict(zip(s.timestamps.tolist(), s.values.tolist(), strict=True))
            for s in signals
        ]

        lines = [header]
        for ts in unified.tolist():
            cells = [_fmt(ts)]
            cells.extend(_fmt(lk[ts]) if ts in lk else "" for lk in lookups)
            lines.append(",".join(cells))
        return lines

    def _rows_shared_timeline(self, signals: list[Signal]) -> list[str]:
        """Build CSV lines assuming all signals share one timestamp axis."""
        names = [s.name for s in signals]
        header = ",".join([_TIMESTAMP_HEADER, *names])
        timestamps = signals[0].timestamps
        lines = [header]
        for i in range(len(timestamps)):
            cells = [_fmt(timestamps[i])]
            cells.extend(_fmt(s.values[i]) for s in signals)
            lines.append(",".join(cells))
        return lines

    def _atomic_write(self, output_path: Path, lines: list[str]) -> None:
        """Write lines to a temp file in the target dir, then atomically rename."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(output_path.parent), prefix=".tmp_", suffix=".csv"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write("\n".join(lines))
                f.write("\n")
            os.replace(tmp_name, output_path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
