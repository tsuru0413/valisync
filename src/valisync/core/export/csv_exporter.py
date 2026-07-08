from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from valisync.core.models import Signal

#: Header name for the leading timestamp column (Req 7.3).
_TIMESTAMP_HEADER = "timestamp"
#: 単位行を出力するときのタイムスタンプ列の単位(コアは秒に正規化済み)。
_TIMESTAMP_UNIT = "s"


@dataclass(frozen=True)
class CsvExportOptions:
    """CSV 書式オプション。既定は現行挙動(round-trip・カンマ・単位行なし)。"""

    delimiter: str = ","
    decimal: str = "."
    unit_row: bool = False
    precision: int | None = None

    def __post_init__(self) -> None:
        # 区切りと小数点が同一だと CSV が曖昧になる(ダイアログでも防ぐが核でも拒否)。
        if self.delimiter == self.decimal:
            raise ValueError("delimiter と decimal に同じ文字は使えません")
        if self.precision is not None and self.precision < 0:
            raise ValueError("precision は 0 以上または None")


def _fmt(value: float, options: CsvExportOptions) -> str:
    """値を書式化。precision=None は round-trip(repr)、指定時は固定小数桁。"""
    if options.precision is None:
        s = repr(float(value))  # 再パースで float64 を厳密復元
    else:
        s = f"{float(value):.{options.precision}f}"
    if options.decimal != ".":
        s = s.replace(".", options.decimal)
    return s


class CsvExporter:
    """CSV exporter. Writes Signal data as a single CSV file.

    Columns are the timestamp (first) followed by one column per Signal value
    (Req 7.2, 7.3). Writing is atomic (Req 7.7). Formatting is governed by
    :class:`CsvExportOptions`; the default reproduces the original behavior.
    """

    def export(
        self,
        signals: list[Signal],
        output_path: Path,
        use_unified_timeline: bool = False,
        options: CsvExportOptions | None = None,
    ) -> None:
        opts = options if options is not None else CsvExportOptions()
        if use_unified_timeline:
            rows = self._rows_unified_timeline(signals, opts)
        else:
            rows = self._rows_shared_timeline(signals, opts)
        self._atomic_write(Path(output_path), rows)

    def _header_rows(self, signals: list[Signal], opts: CsvExportOptions) -> list[str]:
        """ヘッダ行(+ unit_row 指定時は単位行)を返す。"""
        names = [s.name for s in signals]
        lines = [opts.delimiter.join([_TIMESTAMP_HEADER, *names])]
        if opts.unit_row:
            units = [s.metadata.get("unit", "") for s in signals]
            lines.append(opts.delimiter.join([_TIMESTAMP_UNIT, *units]))
        return lines

    def _rows_unified_timeline(
        self, signals: list[Signal], opts: CsvExportOptions
    ) -> list[str]:
        """Align all signals onto the sorted union of their timestamps (Req 7.4)."""
        views = [s.sorted_view() for s in signals]
        unified = np.unique(np.concatenate([ts for ts, _vs in views]))
        lookups = [dict(zip(ts.tolist(), vs.tolist(), strict=True)) for ts, vs in views]

        lines = self._header_rows(signals, opts)
        for ts in unified.tolist():
            cells = [_fmt(ts, opts)]
            cells.extend(_fmt(lk[ts], opts) if ts in lk else "" for lk in lookups)
            lines.append(opts.delimiter.join(cells))
        return lines

    def _rows_shared_timeline(
        self, signals: list[Signal], opts: CsvExportOptions
    ) -> list[str]:
        """Build CSV lines assuming all signals share one timestamp axis."""
        timestamps = signals[0].sorted_view()[0]
        sorted_values = [s.sorted_view()[1] for s in signals]
        lines = self._header_rows(signals, opts)
        for i in range(len(timestamps)):
            cells = [_fmt(timestamps[i], opts)]
            cells.extend(_fmt(vs[i], opts) for vs in sorted_values)
            lines.append(opts.delimiter.join(cells))
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
