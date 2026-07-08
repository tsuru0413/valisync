from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import CsvExporter, CsvExportOptions
from valisync.core.models import Signal


def _sig(name: str, ts: list[float], vs: list[float], unit: str = "") -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="test",
        bus_type="",
        source_file="",
        metadata={"unit": unit} if unit else {},
    )


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").splitlines()


def test_default_options_match_current_behavior(tmp_path: Path) -> None:
    s = _sig("speed", [0.0, 1.0], [1.5, 2.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)  # options 省略 = 既定
    assert _read(out) == ["timestamp,speed", "0.0,1.5", "1.0,2.5"]


def test_semicolon_delimiter(tmp_path: Path) -> None:
    s = _sig("speed", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(delimiter=";"))
    assert _read(out) == ["timestamp;speed", "0.0;1.5"]


def test_comma_decimal_with_semicolon_delimiter(tmp_path: Path) -> None:
    s = _sig("speed", [0.5], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(delimiter=";", decimal=","))
    assert _read(out) == ["timestamp;speed", "0,5;1,5"]


def test_precision_fixed_decimals(tmp_path: Path) -> None:
    s = _sig("speed", [0.0], [1.23456])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(precision=2))
    assert _read(out) == ["timestamp,speed", "0.00,1.23"]


def test_unit_row_below_header(tmp_path: Path) -> None:
    s = _sig("speed", [0.0], [1.5], unit="km/h")
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(unit_row=True))
    assert _read(out) == ["timestamp,speed", "s,km/h", "0.0,1.5"]


def test_delimiter_decimal_collision_rejected() -> None:
    with pytest.raises(ValueError):
        CsvExportOptions(delimiter=",", decimal=",")


def test_negative_precision_rejected() -> None:
    with pytest.raises(ValueError):
        CsvExportOptions(precision=-1)


def test_session_passthrough(tmp_path: Path) -> None:
    # Session.export_csv が options を CsvExporter へ渡すこと
    from valisync.core.session import Session

    out = tmp_path / "d.csv"
    Session().export_csv(
        [_sig("v", [0.0], [1.5])], out, options=CsvExportOptions(delimiter=";")
    )
    assert _read(out)[0] == "timestamp;v"
