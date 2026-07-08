"""Tests for GraphPanelVM with dynamic LOD pipeline (Task 3.1).

Tests verify (strict TDD — tests written before implementation):
- add_signal assigns distinct colors and auto-fits x/y ranges
- render_data returns one RenderCurve per visible signal
- Point-count is bounded: large signal triggers LOD (lod_active True)
  and last_rendered_points <= 2 * panel_width_px + small slack
- Zoomed-in x_range narrows visible slice (searchsorted correctness)
- When slice length <= n, lod_active is False and raw slice returned
- Empty visible range yields empty-array curve (legend still present)
- reset_x / reset_y recompute correct bounds
- Cache: repeated render_data without state change is idempotent
- toggle_visibility removes signal from rendered curves
- inspect() returns a snapshot dict with all expected fields
- remove_signal removes signal from plotted list
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from valisync.core.interpolation import InterpolationMethod
from valisync.core.models import Delimiter, FormatDefinition, Signal, SignalGroup
from valisync.core.session import Session
from valisync.core.statistics.range_stats import StatisticsResult  # noqa: F401
from valisync.gui.viewmodels.graph_panel_vm import (
    CursorReading,  # noqa: F401
    DeltaReading,  # noqa: F401
    GraphPanelVM,
    RenderCurve,
)
from valisync.gui.viewmodels.y_axis_vm import YAxisVM

# ─── Helpers ────────────────────────────────────────────────────────────────


def _csv_format(n_signals: int = 1) -> FormatDefinition:
    """FormatDefinition for a CSV with t + n_signals data columns."""
    return FormatDefinition(
        name="test_fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=n_signals,
        has_header=True,
    )


def _write_csv(path: Path, n_rows: int, n_signals: int = 1) -> Path:
    """Write a CSV with n_rows rows (t, sig1, ..., sigN) and return the path."""
    headers = ["t"] + [f"s{i}" for i in range(1, n_signals + 1)]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for i in range(n_rows):
            t = float(i) * 0.01  # 0.00, 0.01, ..., spaced by 0.01 s
            row = [t] + [float(i % 100) for _ in range(n_signals)]
            writer.writerow(row)
    return path


def _loaded_session(
    tmp_path: Path, n_rows: int = 100, n_signals: int = 1
) -> tuple[Session, str]:
    """Return (session, group_key) with signals loaded from a temp CSV."""
    csv_file = _write_csv(tmp_path / "data.csv", n_rows, n_signals)
    session = Session()
    key = session.load(csv_file, _csv_format(n_signals)).key
    return session, key


def _first_signal_key(session: Session) -> str:
    """Return the namespaced name of the first signal in session."""
    return session.signals()[0].name


def _non_monotonic_signal(name: str = "messy") -> Signal:
    """A Signal with out-of-order timestamps (accepted since Task 1)."""
    return Signal(
        name=name,
        timestamps=np.array([0.0, 2.0, 1.0], dtype=np.float64),
        values=np.array([10.0, 30.0, 20.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def _register_signal(session: Session, sig: Signal, tmp_path: Path) -> str:
    """Register *sig* directly into *session* (bypassing the loader) and return its namespaced key.

    Mirrors the ``_group_of`` pattern in tests/test_session.py: signals are
    injected via ``session._groups.add`` so tests can exercise a Signal shape
    the CSV loader cannot yet produce (Task 4 predates Task 6's non-monotonic
    CSV support).
    """
    key = session._groups.add(
        SignalGroup(
            signals=(sig,),
            source_path=tmp_path / f"{sig.name}.csv",
            file_format="CSV",
            loaded_at=datetime.now(),
        )
    )
    return session.group_signals(key)[0].name


# ─── RenderCurve ─────────────────────────────────────────────────────────────


def test_render_curve_is_dataclass() -> None:
    """RenderCurve is a dataclass with name, color, timestamps, values, axis_index."""
    rc = RenderCurve(
        name="grp::sig",
        color="#1f77b4",
        timestamps=np.array([0.0, 1.0]),
        values=np.array([1.0, 2.0]),
        axis_index=0,
    )
    assert rc.name == "grp::sig"
    assert rc.color == "#1f77b4"
    assert len(rc.timestamps) == 2
    assert len(rc.values) == 2
    assert rc.axis_index == 0


# ─── Construction ────────────────────────────────────────────────────────────


def test_vm_construction_empty_session() -> None:
    """GraphPanelVM can be constructed with an empty Session (no signals)."""
    session = Session()
    vm = GraphPanelVM(session)
    assert vm.x_range is None
    assert vm.y_range is None
    assert vm.panel_width_px == 800
    assert vm.lod_active is False
    assert vm.last_rendered_points == 0


# ─── add_signal ──────────────────────────────────────────────────────────────


def test_add_signal_assigns_first_color(tmp_path: Path) -> None:
    """First added signal gets the first palette color #1f77b4."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    sig_key = _first_signal_key(session)

    vm.add_signal(sig_key)

    snapshot = vm.inspect()
    assert snapshot["plotted_signals"][0]["color"] == "#1f77b4"


def test_add_signal_assigns_distinct_colors(tmp_path: Path) -> None:
    """Two added signals get distinct colors from the palette."""
    session, _key = _loaded_session(tmp_path, n_rows=10, n_signals=2)
    vm = GraphPanelVM(session)
    sigs = session.signals()
    vm.add_signal(sigs[0].name)
    vm.add_signal(sigs[1].name)

    snapshot = vm.inspect()
    colors = [p["color"] for p in snapshot["plotted_signals"]]
    assert colors[0] != colors[1]


