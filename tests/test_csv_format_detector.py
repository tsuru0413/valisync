from __future__ import annotations

from pathlib import Path

from valisync.core.loaders.csv_format_detector import (
    CsvFormatDetector,
    split_line,
)
from valisync.core.models.format_def import Delimiter


def _w(tmp_path: Path, text: str, name: str = "d.csv") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_detect_comma_header_signals(tmp_path: Path) -> None:
    d = CsvFormatDetector().detect(
        _w(tmp_path, "t,speed,rpm\n0.0,1.0,10\n1.0,2.0,20\n")
    )
    assert d.format is not None
    assert d.delimiter is Delimiter.COMMA
    assert d.has_header is True
    assert d.timestamp_column == 0
    assert d.signal_start_column == 1 and d.signal_end_column == 2
    assert d.timestamp_unit == "sec"


def test_detect_semicolon_no_header(tmp_path: Path) -> None:
    d = CsvFormatDetector().detect(_w(tmp_path, "0.0;1.0\n1.0;2.0\n2.0;3.0\n"))
    assert d.delimiter is Delimiter.SEMICOLON
    assert d.has_header is False
    assert d.timestamp_column == 0


def test_detect_tab_delimiter(tmp_path: Path) -> None:
    d = CsvFormatDetector().detect(_w(tmp_path, "time\tv\n0\t1\n1\t2\n"))
    assert d.delimiter is Delimiter.TAB
    assert d.timestamp_column == 0  # 名前ヒント "time"


def test_detect_unit_row(tmp_path: Path) -> None:
    text = "time,speed\ns,km/h\n0.0,10\n1.0,20\n"
    d = CsvFormatDetector().detect(_w(tmp_path, text))
    assert d.has_header is True
    assert d.has_unit_row is True


def test_detect_timestamp_by_name_not_first_column(tmp_path: Path) -> None:
    text = "idx,time,v\n0,0.0,10\n1,1.0,20\n"
    d = CsvFormatDetector().detect(_w(tmp_path, text))
    assert d.timestamp_column == 1  # "time" 列を優先


def test_invalid_single_column_yields_format_none(tmp_path: Path) -> None:
    # 1 列のみ: ts=0 で信号列範囲が作れず不変条件違反 → format=None、notes 付き。
    d = CsvFormatDetector().detect(_w(tmp_path, "0.0\n1.0\n2.0\n"))
    assert d.format is None
    assert d.notes


def test_undetectable_empty_file(tmp_path: Path) -> None:
    d = CsvFormatDetector().detect(_w(tmp_path, ""))
    assert d.format is None
    assert d.notes


def test_split_line_helper() -> None:
    assert split_line("a,b,c", Delimiter.COMMA) == ["a", "b", "c"]
    assert split_line("a\tb", Delimiter.TAB) == ["a", "b"]
