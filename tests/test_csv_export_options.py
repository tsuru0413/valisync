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


# --- shared-timeline mismatch guard (whole-branch review Important #1) ------
#
# 統合タイムライン(unified)を明示的に外した場合、_rows_shared_timeline は
# signals[0] の時間軸を全信号が共有する前提で索引する。マルチレート信号
# (MDF チャンネルは独立ラスタ)を渡すと: 短い→IndexError、長い→末尾を無言
# 切り捨て(データ損失)、同長異timestamps→無言でずれる(データ破損)。


def test_shared_timeline_rejects_mismatched_length_signals(tmp_path: Path) -> None:
    a = _sig("a", [0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    b = _sig("b", [0.0, 1.0], [4.0, 5.0])
    out = tmp_path / "d.csv"
    with pytest.raises(ValueError):
        CsvExporter().export([a, b], out, use_unified_timeline=False)
    assert not out.exists()  # 検査は書き込み前 = 破損ファイルを残さない


def test_shared_timeline_rejects_same_length_different_timestamps(
    tmp_path: Path,
) -> None:
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    b = _sig("b", [0.0, 2.0], [4.0, 5.0])
    out = tmp_path / "d.csv"
    with pytest.raises(ValueError):
        CsvExporter().export([a, b], out, use_unified_timeline=False)
    assert not out.exists()


def test_shared_timeline_still_succeeds_for_matched_signals(tmp_path: Path) -> None:
    # 無回帰: 共有タイムライン信号は従来どおり成功する
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    b = _sig("b", [0.0, 1.0], [3.0, 4.0])
    out = tmp_path / "d.csv"
    CsvExporter().export([a, b], out, use_unified_timeline=False)
    assert _read(out) == ["timestamp,a,b", "0.0,1.0,3.0", "1.0,2.0,4.0"]


def test_unified_timeline_handles_mismatched_signals_correctly(
    tmp_path: Path,
) -> None:
    # マルチレート信号を安全に書き出す唯一の経路 = 統合タイムライン(union)
    a = _sig("a", [0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    b = _sig("b", [0.0, 1.0], [4.0, 5.0])
    out = tmp_path / "d.csv"
    CsvExporter().export([a, b], out, use_unified_timeline=True)
    assert _read(out) == [
        "timestamp,a,b",
        "0.0,1.0,4.0",
        "1.0,2.0,5.0",
        "2.0,3.0,",  # b はこの timestamp を持たない = 空セル
    ]


def test_empty_delimiter_rejected() -> None:
    with pytest.raises(ValueError):
        CsvExportOptions(delimiter="")


def test_empty_decimal_rejected() -> None:
    with pytest.raises(ValueError):
        CsvExportOptions(decimal="")