def test_add_signal_auto_fits_x_range(tmp_path: Path) -> None:
    """add_signal auto-sets x_range when previously None."""
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]

    vm.add_signal(sig.name)

    assert vm.x_range is not None
    x_lo, x_hi = vm.x_range
    assert x_lo <= float(sig.timestamps[0])
    assert x_hi >= float(sig.timestamps[-1])


def test_add_signal_auto_fits_y_range(tmp_path: Path) -> None:
    """add_signal auto-sets y_range when previously None."""
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]

    vm.add_signal(sig.name)

    assert vm.y_range is not None


def test_add_signal_notifies_signals(tmp_path: Path) -> None:
    """add_signal fires a 'signals' notification."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    events: list[str] = []
    vm.subscribe(events.append)

    vm.add_signal(_first_signal_key(session))

    assert "signals" in events


def test_add_signal_visible_by_default(tmp_path: Path) -> None:
    """A newly added signal is visible=True."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))

    snapshot = vm.inspect()
    assert snapshot["plotted_signals"][0]["visible"] is True


# ─── remove_signal ───────────────────────────────────────────────────────────


def test_remove_signal_removes_from_plotted(tmp_path: Path) -> None:
    """remove_signal removes the signal from the plotted list."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    sig_key = _first_signal_key(session)
    vm.add_signal(sig_key)

    vm.remove_signal(sig_key)

    snapshot = vm.inspect()
    keys = [p["signal_key"] for p in snapshot["plotted_signals"]]
    assert sig_key not in keys


def test_remove_signal_notifies_signals(tmp_path: Path) -> None:
    """remove_signal fires a 'signals' notification."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    sig_key = _first_signal_key(session)
    vm.add_signal(sig_key)
    events: list[str] = []
    vm.subscribe(events.append)

    vm.remove_signal(sig_key)

    assert "signals" in events


# ─── toggle_visibility ───────────────────────────────────────────────────────


def test_toggle_visibility_hides_signal_from_render(tmp_path: Path) -> None:
    """A toggled-invisible signal does not appear in render_data output."""
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=2)
    vm = GraphPanelVM(session)
    sigs = session.signals()
    vm.add_signal(sigs[0].name)
    vm.add_signal(sigs[1].name)

    vm.toggle_visibility(sigs[0].name)

    curves = vm.render_data()
    rendered_names = [c.name for c in curves]
    assert sigs[0].name not in rendered_names
    assert sigs[1].name in rendered_names


def test_toggle_visibility_notifies_signals(tmp_path: Path) -> None:
    """toggle_visibility fires a 'signals' notification."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    sig_key = _first_signal_key(session)
    vm.add_signal(sig_key)
    events: list[str] = []
    vm.subscribe(events.append)

    vm.toggle_visibility(sig_key)

    assert "signals" in events


def test_toggle_visibility_double_restores(tmp_path: Path) -> None:
    """Two toggles restores visibility and signal appears in render_data."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    sig_key = _first_signal_key(session)
    vm.add_signal(sig_key)

    vm.toggle_visibility(sig_key)
    vm.toggle_visibility(sig_key)

    curves = vm.render_data()
    rendered_names = [c.name for c in curves]
    assert sig_key in rendered_names


# ─── set_x_range / set_y_range ───────────────────────────────────────────────


def test_set_x_range_stores_and_notifies(tmp_path: Path) -> None:
    """set_x_range stores the range and fires 'range' notification."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    events: list[str] = []
    vm.subscribe(events.append)

    vm.set_x_range(1.0, 2.0)

    assert vm.x_range == (1.0, 2.0)
    assert "range" in events


def test_set_y_range_stores_and_notifies(tmp_path: Path) -> None:
    """set_y_range stores the range and fires 'range' notification."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    events: list[str] = []
    vm.subscribe(events.append)

    vm.set_y_range(-10.0, 10.0)

    assert vm.y_range == (-10.0, 10.0)
    assert "range" in events


# ─── reset_x / reset_y ───────────────────────────────────────────────────────


def test_reset_x_sets_full_range(tmp_path: Path) -> None:
    """reset_x sets x_range to the union of all plotted signals' time extents."""
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]
    vm.add_signal(sig.name)
    # Manually narrow x_range first
    vm.set_x_range(0.1, 0.2)

    vm.reset_x()

    assert vm.x_range is not None
    x_lo, x_hi = vm.x_range
    assert x_lo <= float(sig.timestamps[0]) + 1e-9
    assert x_hi >= float(sig.timestamps[-1]) - 1e-9


def test_reset_y_covers_all_visible_values(tmp_path: Path) -> None:
    """reset_y spans all visible values across all visible plotted signals."""
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]
    vm.add_signal(sig.name)

    vm.reset_y()

    assert vm.y_range is not None
    finite_vals = sig.values[np.isfinite(sig.values)]
    if len(finite_vals) > 0:
        y_lo, y_hi = vm.y_range
        assert y_lo <= float(finite_vals.min()) + 1e-9
        assert y_hi >= float(finite_vals.max()) - 1e-9


def test_reset_y_uses_aligned_view_not_raw_values(tmp_path: Path) -> None:
    """reset_y must fit on the aligned (sorted, keep-last) view, not raw values.

    ts=[0,1,1] has a duplicate ts=1 where sorted_view's keep-last dedup drops
    the 100 sample (never rendered) and keeps 1. Fitting on raw sig.values
    would stretch y_range to include that discarded, never-drawn 100.
    """
    csv_file = tmp_path / "dup.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "s1"])
        writer.writerow([0.0, 5.0])
        writer.writerow([1.0, 100.0])
        writer.writerow([1.0, 1.0])
    session = Session()
    session.load(csv_file, _csv_format(1))
    sig = session.signals()[0]
    assert not sig.is_monotonic  # sanity: duplicate ts triggers the divergence

    vm = GraphPanelVM(session)
    vm.add_signal(sig.name)
    vm.reset_y()

    assert vm.y_range is not None
    _, y_hi = vm.y_range
    assert y_hi < 100.0  # displayed values top out near 5, not the discarded 100


