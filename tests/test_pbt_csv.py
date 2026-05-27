"""Property-based tests for FormatDefinition and the CSV read path.

Property 4: FormatDefinition validation — construction succeeds iff every
            invariant holds.
Property 5: FormatDefinition JSON round-trip — save→load is identity.
Property 7: CSV read round-trip — numbers written at full precision parse back
            within IEEE-754 15-significant-digit tolerance.
Property 8: CSV export round-trip — exporting a Signal then re-loading recovers
            timestamps and values within IEEE-754 17-significant-digit tolerance.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from valisync.core.export import CsvExporter
from valisync.core.loaders.csv_loader import CsvLoader
from valisync.core.loaders.format_def_manager import FormatDefinitionManager
from valisync.core.models import Delimiter, FormatDefinition

from .conftest import finite_floats, monotonic_timestamps, valid_signals

pytestmark = pytest.mark.property

_SAFE_NAME = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=0,
    max_size=40,
)


@st.composite
def valid_format_defs(draw: st.DrawFn) -> FormatDefinition:
    """A FormatDefinition with a filesystem-safe, non-reserved name."""
    name = "fmt_" + draw(_SAFE_NAME)  # prefix guarantees non-empty & not reserved
    ts_col = draw(st.integers(min_value=0, max_value=255))
    # signal range must not contain ts_col; pick a side that has room
    sides: list[str] = []
    if ts_col >= 1:
        sides.append("below")
    if ts_col <= 254:
        sides.append("above")
    if draw(st.sampled_from(sides)) == "below":
        s_end = draw(st.integers(min_value=0, max_value=ts_col - 1))
        s_start = draw(st.integers(min_value=0, max_value=s_end))
    else:
        s_start = draw(st.integers(min_value=ts_col + 1, max_value=255))
        s_end = draw(st.integers(min_value=s_start, max_value=255))
    return FormatDefinition(
        name=name,
        delimiter=draw(st.sampled_from(list(Delimiter))),
        timestamp_column=ts_col,
        timestamp_unit=draw(st.sampled_from(["sec", "msec"])),
        signal_start_column=s_start,
        signal_end_column=s_end,
        has_header=draw(st.booleans()),
        has_unit_row=draw(st.booleans()),
    )


# ─── Property 4: validation ───────────────────────────────────────────────────


@given(
    name=st.text(max_size=70),
    ts_col=st.integers(min_value=-5, max_value=260),
    unit=st.sampled_from(["sec", "msec", "ns", "bad"]),
    s_start=st.integers(min_value=-5, max_value=260),
    s_end=st.integers(min_value=-5, max_value=260),
    delim=st.sampled_from(list(Delimiter)),
    header=st.booleans(),
)
def test_format_def_validation(
    name: str,
    ts_col: int,
    unit: str,
    s_start: int,
    s_end: int,
    delim: Delimiter,
    header: bool,
) -> None:
    should_be_valid = (
        1 <= len(name) <= 64
        and 0 <= ts_col <= 255
        and unit in ("sec", "msec")
        and 0 <= s_start <= s_end <= 255
        and not (s_start <= ts_col <= s_end)
    )

    def build() -> FormatDefinition:
        return FormatDefinition(
            name=name,
            delimiter=delim,
            timestamp_column=ts_col,
            timestamp_unit=unit,
            signal_start_column=s_start,
            signal_end_column=s_end,
            has_header=header,
        )

    if should_be_valid:
        fd = build()
        assert fd.name == name
        assert fd.timestamp_column == ts_col
    else:
        with pytest.raises(ValueError):
            build()


# ─── Property 5: JSON round-trip ──────────────────────────────────────────────


@given(fd=valid_format_defs())
def test_format_def_json_roundtrip(fd: FormatDefinition) -> None:
    with tempfile.TemporaryDirectory() as d:
        mgr = FormatDefinitionManager(Path(d))
        mgr.save(fd)
        (loaded,) = mgr.load_all()
        assert loaded == fd


# ─── Property 7: CSV read round-trip ──────────────────────────────────────────


@given(
    ts=monotonic_timestamps(min_size=2, max_size=20),
    n_signals=st.integers(min_value=1, max_value=4),
    data=st.data(),
)
def test_csv_read_roundtrip(ts: np.ndarray, n_signals: int, data: st.DrawFn) -> None:
    n = len(ts)
    cols = [
        data.draw(arrays(np.float64, n, elements=finite_floats))
        for _ in range(n_signals)
    ]

    header = ",".join(["t"] + [f"s{i}" for i in range(n_signals)])
    lines = [header]
    for r in range(n):
        cells = [repr(float(ts[r]))] + [
            repr(float(cols[i][r])) for i in range(n_signals)
        ]
        lines.append(",".join(cells))
    text = "\n".join(lines) + "\n"

    fmt = FormatDefinition(
        name="rt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=n_signals,
        has_header=True,
    )

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "data.csv"
        path.write_text(text, encoding="utf-8")
        result = CsvLoader().load(path, fmt)

    assert result.signal_group is not None
    signals = result.signal_group.signals
    assert len(signals) == n_signals
    for i, sig in enumerate(signals):
        np.testing.assert_allclose(sig.timestamps, ts, rtol=1e-15, atol=0.0)
        np.testing.assert_allclose(sig.values, cols[i], rtol=1e-15, atol=0.0)


# ─── Property 8: CSV export round-trip ────────────────────────────────────────


@given(sig=valid_signals(min_size=2, max_size=20))
def test_csv_export_roundtrip(sig) -> None:
    fmt = FormatDefinition(
        name="rt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "out.csv"
        CsvExporter().export([sig], path)
        result = CsvLoader().load(path, fmt)

    assert result.signal_group is not None
    (loaded,) = result.signal_group.signals
    np.testing.assert_allclose(loaded.timestamps, sig.timestamps, rtol=1e-16, atol=0.0)
    np.testing.assert_allclose(loaded.values, sig.values, rtol=1e-16, atol=0.0)
