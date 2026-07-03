"""Unit tests for CsvExporter (Task 8.1, Requirements 7.1-7.7)."""

from __future__ import annotations

import numpy as np
import pytest

from valisync.core.export import CsvExporter
from valisync.core.models import Signal


def _signal(name: str, ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata={},
    )


def test_export_single_signal_writes_header_and_rows(tmp_path):
    sig = _signal("speed", [0.0, 1.0, 2.0], [10.0, 20.0, 30.0])
    out = tmp_path / "out.csv"

    CsvExporter().export([sig], out)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert (
        lines[0] == "timestamp,speed"
    )  # Req 7.2, 7.3: timestamp first col + signal name
    assert lines[1].split(",")[0] == "0.0"
    assert lines[1].split(",")[1] == "10.0"
    assert len(lines) == 4  # header + 3 data rows


def test_export_multiple_signals_share_columns(tmp_path):
    a = _signal("a", [0.0, 1.0], [1.0, 2.0])
    b = _signal("b", [0.0, 1.0], [3.0, 4.0])
    out = tmp_path / "out.csv"

    CsvExporter().export([a, b], out)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "timestamp,a,b"
    assert lines[1] == "0.0,1.0,3.0"
    assert lines[2] == "1.0,2.0,4.0"


def test_export_unified_timeline_uses_empty_cells_for_missing_samples(tmp_path):
    # a sampled at t=0,2 ; b sampled at t=1,2 -> union {0,1,2}; Req 7.4
    a = _signal("a", [0.0, 2.0], [10.0, 12.0])
    b = _signal("b", [1.0, 2.0], [21.0, 22.0])
    out = tmp_path / "out.csv"

    CsvExporter().export([a, b], out, use_unified_timeline=True)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "timestamp,a,b"
    assert lines[1] == "0.0,10.0,"  # b missing at t=0
    assert lines[2] == "1.0,,21.0"  # a missing at t=1
    assert lines[3] == "2.0,12.0,22.0"


def test_export_atomic_failure_preserves_existing_file(tmp_path, monkeypatch):
    out = tmp_path / "out.csv"
    out.write_text("ORIGINAL", encoding="utf-8")  # pre-existing content (Req 7.7)
    sig = _signal("x", [0.0, 1.0], [5.0, 6.0])

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(OSError):
        CsvExporter().export([sig], out)

    # original file untouched; no leftover temp files in the directory
    assert out.read_text(encoding="utf-8") == "ORIGINAL"
    assert [p.name for p in tmp_path.iterdir()] == ["out.csv"]


def test_export_shared_timeline_non_monotonic_sorted_rows(tmp_path):
    sig = _signal("x", [0.0, 2.0, 1.0], [10.0, 30.0, 20.0])
    out = tmp_path / "o.csv"

    CsvExporter().export([sig], out, use_unified_timeline=False)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    ts_col = [float(line.split(",")[0]) for line in lines[1:]]
    assert ts_col == sorted(ts_col)
