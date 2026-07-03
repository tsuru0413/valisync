from __future__ import annotations

import csv
import datetime
import math
from collections.abc import Callable
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
from valisync.core.models.load_result import LoadCancelled


class CsvLoader:
    """CSV file loader. Parses according to FormatDefinition."""

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".csv"

    def load(
        self,
        file_path: Path,
        format_def: FormatDefinition,
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
        diagnostics: list[Diagnostic] = []

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

        # LD-08: 重複ヘッダは MDF4 と同一の name[idx] 方式で曖昧化(取り違え防止)
        name_total: dict[str, int] = {}
        for n in signal_names:
            name_total[n] = name_total.get(n, 0) + 1
        if any(c > 1 for c in name_total.values()):
            name_seen: dict[str, int] = {}
            renamed: list[str] = []
            for n in signal_names:
                idx = name_seen.get(n, 0)
                name_seen[n] = idx + 1
                renamed.append(f"{n}[{idx}]" if name_total[n] > 1 else n)
            dups = sorted(n for n, c in name_total.items() if c > 1)
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    message=f"重複ヘッダ {', '.join(dups)} を連番で改名（name[idx] 方式）",  # noqa: RUF001
                )
            )
            signal_names = renamed

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
        nonfinite_counts: dict[int, int] = {}

        data_start = row_idx  # header/unit rows already consumed; first data row
        for raw_idx, row in enumerate(rows[row_idx:], start=row_idx):
            # 1000 データ行ごとの協調的キャンセル確認(毎行だとオーバーヘッド・spec
            # §4.1)。ヘッダー/単位行の有無で raw_idx のオフセットが変わるため、
            # 判定はデータ行の相対位置(先頭データ行を含む)で行う。
            if cancel is not None and (raw_idx - data_start) % 1000 == 0 and cancel():
                raise LoadCancelled(f"load cancelled: {file_path.name}")
            line_number = raw_idx + 1  # 1-based for user-facing messages

            if not any(cell.strip() for cell in row):
                continue  # skip blank rows (common at end of file)

            if len(row) < min_cols:
                return LoadResult(
                    signal_group=None,
                    diagnostics=(
                        *diagnostics,
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
                        *diagnostics,
                        Diagnostic(
                            level="error",
                            message=f"Non-numeric timestamp {ts_str!r}",
                            line_number=line_number,
                            column_number=format_def.timestamp_column,
                        ),
                    ),
                )
            if not math.isfinite(ts):
                # 非有限タイムスタンプは値の nan/inf(LD-06)と違い時刻軸そのものが
                # 破損するため受け入れ不能(sorted_view の単調前提が壊れる)
                return LoadResult(
                    signal_group=None,
                    diagnostics=(
                        *diagnostics,
                        Diagnostic(
                            level="error",
                            message=f"非有限タイムスタンプ {ts_str!r}（時刻軸が破損）",  # noqa: RUF001
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
                    val = float(val_str)
                except ValueError:
                    return LoadResult(
                        signal_group=None,
                        diagnostics=(
                            *diagnostics,
                            Diagnostic(
                                level="error",
                                message=f"Non-numeric value {val_str!r} in signal column",
                                line_number=line_number,
                                column_number=col,
                            ),
                        ),
                    )
                # LD-06: nan/inf は欠測として正当なので受け入れ、件数だけ集計する
                if not math.isfinite(val):
                    nonfinite_counts[sig_idx] = nonfinite_counts.get(sig_idx, 0) + 1
                values_lists[sig_idx].append(val)

        # --- Build Signal objects ---
        timestamps = np.array(timestamps_list, dtype=np.float64)
        abs_path = str(file_path.resolve())

        # LD-04: 非単調/重複はファイル単位で1件の warning(全列が同一時間軸)
        diffs = np.diff(timestamps)
        n_backward = int(np.sum(diffs < 0))
        n_dup = int(np.sum(diffs == 0))
        if n_backward or n_dup:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    message=(
                        f"タイムスタンプ列: 非単調 {n_backward} 箇所・"
                        f"重複 {n_dup} 点（表示/演算は整列ビューで補正）"  # noqa: RUF001
                    ),
                )
            )

        # LD-09: ヘッダのみ(データ行 0)は成功+warning
        if len(timestamps) == 0:
            diagnostics.append(
                Diagnostic(level="warning", message="データ行が 0 行です")
            )

        signals: list[Signal] = []
        for sig_idx, name in enumerate(signal_names):
            values = np.array(values_lists[sig_idx], dtype=np.float64)
            metadata: dict[str, Any] = {}
            if sig_idx in unit_by_sig_idx:
                metadata["unit"] = unit_by_sig_idx[sig_idx]
            # LD-06: 非有限値は受け入れ(NaN は欠測として正当)・件数を可視化
            if nonfinite_counts.get(sig_idx):
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"'{name}': 非有限値 {nonfinite_counts[sig_idx]} 個"
                            "（'nan'/'inf' 文字列由来）"  # noqa: RUF001
                        ),
                        signal_name=name,
                    )
                )
            signals.append(
                Signal(
                    name=name,
                    timestamps=timestamps,
                    values=values,
                    file_format="CSV",
                    bus_type="",
                    source_file=abs_path,
                    metadata=metadata,
                )
            )

        signal_group = SignalGroup(
            signals=tuple(signals),
            source_path=file_path.resolve(),
            file_format="CSV",
            loaded_at=datetime.datetime.now(),
        )
        return LoadResult(signal_group=signal_group, diagnostics=tuple(diagnostics))