def test_reset_y_empty_graceful() -> None:
    """reset_y with no plotted signals does not raise; y_range stays None or is set."""
    session = Session()
    vm = GraphPanelVM(session)
    # Should not raise
    vm.reset_y()


def test_reset_x_notifies_range(tmp_path: Path) -> None:
    """reset_x fires 'range' notification."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    events: list[str] = []
    vm.subscribe(events.append)

    vm.reset_x()

    assert "range" in events


def test_reset_y_notifies_range(tmp_path: Path) -> None:
    """reset_y fires 'range' notification."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    events: list[str] = []
    vm.subscribe(events.append)

    vm.reset_y()

    assert "range" in events


# ─── set_panel_width ─────────────────────────────────────────────────────────


def test_set_panel_width_updates_and_notifies(tmp_path: Path) -> None:
    """set_panel_width updates panel_width_px and fires 'range' notification."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    events: list[str] = []
    vm.subscribe(events.append)

    vm.set_panel_width(1200)

    assert vm.panel_width_px == 1200
    assert "range" in events


# ─── render_data: basic ──────────────────────────────────────────────────────


def test_render_data_empty_when_no_signals() -> None:
    """render_data returns [] when no signals have been added."""
    session = Session()
    vm = GraphPanelVM(session)
    assert vm.render_data() == []


def test_render_data_returns_one_curve_per_visible_signal(tmp_path: Path) -> None:
    """render_data returns one RenderCurve per visible plotted signal."""
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=2)
    vm = GraphPanelVM(session)
    sigs = session.signals()
    vm.add_signal(sigs[0].name)
    vm.add_signal(sigs[1].name)

    curves = vm.render_data()

    assert len(curves) == 2
    assert all(isinstance(c, RenderCurve) for c in curves)


def test_render_data_curve_names_match_signal_keys(tmp_path: Path) -> None:
    """RenderCurve.name equals the signal's namespaced key."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]
    vm.add_signal(sig.name)

    curves = vm.render_data()

    assert curves[0].name == sig.name


