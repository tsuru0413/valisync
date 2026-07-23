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


# --- header_names (E-0, spec §1.2 — GUI-computed display header override) ----


def test_header_names_none_falls_back_to_signal_name(tmp_path: Path) -> None:
    """Default (header_names=None) writes the raw signal.name — no regression."""
    s = _sig("mf4_1::speed", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _read(out)[0] == "timestamp,mf4_1::speed"


def test_header_names_overrides_signal_name_when_given(tmp_path: Path) -> None:
    s = _sig("mf4_1::speed", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(header_names=("speed",)))
    assert _read(out)[0] == "timestamp,speed"


def test_header_names_applies_to_unit_row_column_alignment(tmp_path: Path) -> None:
    """unit_row still lines up under the overridden header names."""
    s = _sig("mf4_1::speed", [0.0], [1.5], unit="km/h")
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [s], out, options=CsvExportOptions(unit_row=True, header_names=("speed",))
    )
    assert _read(out) == ["timestamp,speed", "s,km/h", "0.0,1.5"]


# --- time range filter (F-0 増分, design spec §2.2, UX-28) -------------------
#
# エクスポートは常に base 信号の生タイムスタンプ座標(R14 時間オフセット非適用)
# で行い、range フィルタも生座標の閉区間 [time_start, time_end] で適用する。


def test_time_range_defaults_are_none_unbounded() -> None:
    """既定 (time_start=time_end=None) = 無制限。既存構築の後方互換の要。"""
    opts = CsvExportOptions()
    assert opts.time_start is None
    assert opts.time_end is None


def test_time_range_filters_shared_timeline_rows(tmp_path: Path) -> None:
    s = _sig("speed", [0.0, 1.0, 2.0, 3.0], [10.0, 20.0, 30.0, 40.0])
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [s], out, options=CsvExportOptions(time_start=1.0, time_end=2.0)
    )
    assert _read(out) == ["timestamp,speed", "1.0,20.0", "2.0,30.0"]


def test_time_range_filters_unified_timeline_rows(tmp_path: Path) -> None:
    a = _sig("a", [0.0, 1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0])
    b = _sig("b", [0.0, 1.0, 2.0, 3.0], [5.0, 6.0, 7.0, 8.0])
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [a, b],
        out,
        use_unified_timeline=True,
        options=CsvExportOptions(time_start=1.0, time_end=2.0),
    )
    assert _read(out) == ["timestamp,a,b", "1.0,2.0,6.0", "2.0,3.0,7.0"]


def test_time_range_start_only_is_unbounded_above(tmp_path: Path) -> None:
    s = _sig("speed", [0.0, 1.0, 2.0], [10.0, 20.0, 30.0])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(time_start=1.0))
    assert _read(out) == ["timestamp,speed", "1.0,20.0", "2.0,30.0"]


def test_time_range_end_only_is_unbounded_below(tmp_path: Path) -> None:
    s = _sig("speed", [0.0, 1.0, 2.0], [10.0, 20.0, 30.0])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(time_end=1.0))
    assert _read(out) == ["timestamp,speed", "0.0,10.0", "1.0,20.0"]


def test_time_range_boundary_inclusive_both_endpoints(tmp_path: Path) -> None:
    s = _sig("speed", [0.0, 1.0, 2.0, 3.0], [10.0, 20.0, 30.0, 40.0])
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [s], out, options=CsvExportOptions(time_start=1.0, time_end=2.0)
    )
    lines = _read(out)
    assert lines[1].startswith("1.0,")  # t==start included
    assert lines[-1].startswith("2.0,")  # t==end included
    assert len(lines) == 3  # header + 2 data rows


def test_time_start_equals_time_end_includes_exact_sample(tmp_path: Path) -> None:
    s = _sig("speed", [0.0, 1.0, 2.0], [10.0, 20.0, 30.0])
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [s], out, options=CsvExportOptions(time_start=1.0, time_end=1.0)
    )
    assert _read(out) == ["timestamp,speed", "1.0,20.0"]


