"""Unit tests for CsvLoader and Mdf4Loader (Task 10.1).

Covers the happy path plus the error cases from Requirements 1.4/1.6/1.7/1.8
(MDF4) and 2.5/2.6/2.8 (CSV): missing file, corrupt/invalid format, non-numeric
data, empty file, column-count mismatch.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.loaders.csv_loader import CsvLoader
from valisync.core.loaders.mdf4_loader import Mdf4Loader
from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import LoadCancelled

from .mdf4_helpers import (
    CAN,
    ETHERNET,
    NONE,
    write_mdf4,
    write_mdf4_all_channels_bad,
    write_mdf4_non_monotonic,
)


def _fmt(**overrides: object) -> FormatDefinition:
    base: dict[str, object] = {
        "name": "test",
        "delimiter": Delimiter.COMMA,
        "timestamp_column": 0,
        "timestamp_unit": "sec",
        "signal_start_column": 1,
        "signal_end_column": 2,
        "has_header": True,
        "has_unit_row": False,
    }
    base.update(overrides)
    return FormatDefinition(**base)  # type: ignore[arg-type]


def _write_csv(tmp_path: Path, text: str, name: str = "data.csv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ─── CsvLoader: happy path ────────────────────────────────────────────────────


def test_csv_basic_load_with_header(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,speed,rpm\n0.0,1.0,10.0\n1.0,2.0,20.0\n")
    result = CsvLoader().load(path, _fmt())

    assert result.signal_group is not None
    sg = result.signal_group
    assert sg.file_format == "CSV"
    assert [s.name for s in sg.signals] == ["speed", "rpm"]
    np.testing.assert_array_equal(sg.signals[0].timestamps, [0.0, 1.0])
    np.testing.assert_array_equal(sg.signals[0].values, [1.0, 2.0])
    np.testing.assert_array_equal(sg.signals[1].values, [10.0, 20.0])


def test_csv_no_header_uses_default_names(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "0.0,1.0,10.0\n1.0,2.0,20.0\n")
    result = CsvLoader().load(path, _fmt(has_header=False))

    assert result.signal_group is not None
    assert [s.name for s in result.signal_group.signals] == ["ch_1", "ch_2"]


def test_csv_msec_converted_to_sec(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,v\n0,5.0\n1000,6.0\n2000,7.0\n")
    result = CsvLoader().load(
        path, _fmt(timestamp_unit="msec", signal_start_column=1, signal_end_column=1)
    )

    assert result.signal_group is not None
    np.testing.assert_array_equal(
        result.signal_group.signals[0].timestamps, [0.0, 1.0, 2.0]
    )


def test_csv_unit_row_populates_metadata(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path, "t,speed,rpm\ns,km/h,1/min\n0.0,1.0,10.0\n1.0,2.0,20.0\n"
    )
    result = CsvLoader().load(path, _fmt(has_unit_row=True))

    assert result.signal_group is not None
    assert result.signal_group.signals[0].metadata["unit"] == "km/h"
    assert result.signal_group.signals[1].metadata["unit"] == "1/min"


def test_csv_semicolon_delimiter(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t;v\n0.0;1.0\n1.0;2.0\n")
    result = CsvLoader().load(
        path,
        _fmt(delimiter=Delimiter.SEMICOLON, signal_start_column=1, signal_end_column=1),
    )

    assert result.signal_group is not None
    np.testing.assert_array_equal(result.signal_group.signals[0].values, [1.0, 2.0])


def test_csv_blank_rows_skipped(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,v\n0.0,1.0\n\n1.0,2.0\n\n")
    result = CsvLoader().load(path, _fmt(signal_start_column=1, signal_end_column=1))

    assert result.signal_group is not None
    np.testing.assert_array_equal(result.signal_group.signals[0].timestamps, [0.0, 1.0])


def test_csv_supports_suffix() -> None:
    assert CsvLoader().supports(Path("a.csv")) is True
    assert CsvLoader().supports(Path("a.CSV")) is True
    assert CsvLoader().supports(Path("a.mf4")) is False


# ─── CsvLoader: error cases ───────────────────────────────────────────────────


def test_csv_file_not_found(tmp_path: Path) -> None:
    result = CsvLoader().load(tmp_path / "missing.csv", _fmt())
    assert result.signal_group is None
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].level == "error"


def test_csv_empty_file_with_header(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "")
    result = CsvLoader().load(path, _fmt())
    assert result.signal_group is None
    assert result.diagnostics[0].level == "error"


def test_csv_non_numeric_timestamp(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,v\nabc,1.0\n")
    result = CsvLoader().load(path, _fmt(signal_start_column=1, signal_end_column=1))
    assert result.signal_group is None
    diag = result.diagnostics[0]
    assert diag.level == "error"
    assert diag.line_number == 2


def test_csv_non_numeric_value(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,v\n0.0,xyz\n")
    result = CsvLoader().load(path, _fmt(signal_start_column=1, signal_end_column=1))
    assert result.signal_group is None
    assert result.diagnostics[0].level == "error"


def test_csv_too_few_columns(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "t,a,b\n0.0,1.0\n")
    result = CsvLoader().load(path, _fmt())
    assert result.signal_group is None
    assert result.diagnostics[0].level == "error"


# ─── CsvLoader: 品質診断 (LD-04/06/08/09) ─────────────────────────────────────


def _load_csv_text(tmp_path: Path, text: str):
    # _fmt(): ts列0・信号列1-2・header あり — 下記テストの "t,a,b" 形状に合わせた
    # 既存ヘルパをそのまま流用(新規ヘルパを増やさない)。
    return CsvLoader().load(_write_csv(tmp_path, text), _fmt())


def test_csv_non_monotonic_is_accepted_with_file_warning(tmp_path: Path) -> None:
    result = _load_csv_text(tmp_path, "t,a,b\n0.0,1,2\n2.0,3,4\n1.0,5,6\n1.0,7,8\n")
    assert result.signal_group is not None  # 旧実装ではファイル全滅
    assert any(
        d.level == "warning" and "非単調" in d.message for d in result.diagnostics
    )
    assert not result.signal_group.signals[0].is_monotonic  # 生データ無改変


def test_csv_nan_inf_values_accepted_with_count_warning(tmp_path: Path) -> None:
    result = _load_csv_text(tmp_path, "t,a,b\n0.0,nan,1\n1.0,inf,2\n")
    assert result.signal_group is not None
    a = result.signal_group.signals[0]
    assert np.isnan(a.values[0]) and np.isinf(a.values[1])
    assert any("非有限値 2 個" in d.message for d in result.diagnostics)


def test_csv_duplicate_headers_disambiguated_like_mdf4(tmp_path: Path) -> None:
    result = _load_csv_text(tmp_path, "t,spd,spd\n0.0,1,2\n1.0,3,4\n")
    assert result.signal_group is not None
    names = [s.name for s in result.signal_group.signals]
    assert names == ["spd[0]", "spd[1]"]  # MDF4 と同一方式
    assert any("重複ヘッダ" in d.message for d in result.diagnostics)


def test_csv_header_only_succeeds_with_warning(tmp_path: Path) -> None:
    result = _load_csv_text(tmp_path, "t,a,b\n")
    assert result.signal_group is not None
    assert all(len(s.timestamps) == 0 for s in result.signal_group.signals)
    assert any("データ行が 0 行" in d.message for d in result.diagnostics)


def test_csv_non_finite_timestamp_fails_with_error(tmp_path: Path) -> None:
    result = _load_csv_text(tmp_path, "t,a,b\n0.0,1,2\nnan,3,4\n")
    assert result.signal_group is None
    assert any(
        d.level == "error" and "タイムスタンプ" in d.message for d in result.diagnostics
    )


# ─── CsvLoader: cooperative cancel (FB-04 hard side) ──────────────────────────


def test_csv_loader_cancel_checked_per_1000_rows(tmp_path: Path) -> None:
    # 2500 データ行 → チェックは概ね 1000 行ごと(毎行呼ばれないこと)を検証
    fmt = _fmt(signal_start_column=1, signal_end_column=1)
    path = tmp_path / "big.csv"
    rows = "\n".join(f"{i * 0.001},{i}" for i in range(2500))
    path.write_text("t,v\n" + rows + "\n", encoding="utf-8")

    calls: list[int] = []

    def cancel() -> bool:
        calls.append(1)
        return len(calls) >= 2  # 2回目のチェックで中断

    with pytest.raises(LoadCancelled):
        CsvLoader().load(path, fmt, cancel=cancel)
    assert 2 <= len(calls) <= 5  # 行数比例で毎行呼ばれていないこと


# ─── Mdf4Loader: happy path ───────────────────────────────────────────────────


def test_mdf4_basic_load_bus_type_detection(tmp_path: Path) -> None:
    ts = [0.0, 0.1, 0.2]
    path = write_mdf4(
        tmp_path / "x.mf4",
        [
            {
                "name": "speed",
                "timestamps": ts,
                "values": [1.0, 2.0, 3.0],
                "bus_type": CAN,
                "unit": "km/h",
            },
            {
                "name": "rpm",
                "timestamps": ts,
                "values": [4.0, 5.0, 6.0],
                "bus_type": NONE,
                "source_name": "XCP_daq",
            },
            {
                "name": "load",
                "timestamps": ts,
                "values": [7.0, 8.0, 9.0],
                "bus_type": ETHERNET,
            },
        ],
    )
    result = Mdf4Loader().load(path)

    assert result.signal_group is not None
    by_name = {s.name: s for s in result.signal_group.signals}
    assert by_name["speed"].bus_type == "CAN"
    assert by_name["rpm"].bus_type == "XCP"
    assert by_name["load"].bus_type == "Ethernet"
    assert by_name["speed"].metadata["unit"] == "km/h"
    np.testing.assert_array_equal(by_name["speed"].values, [1.0, 2.0, 3.0])


def test_mdf4_duplicate_names_disambiguated(tmp_path: Path) -> None:
    ts = [0.0, 1.0]
    path = write_mdf4(
        tmp_path / "dup.mf4",
        [
            {"name": "sig", "timestamps": ts, "values": [1.0, 2.0], "bus_type": CAN},
            {"name": "sig", "timestamps": ts, "values": [3.0, 4.0], "bus_type": CAN},
        ],
    )
    result = Mdf4Loader().load(path)

    assert result.signal_group is not None
    names = {s.name for s in result.signal_group.signals}
    assert names == {"sig[0]", "sig[1]"}


def test_mdf4_multiple_channel_groups_all_loaded(tmp_path: Path) -> None:
    path = write_mdf4(
        tmp_path / "multi.mf4",
        [{"name": f"ch{i}", "bus_type": CAN} for i in range(5)],
    )
    result = Mdf4Loader().load(path)
    assert result.signal_group is not None
    assert len(result.signal_group.signals) == 5


def test_mdf4_supports_suffix() -> None:
    assert Mdf4Loader().supports(Path("a.mf4")) is True
    assert Mdf4Loader().supports(Path("a.MF4")) is True
    assert Mdf4Loader().supports(Path("a.csv")) is False


# ─── Mdf4Loader: error cases ──────────────────────────────────────────────────


def test_mdf4_file_not_found(tmp_path: Path) -> None:
    result = Mdf4Loader().load(tmp_path / "missing.mf4")
    assert result.signal_group is None
    assert result.diagnostics[0].level == "error"


def test_mdf4_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.mf4"
    path.write_bytes(b"this is not a valid MDF4 file" * 10)
    result = Mdf4Loader().load(path)
    assert result.signal_group is None
    assert result.diagnostics[0].level == "error"


# ─── Mdf4Loader: 非単調/0ch 診断 (LD-03/05) ───────────────────────────────────


def test_mdf4_non_monotonic_channel_is_accepted_with_warning(tmp_path: Path) -> None:
    path = write_mdf4_non_monotonic(tmp_path)
    result = Mdf4Loader().load(path)
    assert result.signal_group is not None
    names = [s.name for s in result.signal_group.signals]
    assert "messy" in names  # 旧実装では skip されていた
    warnings = [d for d in result.diagnostics if d.level == "warning"]
    assert any("非単調" in d.message or "重複" in d.message for d in warnings)
    messy = next(s for s in result.signal_group.signals if s.name == "messy")
    assert not messy.is_monotonic  # 生データ無改変で受け入れ


def test_mdf4_zero_channels_emits_warning(tmp_path: Path) -> None:
    path = write_mdf4_all_channels_bad(tmp_path)
    result = Mdf4Loader().load(path)
    assert result.signal_group is not None
    assert len(result.signal_group.signals) == 0
    assert any("0 本" in d.message for d in result.diagnostics)


# ─── Mdf4Loader: cooperative cancel (FB-04 hard side) ─────────────────────────


def test_mdf4_loader_cancel_raises(tmp_path: Path) -> None:
    path = write_mdf4(
        tmp_path / "x.mf4",
        [
            {
                "name": "speed",
                "timestamps": [0.0, 0.1],
                "values": [1.0, 2.0],
                "bus_type": CAN,
            }
        ],
    )
    with pytest.raises(LoadCancelled):
        Mdf4Loader().load(path, cancel=lambda: True)
