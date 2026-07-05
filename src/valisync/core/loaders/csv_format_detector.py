from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from valisync.core.models.format_def import Delimiter, FormatDefinition

# 時間列とみなすヘッダ名 (完全一致 or "time" 前方一致)。
_TIME_NAME_HINTS = frozenset({"time", "timestamp", "t", "時刻", "sec", "msec", "ms"})
_DELIMITER_CANDIDATES = (
    Delimiter.COMMA,
    Delimiter.TAB,
    Delimiter.SEMICOLON,
    Delimiter.SPACE,
)


@dataclass(frozen=True)
class DetectedFormat:
    """CSV 検出結果。format は妥当なら FormatDefinition、不能なら None。

    プリフィル用フィールド (delimiter 以下) は format=None でも埋める。
    preview_lines は生の先頭行 (ダイアログで区切り変更時にライブ再分割するため)。
    """

    format: FormatDefinition | None
    name: str
    delimiter: Delimiter
    has_header: bool
    has_unit_row: bool
    timestamp_column: int
    timestamp_unit: str
    signal_start_column: int
    signal_end_column: int
    preview_lines: tuple[str, ...]
    notes: tuple[str, ...]


def split_line(line: str, delimiter: Delimiter) -> list[str]:
    """行を区切り文字で分割する (検出器とダイアログで共有)。"""
    return line.split(delimiter.value)


def _is_number(cell: str) -> bool:
    try:
        float(cell.strip())
    except ValueError:
        return False
    return True


def _row_all_nonnumeric(row: list[str]) -> bool:
    nonempty = [c for c in row if c.strip() != ""]
    return bool(nonempty) and all(not _is_number(c) for c in nonempty)


def _column_numeric(data_rows: list[list[str]], col: int) -> bool:
    vals = [r[col] for r in data_rows if col < len(r) and r[col].strip() != ""]
    if not vals:
        return False
    numeric = sum(1 for v in vals if _is_number(v))
    return numeric >= max(1, int(len(vals) * 0.8))


def _column_monotonic(data_rows: list[list[str]], col: int) -> bool:
    vals: list[float] = []
    for r in data_rows:
        if col >= len(r) or not _is_number(r[col]):
            return False
        vals.append(float(r[col]))
    return len(vals) >= 2 and all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))


class CsvFormatDetector:
    """CSV 先頭行から FormatDefinition を推定する (LD-01)。純粋・Qt-free。"""

    def detect(self, file_path: Path, *, max_rows: int = 50) -> DetectedFormat:
        lines = self._read_lines(file_path, max_rows)
        name = file_path.stem[:64] or "csv"
        if not lines:
            return self._undetectable(name, (), ("ファイルが空です",))

        delimiter = self._sniff_delimiter(lines)
        rows = [split_line(line, delimiter) for line in lines]
        n_cols = max((len(r) for r in rows), default=0)
        if n_cols < 1:
            return self._undetectable(
                name,
                tuple(lines[:10]),
                ("列を検出できません",),
            )

        has_header = _row_all_nonnumeric(rows[0])
        has_unit_row = has_header and len(rows) > 1 and _row_all_nonnumeric(rows[1])
        data_start = (2 if has_unit_row else 1) if has_header else 0
        data_rows = rows[data_start:]
        if not data_rows:
            return self._undetectable(
                name,
                tuple(lines[:10]),
                ("データ行がありません",),
            )

        header_names = rows[0] if has_header else []
        ts_col = self._detect_timestamp_column(header_names, data_rows, n_cols)

        notes: list[str] = []
        numeric_cols = [
            c for c in range(n_cols) if c != ts_col and _column_numeric(data_rows, c)
        ]
        if numeric_cols:
            sig_start, sig_end = min(numeric_cols), max(numeric_cols)
        else:
            sig_start = 0 if ts_col != 0 else 1
            sig_end = n_cols - 1
            notes.append("信号列を数値から特定できませんでした")

        notes.append("時間単位は sec と仮定しています。確認してください")
        fmt = self._try_build(
            name,
            delimiter,
            ts_col,
            "sec",
            sig_start,
            sig_end,
            has_header,
            has_unit_row,
            notes,
        )
        return DetectedFormat(
            format=fmt,
            name=name,
            delimiter=delimiter,
            has_header=has_header,
            has_unit_row=has_unit_row,
            timestamp_column=ts_col,
            timestamp_unit="sec",
            signal_start_column=sig_start,
            signal_end_column=sig_end,
            preview_lines=tuple(lines[:10]),
            notes=tuple(notes),
        )

    def _read_lines(self, file_path: Path, max_rows: int) -> list[str]:
        lines: list[str] = []
        with file_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            for i, line in enumerate(fh):
                if i >= max_rows:
                    break
                lines.append(line.rstrip("\r\n"))
        while lines and lines[-1].strip() == "":
            lines.pop()
        return lines

    def _sniff_delimiter(self, lines: list[str]) -> Delimiter:
        sample = "\n".join(lines[:20])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t ")
            for cand in _DELIMITER_CANDIDATES:
                if cand.value == dialect.delimiter:
                    return cand
        except csv.Error:
            pass
        best, best_score = Delimiter.COMMA, -1.0
        for cand in _DELIMITER_CANDIDATES:
            counts = [len(line.split(cand.value)) for line in lines if line.strip()]
            if not counts:
                continue
            maxc = max(counts)
            if maxc <= 1:
                continue
            consistency = sum(1 for c in counts if c == maxc) / len(counts)
            score = consistency * maxc
            if score > best_score:
                best, best_score = cand, score
        return best

    def _detect_timestamp_column(
        self, header_names: list[str], data_rows: list[list[str]], n_cols: int
    ) -> int:
        for c in range(n_cols):
            if c < len(header_names):
                nm = header_names[c].strip().lower()
                if nm in _TIME_NAME_HINTS or nm.startswith("time"):
                    return c
        for c in range(n_cols):
            if _column_monotonic(data_rows, c):
                return c
        return 0

    def _try_build(
        self,
        name: str,
        delimiter: Delimiter,
        ts_col: int,
        unit: str,
        sig_start: int,
        sig_end: int,
        has_header: bool,
        has_unit_row: bool,
        notes: list[str],
    ) -> FormatDefinition | None:
        try:
            return FormatDefinition(
                name=name,
                delimiter=delimiter,
                timestamp_column=ts_col,
                timestamp_unit=unit,
                signal_start_column=sig_start,
                signal_end_column=sig_end,
                has_header=has_header,
                has_unit_row=has_unit_row,
            )
        except ValueError as exc:
            notes.append(f"自動構築に失敗: {exc}")
            return None

    def _undetectable(
        self, name: str, preview: tuple[str, ...], notes: tuple[str, ...]
    ) -> DetectedFormat:
        return DetectedFormat(
            format=None,
            name=name,
            delimiter=Delimiter.COMMA,
            has_header=False,
            has_unit_row=False,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            preview_lines=preview,
            notes=notes,
        )
