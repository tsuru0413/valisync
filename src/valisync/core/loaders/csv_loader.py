from __future__ import annotations

import csv
import datetime
from pathlib import Path
from typing import Any

import numpy as np

from valisync.core.models import (
    Diagnostic,
    FormatDefinition,
    LoadResult,
    Signal,
    SignalGroup,
)


class CsvLoader:
    """CSV file loader. Parses according to FormatDefinition."""

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".csv"

    def load(self, file_path: Path, format_def: FormatDefinition) -> LoadResult:
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
            with open(file_path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f, delimiter=format_def.delimiter.value))
        except OSError as exc:
            return LoadResult(
                signal_group=None,
                diagnostics=(
                    Diagnostic(
                        level="error", message=f"Cannot read '{file_path.name}': {exc}"
                    ),
                ),
            )

        n_signals = format_def.signal_end_column - format_def.signal_start_column + 1
        min_cols = max(format_def.timestamp_column, format_def.signal_end_column) + 1
        row_idx = 0

        # --- Header row ---
        signal_names: list[str]
        if format_def.has_header:
            if row_idx >= len(rows):
                return LoadResult(
                    signal_group=None,
                    diagnostics=(
                        Diagnostic(
                            level="error",
                            message="Expected header row but file is empty",
                        ),
                    ),
                )
            header = rows[row_idx]
            row_idx += 1
            if len(header) < min_cols:
                return LoadResult(
                    signal_group=None,
                    diagnostics=(
                        Diagnostic(
                            level="error",
                            message=(
                                f"Header has {len(header)} columns,"
                                f" expected at least {min_cols}"
                            ),
                            line_number=row_idx,
                        ),
                    ),
                )
            signal_names = [
                header[col]
                for col in range(
                    format_def.signal_start_column, format_def.signal_end_column + 1
                )
            ]
        else:
            signal_names = [f"ch_{i + 1}" for i in range(n_signals)]

        # --- Unit row (immediately after header) ---
        unit_by_sig_idx: dict[int, str] = {}
        if format_def.has_unit_row and row_idx < len(rows):
            unit_row = rows[row_idx]
            row_idx += 1
            for sig_idx, col in enumerate(
                range(format_def.signal_start_column, format_def.signal_end_column + 1)
            ):
                if col < len(unit_row) and unit_row[col].strip():
                    unit_by_sig_idx[sig_idx] = unit_row[col].strip()

        # --- Data rows ---
        timestamps_list: list[float] = []
        values_lists: list[list[float]] = [[] for _ in range(n_signals)]

        for raw_idx, row in enumerate(rows[row_idx:], start=row_idx):
            line_number = raw_idx + 1  # 1-based for user-facing messages

            if not any(cell.strip() for cell in row):
                continue  # skip blank rows (common at end of file)

            if len(row) < min_cols:
                return LoadResult(
                    signal_group=None,
                    diagnostics=(
                        Diagnostic(
                            level="error",
                            message=(
                                f"Row has {len(row)} columns, expected at least {min_cols}"
                            ),
                            line_number=line_number,
                        ),
                    ),
                )

            ts_str = row[format_def.timestamp_column]
            try:
                ts = float(ts_str)
            except ValueError:
                return LoadResult(
                    signal_group=None,
                    diagnostics=(
                        Diagnostic(
                            level="error",
                            message=f"Non-numeric timestamp {ts_str!r}",
                            line_number=line_number,
                            column_number=format_def.timestamp_column,
                        ),
                    ),
                )
            if format_def.timestamp_unit == "msec":
                ts /= 1000.0
            timestamps_list.append(ts)

            for sig_idx, col in enumerate(
                range(format_def.signal_start_column, format_def.signal_end_column + 1)
            ):
                val_str = row[col]
                try:
                    values_lists[sig_idx].append(float(val_str))
                except ValueError:
                    return LoadResult(
                        signal_group=None,
                        diagnostics=(
                            Diagnostic(
                                level="error",
                                message=f"Non-numeric value {val_str!r} in signal column",
                                line_number=line_number,
                                column_number=col,
                            ),
                        ),
                    )

        # --- Build Signal objects ---
        timestamps = np.array(timestamps_list, dtype=np.float64)
        abs_path = str(file_path.resolve())
        signals: list[Signal] = []

        for sig_idx, name in enumerate(signal_names):
            values = np.array(values_lists[sig_idx], dtype=np.float64)
            metadata: dict[str, Any] = {}
            if sig_idx in unit_by_sig_idx:
                metadata["unit"] = unit_by_sig_idx[sig_idx]

            try:
                signal = Signal(
                    name=name,
                    timestamps=timestamps,
                    values=values,
                    file_format="CSV",
                    bus_type="",
                    source_file=abs_path,
                    metadata=metadata,
                )
                signals.append(signal)
            except ValueError as exc:
                return LoadResult(
                    signal_group=None,
                    diagnostics=(
                        Diagnostic(
                            level="error",
                            message=f"Signal '{name}' failed validation: {exc}",
                        ),
                    ),
                )

        signal_group = SignalGroup(
            signals=tuple(signals),
            source_path=file_path.resolve(),
            file_format="CSV",
            loaded_at=datetime.datetime.now(),
        )
        return LoadResult(signal_group=signal_group)