def test_render_data_curve_has_correct_color(tmp_path: Path) -> None:
    """RenderCurve.color matches the color assigned during add_signal."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))

    curves = vm.render_data()
    snapshot = vm.inspect()

    assert curves[0].color == snapshot["plotted_signals"][0]["color"]


# ─── render_data: LOD pipeline ───────────────────────────────────────────────


def test_render_data_lod_active_for_large_signal(tmp_path: Path) -> None:
    """Large signal (> 2*panel_width_px points) triggers LOD; lod_active=True."""
    # n_rows=5000, panel_width_px=800 → n=1600 < 5000 → downsampling
    session, _ = _loaded_session(tmp_path, n_rows=5000)
    vm = GraphPanelVM(session)
    vm.set_panel_width(800)
    vm.add_signal(_first_signal_key(session))

    vm.render_data()

    assert vm.lod_active is True


def test_render_data_point_count_bounded(tmp_path: Path) -> None:
    """last_rendered_points <= 2*panel_width_px + slack after LOD."""
    session, _ = _loaded_session(tmp_path, n_rows=5000)
    vm = GraphPanelVM(session)
    vm.set_panel_width(800)
    vm.add_signal(_first_signal_key(session))

    vm.render_data()

    # n = 2*800 = 1600; downsampler may return slightly fewer due to buckets
    assert vm.last_rendered_points <= 2 * 800 + 10


def test_render_data_no_lod_for_small_signal(tmp_path: Path) -> None:
    """Small signal (< 2*panel_width_px points) is NOT downsampled; lod_active=False."""
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    vm.set_panel_width(800)  # n=1600 > 50, so no downsampling
    vm.add_signal(_first_signal_key(session))

    vm.render_data()

    assert vm.lod_active is False


def test_render_data_raw_slice_when_small(tmp_path: Path) -> None:
    """When no downsampling is needed, all raw slice points are returned."""
    n_rows = 50
    session, _ = _loaded_session(tmp_path, n_rows=n_rows)
    vm = GraphPanelVM(session)
    vm.set_panel_width(800)
    sig = session.signals()[0]
    vm.add_signal(sig.name)

    curves = vm.render_data()

    assert len(curves[0].timestamps) == n_rows
    assert vm.last_rendered_points == n_rows


# ─── render_data: searchsorted / x_range slicing ─────────────────────────────


def test_render_data_zoom_reduces_points(tmp_path: Path) -> None:
    """Zoomed-in x_range returns fewer or equal points than full range."""
    n_rows = 200
    session, _ = _loaded_session(tmp_path, n_rows=n_rows)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]
    vm.add_signal(sig.name)

    # Full range
    full_curves = vm.render_data()
    full_count = len(full_curves[0].timestamps)

    # Narrow to first 20%
    ts = sig.timestamps
    vm.set_x_range(float(ts[0]), float(ts[int(n_rows * 0.2)]))
    zoomed_curves = vm.render_data()
    zoomed_count = len(zoomed_curves[0].timestamps)

    assert zoomed_count <= full_count


def test_render_data_includes_boundary_samples(tmp_path: Path) -> None:
    """RN-01: 描画スライスは窓の外側に隣接サンプルを1点ずつ含む (窓を横切る線分用)."""
    n_rows = 200
    session, _ = _loaded_session(tmp_path, n_rows=n_rows)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]
    vm.add_signal(sig.name)

    ts = sig.timestamps
    x_lo = float(ts[10])
    x_hi = float(ts[50])
    vm.set_x_range(x_lo, x_hi)

    out = vm.render_data()[0].timestamps.tolist()
    # 窓内 (ts[10]..ts[50]) と左右1点ずつ (ts[9], ts[51])
    assert out[0] == pytest.approx(float(ts[9]))
    assert out[-1] == pytest.approx(float(ts[51]))


def test_render_data_non_monotonic_signal_yields_monotonic_curve(
    tmp_path: Path,
) -> None:
    """render_data yields strictly-monotonic timestamps for a non-monotonic Signal.

    Signal no longer rejects out-of-order timestamps (Task 1); render must
    consume Signal.sorted_view() (not raw timestamps) so RenderCurve stays
    strictly monotonic and searchsorted slicing is correct.
    """
    session = Session()
    sig_key = _register_signal(session, _non_monotonic_signal(), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(sig_key)
    # add_signal auto-fits x_range via _auto_fit_ranges(); for the raw
    # timestamps [0.0, 2.0, 1.0] the sorted endpoints are 0.0/2.0 — this
    # pins down that auto-fit reads sorted_view(), not the raw array.
    assert vm.x_range == (0.0, 2.0)
    # Wide fixed window so the render assertion below doesn't depend on
    # auto-fit, which (pre-fix) derives ts0/tsN from the raw unsorted array
    # (see memory: gui_offset_render_test_xrange_pitfall).
    vm.x_range = (0.0, 10.0)

    curves = vm.render_data()

    ts = curves[0].timestamps
    assert len(ts) > 0
    assert np.all(np.diff(ts) > 0)


def test_reset_x_sorts_non_monotonic_signal_to_sorted_endpoints(
    tmp_path: Path,
) -> None:
    """reset_x fits x_range to the sorted (not raw) endpoints of a non-monotonic Signal.

    Mirrors test_reset_x_sets_full_range but with an out-of-order Signal, so
    it fails if reset_x's auto-fit ever regresses to reading raw timestamps
    instead of sorted_view().
    """
    session = Session()
    sig_key = _register_signal(session, _non_monotonic_signal(), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(sig_key)
    # Manually narrow x_range first so reset_x has something to overwrite.
    vm.set_x_range(0.1, 0.2)

    vm.reset_x()

    assert vm.x_range == (0.0, 2.0)


def test_render_data_range_beyond_data_keeps_legend(tmp_path: Path) -> None:
    """x_range が完全にデータ外 → 凡例は残り、窓内サンプルは無い (RN-01: 境界1点は可視域外)."""
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]
    vm.add_signal(sig.name)

    # Set x_range far beyond data end
    ts = sig.timestamps
    win_lo = float(ts[-1]) + 100.0
    vm.set_x_range(win_lo, float(ts[-1]) + 200.0)

    curves = vm.render_data()

    assert len(curves) == 1  # legend entry still present
    # RN-01: 終端の境界サンプルが1点含まれ得るが、窓内 (win_lo 以降) には何も無い
    in_window = [t for t in curves[0].timestamps.tolist() if t >= win_lo]
    assert in_window == []


# ─── render_data: cache ───────────────────────────────────────────────────────


def test_render_data_cache_idempotent(tmp_path: Path) -> None:
    """Calling render_data twice without state change is idempotent."""
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))

    curves1 = vm.render_data()
    pts1 = vm.last_rendered_points
    curves2 = vm.render_data()
    pts2 = vm.last_rendered_points

    assert pts1 == pts2
    assert len(curves1) == len(curves2)
    for c1, c2 in zip(curves1, curves2, strict=True):
        assert c1.name == c2.name
        np.testing.assert_array_equal(c1.timestamps, c2.timestamps)
        np.testing.assert_array_equal(c1.values, c2.values)


def test_render_data_cache_invalidated_by_x_range_change(tmp_path: Path) -> None:
    """Cache is invalidated when x_range changes."""
    n_rows = 200
    session, _ = _loaded_session(tmp_path, n_rows=n_rows)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]
    vm.add_signal(sig.name)

    curves1 = vm.render_data()
    count1 = len(curves1[0].timestamps)

    ts = sig.timestamps
    vm.set_x_range(float(ts[0]), float(ts[20]))
    curves2 = vm.render_data()
    count2 = len(curves2[0].timestamps)

    assert count2 < count1 or count2 <= 21


def test_render_data_cache_invalidated_by_panel_width_change(tmp_path: Path) -> None:
    """Cache is invalidated when panel_width changes (potentially changes n)."""
    session, _ = _loaded_session(tmp_path, n_rows=5000)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.set_panel_width(100)  # very narrow → aggressive LOD

    vm.render_data()
    pts_narrow = vm.last_rendered_points

    vm.set_panel_width(2000)  # very wide → less LOD
    vm.render_data()
    pts_wide = vm.last_rendered_points

    # Wider panel allows more points
    assert pts_wide >= pts_narrow


# ─── lod_active aggregate ─────────────────────────────────────────────────────


def test_lod_active_resets_per_render(tmp_path: Path) -> None:
    """lod_active reflects the CURRENT render, not a previous one."""
    session, _ = _loaded_session(tmp_path, n_rows=5000)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]
    vm.add_signal(sig.name)
    vm.set_panel_width(800)

    vm.render_data()
    assert vm.lod_active is True  # downsampled

    # Now zoom in to just 2 points — slice < n, no downsampling
    ts = sig.timestamps
    vm.set_x_range(float(ts[0]), float(ts[1]))
    vm.render_data()
    # slice is 2 points, n = 1600 >> 2, no downsampling
    assert vm.lod_active is False


# ─── inspect ──────────────────────────────────────────────────────────────────


def test_inspect_returns_expected_keys(tmp_path: Path) -> None:
    """inspect() dict includes all documented top-level keys."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))

    snap = vm.inspect()

    for key in (
        "plotted_signals",
        "x_range",
        "y_range",
        "panel_width_px",
        "lod_active",
        "last_rendered_points",
    ):
        assert key in snap, f"Missing key: {key}"


