"""Unit tests for Session orchestration (Task 8.2, Requirements 4.4, 4.5, 5.4, 8.1, 8.3)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.interpolation import InterpolationMethod
from valisync.core.models import Delimiter, FormatDefinition, Signal
from valisync.core.session import (
    LoadCancelled,
    LoadError,
    LoadOutcome,
    Session,
    SourceInfo,
)


def _derived(name: str, ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata={},
    )


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


_FMT = FormatDefinition(
    name="t1",
    delimiter=Delimiter.COMMA,
    timestamp_column=0,
    timestamp_unit="sec",
    signal_start_column=1,
    signal_end_column=1,
    has_header=True,
)


def test_load_csv_returns_key_and_exposes_namespaced_signals(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])

    session = Session()
    key = session.load(csv, format_def=_FMT).key

    assert key == "csv_1"
    signals = session.signals()
    assert len(signals) == 1
    assert signals[0].name == "csv_1::speed"
    np.testing.assert_array_equal(signals[0].values, np.array([10.0, 20.0]))


def test_load_csv_without_format_def_raises(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,v", ["0.0,1.0"])
    with pytest.raises(ValueError):
        Session().load(csv)


def test_source_name_returns_basename_for_key(tmp_path):
    """Public API for GUI to recover a file's display name from its group key."""
    csv = tmp_path / "drive.csv"
    _write_csv(csv, "t,speed", ["0.0,1.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key

    assert session.source_name(key) == "drive.csv"
    with pytest.raises(KeyError):
        session.source_name("nope_99")


def test_group_signals_returns_namespaced_signals_for_one_group(tmp_path):
    """Public API to fetch only one file's signals (avoids scanning all files)."""
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    _write_csv(a, "t,speed", ["0.0,1.0"])
    _write_csv(b, "t,rpm", ["0.0,2.0"])
    session = Session()
    ka = session.load(a, format_def=_FMT).key
    kb = session.load(b, format_def=_FMT).key

    only_a = session.group_signals(ka)
    assert [s.name for s in only_a] == [f"{ka}::speed"]
    only_b = session.group_signals(kb)
    assert [s.name for s in only_b] == [f"{kb}::rpm"]
    with pytest.raises(KeyError):
        session.group_signals("nope_99")


def test_load_many_reports_partial_failure(tmp_path):
    good = tmp_path / "good.csv"
    _write_csv(good, "t,v", ["0.0,1.0", "1.0,2.0"])
    missing = tmp_path / "missing.csv"  # never created

    session = Session()
    result = session.load_many([(good, _FMT), (missing, _FMT)])

    assert len(result.succeeded) == 1  # the good file is usable (Req 5.4)
    assert result.succeeded[0].key == "csv_1"
    assert len(result.failed) == 1
    failed_path, messages = result.failed[0]
    assert failed_path == missing
    assert messages  # error reported per failed file
    assert len(session.signals()) == 1  # successful load available despite the failure


def test_remove_group_without_dependents_removes_immediately(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key

    outcome = session.remove_group(key)

    assert outcome.removed is True
    assert outcome.dependent_signals == ()
    assert session.signals() == []


def test_remove_group_with_dependent_derived_requires_confirmation(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key
    src = session.signals()[0]  # csv_1::speed
    derived = session.evaluate_formula("csv_1::speed * 2", {"csv_1::speed": src})

    # Req 4.5: a dependent Derived_Signal blocks removal until confirmed.
    blocked = session.remove_group(key)
    assert blocked.removed is False
    assert derived.name in blocked.dependent_signals
    assert session.signals()  # not removed

    forced = session.remove_group(key, force=True)
    assert forced.removed is True
    assert session.signals() == []


# ─── Pure-computation pass-throughs ───────────────────────────────────────────


def test_downsample_delegates_to_core():
    ts = list(np.linspace(0.0, 99.0, 100))
    sig = _derived("x", ts, list(np.arange(100.0)))
    out = Session().downsample(sig, 10)
    assert isinstance(out, Signal)
    assert len(out.timestamps) <= 10


def test_interpolate_delegates_to_core():
    sig = _derived("x", [0.0, 1.0, 2.0], [0.0, 10.0, 20.0])
    assert Session().interpolate(sig, 0.5, InterpolationMethod.LINEAR) == 5.0


def test_compute_statistics_delegates_to_core():
    sig = _derived("x", [0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    stats = Session().compute_statistics(sig, 0.0, 2.0)
    assert stats.count == 3
    assert stats.mean == 2.0


def test_apply_offset_delegates_to_core():
    sig = _derived("x", [0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    out = Session().apply_offset(sig, file_offset=1.0)
    np.testing.assert_array_equal(out.timestamps, np.array([1.0, 2.0, 3.0]))


def test_export_csv_delegates_to_core(tmp_path):
    sig = _derived("speed", [0.0, 1.0], [10.0, 20.0])
    out = tmp_path / "e.csv"
    Session().export_csv([sig], out)
    assert out.read_text(encoding="utf-8").splitlines()[0] == "timestamp,speed"


def test_unified_timeline_applies_offsets_preserving_count_and_order(tmp_path):
    csv = tmp_path / "a.csv"
    # two signals sharing one timestamp axis
    csv.write_text("t,a,b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    fmt = FormatDefinition(
        name="t2",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )
    session = Session()
    session.load(csv, format_def=fmt)

    placed = session.unified_timeline_signals(file_offsets={"csv_1": 2.0})

    assert [s.name for s in placed] == ["csv_1::a", "csv_1::b"]  # order preserved (8.3)
    for s in placed:
        np.testing.assert_array_equal(
            s.timestamps, np.array([2.0, 3.0])
        )  # offset (8.1)
        assert len(s.timestamps) == 2  # sample count unchanged (8.4)


# ─── LoadOutcome / diagnostics (FB-02 foundation) ─────────────────────────────


def test_load_returns_outcome_with_key_and_diagnostics(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    outcome = session.load(csv, format_def=_FMT)
    assert isinstance(outcome, LoadOutcome)
    assert outcome.key == "csv_1"
    assert isinstance(outcome.diagnostics, tuple)


def test_load_error_carries_diagnostics(tmp_path):
    session = Session()
    bad = tmp_path / "nope.mf4"  # 存在しない → mdf4 ローダーが失敗
    bad.write_bytes(b"not an mdf")
    try:
        session.load(bad, None)
    except LoadError as exc:
        assert isinstance(exc.diagnostics, tuple)
    else:
        raise AssertionError("expected LoadError")


# ─── Cooperative cancel (FB-04 hard side) ─────────────────────────────────────


def test_load_cancel_raises_and_registers_nothing(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    with pytest.raises(LoadCancelled):
        session.load(csv, format_def=_FMT, cancel=lambda: True)
    assert session.signals() == []


def test_load_without_cancel_is_unchanged(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    outcome = session.load(csv, format_def=_FMT)
    assert outcome.key == "csv_1"


# ─── SourceInfo (FB-10 tooltip data) ─────────────────────────────────────────


def test_source_info_fields(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key
    info = session.source_info(key)
    assert isinstance(info, SourceInfo)
    assert info.full_path == csv.resolve()
    assert info.size_bytes == csv.stat().st_size
    assert info.n_channels >= 1
    assert info.file_format == "CSV"
    assert info.t_min is not None and info.t_max is not None
    assert info.t_min <= info.t_max


def test_source_info_size_none_when_file_gone(tmp_path):
    csv = tmp_path / "a.csv"
    _write_csv(csv, "t,speed", ["0.0,10.0", "1.0,20.0"])
    session = Session()
    key = session.load(csv, format_def=_FMT).key
    csv.unlink()
    info = session.source_info(key)
    assert info.size_bytes is None  # graceful degradation (spec §6)
    assert info.n_channels >= 1  # メモリ上の情報は生きている


def test_source_info_unknown_key_raises():
    with pytest.raises(KeyError):
        Session().source_info("nope_1")