def test_time_range_out_of_range_produces_header_only_file(tmp_path: Path) -> None:
    s = _sig("speed", [0.0, 1.0, 2.0], [10.0, 20.0, 30.0])
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [s], out, options=CsvExportOptions(time_start=10.0, time_end=20.0)
    )
    assert _read(out) == ["timestamp,speed"]  # header-only, 0 data rows


def test_time_range_header_and_unit_rows_unaffected_by_filter(tmp_path: Path) -> None:
    s = _sig("speed", [0.0, 1.0, 2.0], [10.0, 20.0, 30.0], unit="km/h")
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [s],
        out,
        options=CsvExportOptions(unit_row=True, time_start=10.0, time_end=20.0),
    )
    assert _read(out) == ["timestamp,speed", "s,km/h"]  # header + unit, no data


def test_time_start_greater_than_time_end_raises_valueerror() -> None:
    with pytest.raises(ValueError):
        CsvExportOptions(time_start=5.0, time_end=1.0)


def test_time_range_applied_after_unified_timeline_union_resolution(
    tmp_path: Path,
) -> None:
    """統合タイムライン(union)解決後に範囲フィルタを適用する — union に現れない
    範囲外 timestamp が誤って復活しないことを確認。"""
    a = _sig("a", [0.0, 2.0], [10.0, 12.0])
    b = _sig("b", [1.0, 3.0], [21.0, 23.0])
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [a, b],
        out,
        use_unified_timeline=True,
        options=CsvExportOptions(time_start=1.0, time_end=2.0),
    )
    assert _read(out) == ["timestamp,a,b", "1.0,,21.0", "2.0,12.0,"]


def test_time_range_shared_timeline_mismatch_loud_fail_preserved(
    tmp_path: Path,
) -> None:
    """範囲フィルタが shared-timeline mismatch の loud-fail を握りつぶさない。"""
    a = _sig("a", [0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    b = _sig("b", [0.0, 1.0], [4.0, 5.0])
    out = tmp_path / "d.csv"
    with pytest.raises(ValueError):
        CsvExporter().export(
            [a, b],
            out,
            use_unified_timeline=False,
            options=CsvExportOptions(time_start=0.0, time_end=1.0),
        )
    assert not out.exists()


def test_time_range_prod_scale_shared_timeline_row_count_correct(
    tmp_path: Path,
) -> None:
    """prod スケール(330k 相当)で範囲フィルタの行数削減が正しいことを検証。"""
    n = 330_000
    ts = np.arange(n, dtype=np.float64)
    vs = ts * 2.0
    s = _sig("speed", ts.tolist(), vs.tolist())
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [s],
        out,
        options=CsvExportOptions(time_start=50_000.0, time_end=150_000.0),
    )
    lines = _read(out)
    assert len(lines) == 1 + 100_001  # header + inclusive [50000, 150000]
    assert lines[1] == "50000.0,100000.0"
    assert lines[-1] == "150000.0,300000.0"


def test_time_range_prod_scale_unified_timeline_row_count_correct(
    tmp_path: Path,
) -> None:
    """統合タイムライン経路でも prod スケールで行数削減が正しい。"""
    n = 330_000
    ts_a = np.arange(0, n, 2, dtype=np.float64)  # 偶数のみ
    ts_b = np.arange(1, n, 2, dtype=np.float64)  # 奇数のみ
    a = _sig("a", ts_a.tolist(), (ts_a * 2.0).tolist())
    b = _sig("b", ts_b.tolist(), (ts_b * 3.0).tolist())
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [a, b],
        out,
        use_unified_timeline=True,
        options=CsvExportOptions(time_start=100_000.0, time_end=100_010.0),
    )
    lines = _read(out)
    data_lines = lines[1:]
    assert len(data_lines) == 11  # union covers 100000..100010 inclusive
    assert data_lines[0].split(",")[0] == "100000.0"
    assert data_lines[-1].split(",")[0] == "100010.0"