def test_inspect_plotted_signals_structure(tmp_path: Path) -> None:
    """inspect()['plotted_signals'] entries have signal_key, color, visible."""
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))

    snap = vm.inspect()
    entry = snap["plotted_signals"][0]

    assert "signal_key" in entry
    assert "color" in entry
    assert "visible" in entry


# ─── palette cycling ──────────────────────────────────────────────────────────


def test_palette_cycles_beyond_ten_signals(tmp_path: Path) -> None:
    """11th signal cycles back to the first palette color."""
    # Need 11 distinct signals: 1 CSV with 11 signal columns
    session, _ = _loaded_session(tmp_path, n_rows=5, n_signals=11)
    vm = GraphPanelVM(session)
    sigs = session.signals()
    assert len(sigs) >= 11

    for sig in sigs[:11]:
        vm.add_signal(sig.name)

    snap = vm.inspect()
    colors = [p["color"] for p in snap["plotted_signals"]]
    # Color of 11th signal (index 10) should equal color of 1st (index 0)
    assert colors[10] == colors[0]


# ─── reset with no fittable signals clears the range (review finding ⑦) ─────────


def test_reset_x_clears_range_when_no_plotted_signals(tmp_path: Path) -> None:
    """reset_x with nothing to fit must clear x_range to None, not keep a stale one.

    Regression: a leftover range from a previous signal set would otherwise
    suppress _auto_fit_ranges (which only fires when x_range is None) and clip
    any later-added signal to the stale window.
    """
    session, _ = _loaded_session(tmp_path)
    key = _first_signal_key(session)
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.set_x_range(0.1, 0.2)
    vm.remove_signal(key)

    vm.reset_x()

    assert vm.x_range is None


def test_reset_y_clears_range_when_no_plotted_signals(tmp_path: Path) -> None:
    """reset_y with nothing to fit must clear y_range to None, not keep a stale one."""
    session, _ = _loaded_session(tmp_path)
    key = _first_signal_key(session)
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.set_y_range(-5.0, 5.0)
    vm.remove_signal(key)

    vm.reset_y()

    assert vm.y_range is None


def test_multi_axis_independent_ranges(tmp_path: Path) -> None:
    """Verify reset_y fits multiple axes independently based on their assigned signals."""
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=2)
    vm = GraphPanelVM(session)
    sigs = session.signals()

    # Add a second axis
    vm.axes.append(YAxisVM())

    # Assign sig[0] to axis 0, sig[1] to axis 1
    vm.add_signal(sigs[0].name)  # defaults to axis 0
    vm.add_signal(sigs[1].name)
    # Manually reassign second signal to second axis (entry.axis_index = 1)
    # This is slightly white-box but no public API exists yet for assignment.
    vm._plotted[1].axis_index = 1

    # Get actual min/max of the signals
    v0_lo, v0_hi = sigs[0].values.min(), sigs[0].values.max()
    v1_lo, v1_hi = sigs[1].values.min(), sigs[1].values.max()

    vm.reset_y()

    assert vm.axes[0].y_range == (float(v0_lo), float(v0_hi))
    assert vm.axes[1].y_range == (float(v1_lo), float(v1_hi))


# ─── Multi-axis resizing (Task 2) ────────────────────────────────────────────


def test_render_data_includes_axis_index(tmp_path: Path) -> None:
    """RenderCurve includes the axis_index assigned to the signal."""
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=2)
    vm = GraphPanelVM(session)
    sigs = session.signals()
    vm.add_signal(sigs[0].name)
    vm.add_signal(sigs[1].name)
    vm._plotted[1].axis_index = 1

    curves = vm.render_data()

    assert curves[0].axis_index == 0
    assert curves[1].axis_index == 1


# ─── Global cursor (R15) ─────────────────────────────────────────────────────


