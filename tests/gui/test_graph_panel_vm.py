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
from pathlib import Path

import numpy as np
import pytest

from valisync.core.interpolation import InterpolationMethod
from valisync.core.models import Delimiter, FormatDefinition
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
    key = session.load(csv_file, _csv_format(n_signals))
    return session, key


def _first_signal_key(session: Session) -> str:
    """Return the namespaced name of the first signal in session."""
    return session.signals()[0].name


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


def test_render_data_timestamps_within_x_range(tmp_path: Path) -> None:
    """Returned timestamps lie within the requested x_range (searchsorted)."""
    n_rows = 200
    session, _ = _loaded_session(tmp_path, n_rows=n_rows)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]
    vm.add_signal(sig.name)

    ts = sig.timestamps
    x_lo = float(ts[10])
    x_hi = float(ts[50])
    vm.set_x_range(x_lo, x_hi)

    curves = vm.render_data()
    if len(curves[0].timestamps) > 0:
        assert float(curves[0].timestamps[0]) >= x_lo - 1e-12
        assert float(curves[0].timestamps[-1]) <= x_hi + 1e-12


def test_render_data_empty_range_yields_empty_curve(tmp_path: Path) -> None:
    """x_range fully outside data → empty arrays but curve still present (legend)."""
    session, _ = _loaded_session(tmp_path, n_rows=50)
    vm = GraphPanelVM(session)
    sig = session.signals()[0]
    vm.add_signal(sig.name)

    # Set x_range far beyond data end
    ts = sig.timestamps
    vm.set_x_range(float(ts[-1]) + 100.0, float(ts[-1]) + 200.0)

    curves = vm.render_data()

    assert len(curves) == 1  # legend entry still present
    assert len(curves[0].timestamps) == 0
    assert len(curves[0].values) == 0


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