def test_cursor_readings_linear_interpolation(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    key = _first_signal_key(session)
    vm.add_signal(key)
    # CSV helper: t=i*0.01, value=i  → between (0.00,0) and (0.01,1), linear@0.005 = 0.5
    vm.set_cursor(0.005)
    readings = vm.cursor_readings()
    assert len(readings) == 1
    assert readings[0].name == key
    assert readings[0].in_range is True
    assert readings[0].value == pytest.approx(0.5)


def test_cursor_readings_out_of_range_yields_none(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.set_cursor(5.0)  # 最終 timestamp 0.99 を超える
    reading = vm.cursor_readings()[0]
    assert reading.in_range is False
    assert reading.value is None


def test_cursor_readings_empty_when_no_cursor(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    assert vm.cursor_readings() == []


def test_set_cursor_notifies_cursor_change(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.set_cursor(0.1)
    assert "cursor" in changes


def test_set_interp_method_changes_reading_and_notifies(tmp_path: Path) -> None:
    """Switching interp method changes the cursor reading and fires 'cursor' notify.

    CSV helper: t=i*0.01, value=i  → at t=0.005, LINEAR gives ~0.5, ZOH gives 0.0.
    """
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.set_cursor(0.005)

    # LINEAR (default): interpolated value ≈ 0.5
    readings_linear = vm.cursor_readings()
    assert len(readings_linear) == 1
    assert readings_linear[0].value == pytest.approx(0.5)

    # Subscribe to capture notifications from set_interp_method.
    notified: list[str] = []
    vm.subscribe(notified.append)

    vm.set_interp_method(InterpolationMethod.ZERO_ORDER_HOLD)

    # ZOH: held value of the preceding sample at t=0.00 → value=0.0
    readings_zoh = vm.cursor_readings()
    assert len(readings_zoh) == 1
    assert readings_zoh[0].value == pytest.approx(0.0)

    # set_interp_method must fire a "cursor" notification so views re-render.
    assert "cursor" in notified


def test_cursor_readings_skips_invisible_signal(tmp_path: Path) -> None:
    """cursor_readings() excludes signals whose visible flag is False."""
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    key = _first_signal_key(session)
    vm.add_signal(key)
    vm.toggle_visibility(key)  # hide the signal
    vm.set_cursor(0.005)

    readings = vm.cursor_readings()

    assert readings == []


# ─── Delta cursor + range stats (R16/R17) ───────────────────────────────────


def test_toggle_main_cursor_places_at_50_percent(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    assert vm.cursor_t == pytest.approx(0.5)
    vm.toggle_main_cursor(False)
    assert vm.cursor_t is None


def test_toggle_delta_requires_main(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    # main OFF のとき delta は有効化されない
    vm.toggle_delta(True)
    assert vm.delta_enabled is False
    assert vm.cursor_t_b is None
    # main ON 後は B=75% に出る
    vm.toggle_main_cursor(True)
    vm.toggle_delta(True)
    assert vm.delta_enabled is True
    assert vm.cursor_t_b == pytest.approx(0.75)


def test_clearing_main_clears_delta(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    vm.toggle_delta(True)
    vm.set_cursor(None)  # メインを消すとサブも消える(不変条件)
    assert vm.delta_enabled is False
    assert vm.cursor_t_b is None


def test_delta_t_signed(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)  # A=0.5
    vm.toggle_delta(True)  # B=0.75
    assert vm.delta_t == pytest.approx(0.25)


def test_delta_readings_dy_and_stats(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    key = _first_signal_key(session)
    vm.add_signal(key)
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)  # A=0.5 → value≈50 (value=i, t=i/100)
    vm.set_cursor(0.2)  # A を 0.2 に(value≈20)
    vm.toggle_delta(True)  # B=0.75 (value≈75)
    vm.set_cursor_b(0.6)  # B=0.6 (value≈60)
    r = vm.delta_readings()[0]
    assert r.name == key
    assert r.value_a == pytest.approx(20.0)
    assert r.dy == pytest.approx(40.0)  # y(0.6)-y(0.2) = 60-20
    # 範囲 [0.2,0.6] の統計: 値 20..60
    assert r.stats.count > 0
    assert r.stats.min == pytest.approx(20.0)
    assert r.stats.max == pytest.approx(60.0)


def test_delta_readings_normalizes_when_b_before_a(tmp_path):
    # B<A でも compute_statistics は min/max 正規化で ValueError を出さない
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    vm.set_cursor(0.6)  # A=0.6
    vm.toggle_delta(True)
    vm.set_cursor_b(0.2)  # B=0.2 < A
    r = vm.delta_readings()[0]  # 例外なく計算できる
    assert r.stats.count > 0
    assert vm.delta_t == pytest.approx(-0.4)  # Δt は符号付き


def test_delta_readings_empty_when_delta_off(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    assert vm.delta_readings() == []  # delta 未有効


def test_set_cursor_b_notifies_delta(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    vm.toggle_delta(True)
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.set_cursor_b(0.3)
    assert "delta" in changes
    assert "cursor" not in changes  # must NOT cross-broadcast (local-only)


def test_toggle_delta_notifies_only_delta(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)  # this notifies "cursor"
    changes: list[str] = []
    vm.subscribe(changes.append)  # subscribe AFTER main is on
    vm.toggle_delta(True)
    assert "delta" in changes
    assert "cursor" not in changes  # delta toggle must not cross-broadcast


def test_toggle_delta_off_clears_b(tmp_path):
    session, _ = _loaded_session(tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    vm.toggle_delta(True)
    vm.toggle_delta(False)
    assert vm.delta_enabled is False
    assert vm.cursor_t_b is None


def test_delta_readings_dy_none_when_out_of_range(tmp_path):
    session, _ = _loaded_session(tmp_path, n_rows=100, n_signals=1)
    vm = GraphPanelVM(session)
    vm.add_signal(_first_signal_key(session))
    vm.x_range = (0.0, 1.0)
    vm.toggle_main_cursor(True)
    vm.set_cursor(0.2)  # A in range (value≈20)
    vm.toggle_delta(True)
    vm.set_cursor_b(5.0)  # B beyond last timestamp 0.99 → interpolate None
    r = vm.delta_readings()[0]
    assert r.dy is None
    assert r.value_a == pytest.approx(20.0)  # A still in range


# ─── visible_stat_cols (spec §7) ─────────────────────────────────────────────


def test_visible_stat_cols_default_all_five() -> None:
    """visible_stat_cols defaults to all 5 stat columns (spec §7)."""
    session = Session()
    vm = GraphPanelVM(session)
    assert vm.visible_stat_cols == {"mean", "max", "min", "std", "count"}


def test_set_visible_stats_updates_field() -> None:
    """set_visible_stats stores the reduced set on the VM."""
    session = Session()
    vm = GraphPanelVM(session)
    vm.set_visible_stats({"mean", "count"})
    assert vm.visible_stat_cols == {"mean", "count"}


def test_set_visible_stats_notifies_delta() -> None:
    """set_visible_stats fires a 'delta' notification so the view re-renders."""
    session = Session()
    vm = GraphPanelVM(session)
    events: list[str] = []
    vm.subscribe(events.append)
    vm.set_visible_stats({"mean"})
    assert "delta" in events


# ─── RN-01: 疎信号のズーム消失 (X 窓スライスの境界サンプル取り込み) ──────────────


def _sparse_sig(name: str = "sparse") -> Signal:
    """t=0,100,200 の疎信号 (値も 0,100,200)."""
    return Signal(
        name=name,
        timestamps=np.array([0.0, 100.0, 200.0], dtype=np.float64),
        values=np.array([0.0, 100.0, 200.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def test_rn01_sparse_signal_visible_when_zoomed_between_samples(
    tmp_path: Path,
) -> None:
    """窓内にサンプルが無くても窓を横切る線分の端点が含まれる (RN-01)."""
    session = Session()
    key = _register_signal(session, _sparse_sig(), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.set_x_range(40.0, 60.0)  # サンプルの無い窓へズーム
    curves = vm.render_data()
    ts = curves[0].timestamps
    # 境界2点 (t=0 と t=100) が含まれ、線分 0->100 が [40,60] を横切って描ける
    assert 0.0 in ts.tolist() and 100.0 in ts.tolist()


def test_rn01_window_after_signal_end_no_fabricated_line(tmp_path: Path) -> None:
    """信号終端より後の窓は境界1点のみ (可視域外・外挿の捏造なし) (RN-01)."""
    session = Session()
    key = _register_signal(session, _sparse_sig(), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.set_x_range(300.0, 400.0)  # 信号は t<=200
    ts = vm.render_data()[0].timestamps
    assert ts.tolist() == [200.0]  # 終端の1点のみ (可視域外でクリップ)


def test_rn01_full_view_unchanged(tmp_path: Path) -> None:
    """全体表示 (x_range=None 相当) では全サンプルが出る (回帰) (RN-01)."""
    session = Session()
    key = _register_signal(session, _sparse_sig(), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(key)  # auto-fit で [0,200]
    ts = vm.render_data()[0].timestamps
    assert ts.tolist() == [0.0, 100.0, 200.0]


# ─── RN-02: 別時間域の追加信号が窓外で無表示 (自動フィットの和集合拡張) ──────────


def _ranged_sig(name: str, t0: float, t1: float) -> Signal:
    """[t0, t1] の 2 点信号 (別時間域の比較用)."""
    return Signal(
        name=name,
        timestamps=np.array([t0, t1], dtype=np.float64),
        values=np.array([1.0, 2.0], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def test_rn02_second_signal_expands_range_in_auto_mode(tmp_path: Path) -> None:
    """自動フィット中は別時間域の2本目追加で x_range が和集合へ拡張 (RN-02)."""
    session = Session()
    a = _register_signal(session, _ranged_sig("A", 0.0, 100.0), tmp_path)
    b = _register_signal(session, _ranged_sig("B", 500.0, 600.0), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(a)
    assert vm.x_range == (0.0, 100.0) and vm._x_range_is_auto is True
    vm.add_signal(b)
    assert vm.x_range == (0.0, 600.0)  # 和集合 — B が窓外に消えない


def test_rn02_manual_zoom_is_respected(tmp_path: Path) -> None:
    """手動ズーム後は追加で範囲を触らない (RN-02・ユーザー決定=何もしない)."""
    session = Session()
    a = _register_signal(session, _ranged_sig("A", 0.0, 100.0), tmp_path)
    c = _register_signal(session, _ranged_sig("C", 500.0, 600.0), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(a)
    vm.set_x_range(40.0, 60.0)  # 手動ズーム
    assert vm._x_range_is_auto is False
    vm.add_signal(c)
    assert vm.x_range == (40.0, 60.0)  # ズーム尊重・拡張しない


def test_rn02_reset_x_returns_to_auto(tmp_path: Path) -> None:
    """reset_x は union フィットして auto へ復帰 (RN-02)."""
    session = Session()
    a = _register_signal(session, _ranged_sig("A", 0.0, 100.0), tmp_path)
    b = _register_signal(session, _ranged_sig("B", 500.0, 600.0), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(a)
    vm.set_x_range(40.0, 60.0)  # manual
    vm.add_signal(b)  # manual なので拡張しない
    vm.reset_x()
    assert vm.x_range == (0.0, 600.0) and vm._x_range_is_auto is True


def test_entry_id_is_monotonic_and_unique(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=2)
    k0, k1 = [s.name for s in session.signals()][:2]
    vm = GraphPanelVM(session)
    vm.add_signal(k0)
    vm.add_signal(k1)
    ids = [e["entry_id"] for e in vm.inspect()["plotted_signals"]]
    assert ids == [0, 1]  # monotonic, in add order


def test_same_signal_key_gets_distinct_entry_ids(tmp_path: Path) -> None:
    # Same signal_key plotted on 2 axes must be tracked as distinct entries.
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = next(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal(key)  # axis 0
    vm.create_new_axis(key)  # separate axis
    entries = vm.inspect()["plotted_signals"]
    assert len(entries) == 2
    assert entries[0]["entry_id"] != entries[1]["entry_id"]
    assert entries[0]["signal_key"] == entries[1]["signal_key"] == key


def test_signal_key_and_axis_reverse_lookup(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = next(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.create_new_axis(key)
    e0, e1 = vm.inspect()["plotted_signals"]
    assert vm.signal_key_for_entry(e0["entry_id"]) == key
    assert vm.axis_of_entry(e1["entry_id"]) == e1["axis_index"]
    assert vm.signal_key_for_entry(999) is None
    assert vm.axis_of_entry(999) is None


def test_render_data_carries_entry_id(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = next(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.create_new_axis(key)
    curves = vm.render_data()
    plotted_ids = {e["entry_id"] for e in vm.inspect()["plotted_signals"]}
    assert {c.entry_id for c in curves} == plotted_ids


def test_render_data_carries_entry_id_for_missing_signal(tmp_path: Path) -> None:
    """entry_id survives the sig=None branch (signal removed from session after add)."""
    session, group_key = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = next(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    entry_id = vm.inspect()["plotted_signals"][0]["entry_id"]

    session.remove_group(group_key)  # signal now absent from session -> sig_map miss

    curves = vm.render_data()
    assert len(curves) == 1
    assert curves[0].timestamps.size == 0  # confirms the sig=None placeholder branch
    assert curves[0].entry_id == entry_id


def _empty_sig(name: str = "void") -> Signal:
    """A Signal with zero samples — exercises render_data's empty-ts_slice branch directly.

    Unlike an out-of-range x_range (which RN-01's +/-1 boundary extension still
    fills with one point), a genuinely zero-length signal forces ts_slice itself
    to be empty regardless of x_range.
    """
    return Signal(
        name=name,
        timestamps=np.array([], dtype=np.float64),
        values=np.array([], dtype=np.float64),
        file_format="CSV",
        bus_type="",
        source_file="",
    )


def test_render_data_carries_entry_id_for_empty_slice(tmp_path: Path) -> None:
    """entry_id survives the empty-ts_slice branch (zero-sample signal)."""
    session = Session()
    key = _register_signal(session, _empty_sig(), tmp_path)
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    entry_id = vm.inspect()["plotted_signals"][0]["entry_id"]

    curves = vm.render_data()
    assert len(curves) == 1
    assert curves[0].timestamps.size == 0  # confirms the empty-slice branch
    assert curves[0].entry_id == entry_id


def test_insert_axis_renumbers_entry_ids_to_dest_vm(tmp_path: Path) -> None:
    """Moving an axis across panels must not collide entry_ids in the destination VM.

    Both source and destination VMs number entries independently starting at 0,
    so the first signal added to each gets entry_id 0. insert_axis must renumber
    the moved entries into the destination's id-space rather than carrying the
    source's ids verbatim (else the destination ends up with duplicate entry_ids).
    """
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=2)
    k0, k1 = [s.name for s in session.signals()][:2]
    src = GraphPanelVM(session)
    src.add_signal(k0)  # entry_id 0 in src
    dst = GraphPanelVM(session)
    dst.add_signal(k1)  # entry_id 0 in dst

    extracted = src.extract_axis(0)
    assert extracted is not None
    axis, entries = extracted
    dst.insert_axis(axis, entries, column=0, position=None)

    ids = [e["entry_id"] for e in dst.inspect()["plotted_signals"]]
    assert len(ids) == len(set(ids))  # all distinct — no collision


def test_toggle_entry_visibility_targets_only_that_entry(tmp_path: Path) -> None:
    # 同一 signal_key の 2 エントリのうち片方だけを不可視にできる (先頭一致の曖昧さを解消)
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = next(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.create_new_axis(key)
    e0, e1 = vm.inspect()["plotted_signals"]
    vm.toggle_entry_visibility(e1["entry_id"])
    vis = {e["entry_id"]: e["visible"] for e in vm.inspect()["plotted_signals"]}
    assert vis[e0["entry_id"]] is True
    assert vis[e1["entry_id"]] is False


def test_set_color_changes_only_target_and_busts_cache(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = next(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    eid = vm.inspect()["plotted_signals"][0]["entry_id"]
    vm.render_data()  # prime cache
    vm.set_color(eid, "#123456")
    # 色は cache_key に含まれない → invalidate されていないと古い色が返る
    curves = vm.render_data()
    assert curves[0].color == "#123456"
    assert vm.inspect()["plotted_signals"][0]["color"] == "#123456"


def test_remove_entry_removes_only_that_entry(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = next(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.create_new_axis(key)
    e0, e1 = vm.inspect()["plotted_signals"]
    vm.remove_entry(e0["entry_id"])
    remaining = vm.inspect()["plotted_signals"]
    assert len(remaining) == 1
    assert remaining[0]["entry_id"] == e1["entry_id"]


def test_toggle_axis_visibility_flips_all_on_axis(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=2)
    k0, k1 = [s.name for s in session.signals()][:2]
    vm = GraphPanelVM(session)
    vm.add_signal(k0)  # axis 0
    vm.add_signal(k1)  # axis 0 (同 axis)
    # 1 本でも可視 → 全非表示
    vm.toggle_axis_visibility(0)
    assert all(not e["visible"] for e in vm.inspect()["plotted_signals"])
    # 全非表示 → 全表示
    vm.toggle_axis_visibility(0)
    assert all(e["visible"] for e in vm.inspect()["plotted_signals"])


def test_toggle_axis_visibility_empty_axis_is_noop(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = next(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    vm.toggle_axis_visibility(5)  # 存在しない axis
    assert vm.inspect()["plotted_signals"][0]["visible"] is True


def test_entry_ops_notify_signals(tmp_path: Path) -> None:
    session, _ = _loaded_session(tmp_path, n_rows=10, n_signals=1)
    key = next(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal(key)
    eid = vm.inspect()["plotted_signals"][0]["entry_id"]
    changes: list[str] = []
    vm.subscribe(changes.append)
    vm.toggle_entry_visibility(eid)
    vm.set_color(eid, "#abcdef")
    assert changes == ["signals", "signals"]
