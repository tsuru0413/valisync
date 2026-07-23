"""Tests for the comparison-mode transient flag (spec: comparison-mode-toggle).

Tests verify:
- is_comparison_mode() is now flag AND >=2-files (not the bare file-count
  auto-judgment it used to be) -- see docs/superpowers/specs/
  2026-07-23-comparison-mode-toggle-design.md §1.
- comparison_enabled exposes the raw user flag, independent of file count.
- set_comparison_mode() is a same-value no-op (mirrors set_reference_file).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.color_variants import hue_variant
from valisync.gui.theme.tokens import active
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

# ─── Fixtures / helpers ─────────────────────────────────────────────────────


@pytest.fixture
def app_vm_with_two_files() -> AppViewModel:
    """AppViewModel with 2 group keys registered (lightweight -- no real I/O,
    mirrors the register_loaded-based E-2c tests in test_app_viewmodel.py)."""
    vm = AppViewModel()
    vm.register_loaded("k1")
    vm.register_loaded("k2")
    return vm


@pytest.fixture
def app_vm_one_file() -> AppViewModel:
    vm = AppViewModel()
    vm.register_loaded("k1")
    return vm


def _csv_format_n(n_signals: int) -> FormatDefinition:
    """FormatDefinition for a CSV with t + n_signals data columns."""
    return FormatDefinition(
        name="tN",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=n_signals,
        has_header=True,
    )


def _write_csv_n(path: Path, n_signals: int) -> Path:
    """Write a CSV with n_signals data columns (headers s1..sN)."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t"] + [f"s{i}" for i in range(1, n_signals + 1)])
        writer.writerow([0.0, *[10.0 * i for i in range(1, n_signals + 1)]])
        writer.writerow([1.0, *[20.0 * i for i in range(1, n_signals + 1)]])
    return path


# ─── T-A1 / T-A2 ────────────────────────────────────────────────────────────


def test_comparison_predicate_gates_on_flag_and_count(
    app_vm_with_two_files: AppViewModel,
) -> None:
    vm = app_vm_with_two_files  # 2 files loaded
    assert vm.is_comparison_mode() is False  # default OFF
    assert vm.comparison_enabled is False
    vm.set_comparison_mode(True)
    assert vm.comparison_enabled is True
    assert vm.is_comparison_mode() is True  # flag AND >=2


def test_comparison_predicate_false_with_single_file_even_when_enabled(
    app_vm_one_file: AppViewModel,
) -> None:
    vm = app_vm_one_file
    vm.set_comparison_mode(True)
    assert vm.comparison_enabled is True  # raw flag independent of count
    assert vm.is_comparison_mode() is False  # AND >=2 guard


def test_set_comparison_mode_same_value_is_noop(
    app_vm_with_two_files: AppViewModel,
) -> None:
    vm = app_vm_with_two_files
    calls = []
    vm.subscribe(lambda tag: calls.append(tag) if tag == "comparison_mode" else None)
    vm.set_comparison_mode(False)  # already False
    assert calls == []
    vm.set_comparison_mode(True)
    assert calls == ["comparison_mode"]


# ─── T-A4 (OFF freeze + no-churn) ───────────────────────────────────────────


def test_off_freezes_hue_colors_and_reapply_is_noop(tmp_path: Path) -> None:
    """OFF freeze (spec §4, user decision 3): once hue-family colors are
    applied under comparison mode ON, toggling OFF and calling
    reapply_auto_colors() again must NOT touch colors (resolver returns None
    for every group -> the `continue` on `hue is None` leaves existing
    colors alone) and must NOT churn (no invalidate/notify) since nothing
    actually changed (spec §7 T-A4).

    key1 contributes 2 signals (variant_step 0 and 1) precisely so a
    count-mod-by-list-position sabotage of the freeze branch (which would
    coincidentally match hue_variant(..., step=0) for a single-signal file,
    hiding the regression) actually diverges on the variant_step=1 entry —
    see the sabotage note in task-1-report.md."""
    app_vm = AppViewModel()
    app_vm.set_comparison_mode(True)
    key1 = app_vm.request_load(_write_csv_n(tmp_path / "a.csv", 2), _csv_format_n(2))
    key2 = app_vm.request_load(_write_csv_n(tmp_path / "b.csv", 1), _csv_format_n(1))
    panel = GraphPanelVM(app_vm.session, hue_resolver=app_vm.file_hue_resolver())
    panel.add_signal(f"{key1}::s1")
    panel.add_signal(f"{key1}::s2")
    panel.add_signal(f"{key2}::s1")

    palette = active().colors.signal_palette
    before = [e["color"] for e in panel.inspect()["plotted_signals"]]
    assert before == [
        hue_variant(palette[app_vm.file_hue_index[key1]].hex, 0),
        hue_variant(palette[app_vm.file_hue_index[key1]].hex, 1),
        hue_variant(palette[app_vm.file_hue_index[key2]].hex, 0),
    ]  # sanity: really hue-family colors before toggling off

    panel.render_data()  # populate the render cache
    assert panel._cache  # sanity: cache non-empty before reapply

    app_vm.set_comparison_mode(False)
    notifications: list[str] = []
    panel.subscribe(notifications.append)

    panel.reapply_auto_colors()

    after = [e["color"] for e in panel.inspect()["plotted_signals"]]
    assert after == before  # (a) colors unchanged -- frozen, not count-mod
    assert notifications == []  # (b) no churn: no notify at all
    assert panel._cache  # (b) no churn: cache was not invalidated (cleared)


# ─── T-A5 (E-0 independence) / T-A6 (sticky expansion) / T-A7 (2->1 freeze) ─


def test_bare_name_collision_qualifies_regardless_of_comparison_mode(
    tmp_path: Path,
) -> None:
    """Readings' "(group_key)" collision qualification is E-0's concern
    (display_names(), collision-scoped to the panel's VISIBLE entries) and
    must NOT depend on is_comparison_mode() (spec §5, §7 T-A5) -- even in
    single mode (flag OFF, the default), 2 distinct group_keys sharing a
    bare name plotted together on ONE panel must both qualify."""
    app_vm = AppViewModel()
    key1 = app_vm.request_load(_write_csv_n(tmp_path / "a.csv", 1), _csv_format_n(1))
    key2 = app_vm.request_load(_write_csv_n(tmp_path / "b.csv", 1), _csv_format_n(1))
    assert app_vm.is_comparison_mode() is False  # single mode throughout

    panel = GraphPanelVM(app_vm.session, hue_resolver=app_vm.file_hue_resolver())
    panel.add_signal_to_axis(f"{key1}::s1", 0)
    panel.add_signal_to_axis(f"{key2}::s1", 0)  # same panel, same bare name "s1"
    assert all(e.visible for e in panel._plotted)

    panel.set_cursor(0.0)
    names = {r.name for r in panel.cursor_readings()}
    assert names == {f"s1 ({key1})", f"s1 ({key2})"}


def test_sticky_variant_step_expands_same_file_entries_on_toggle_on(
    tmp_path: Path,
) -> None:
    """Adding 3 signals from ONE file while single (count-mod, already
    distinct by construction) sticky-records variant_step 0/1/2 at add time
    (spec §4.1) even with comparison mode inactive. Toggling comparison mode
    ON must therefore spread the 3 entries across 3 DISTINCT hue-variant
    shades, not collapse them onto the same family color (spec §7 T-A6)."""
    app_vm = AppViewModel()
    key1 = app_vm.request_load(_write_csv_n(tmp_path / "a.csv", 3), _csv_format_n(3))
    app_vm.request_load(  # 2nd file -- only satisfies the >=2-files guard
        _write_csv_n(tmp_path / "b.csv", 1), _csv_format_n(1)
    )
    panel = GraphPanelVM(app_vm.session, hue_resolver=app_vm.file_hue_resolver())
    for i in (1, 2, 3):
        panel.add_signal(f"{key1}::s{i}")
    assert app_vm.is_comparison_mode() is False  # flag still OFF -- count-mod

    app_vm.set_comparison_mode(True)
    panel.reapply_auto_colors()

    colors = [e["color"] for e in panel.inspect()["plotted_signals"]]
    assert len(set(colors)) == 3  # 3 distinct shades -- not collapsed
    palette = active().colors.signal_palette
    hue1 = app_vm.file_hue_index[key1]
    assert colors == [hue_variant(palette[hue1].hex, step) for step in (0, 1, 2)]


def test_survivor_keeps_hue_color_after_unload_to_one_file(tmp_path: Path) -> None:
    """2 files, ON, hue-family colors applied -> unloading the OTHER file
    drops the session to 1 file -> the surviving curve's hue-family color
    stays frozen (does NOT fall back to count-mod), and comparison_enabled
    (the raw flag) stays True even though is_comparison_mode() now reads
    False (spec §4.2/§9.4, §7 T-A7, M9)."""
    app_vm = AppViewModel()
    app_vm.set_comparison_mode(True)
    key1 = app_vm.request_load(_write_csv_n(tmp_path / "a.csv", 1), _csv_format_n(1))
    key2 = app_vm.request_load(_write_csv_n(tmp_path / "b.csv", 1), _csv_format_n(1))
    panel = GraphPanelVM(app_vm.session, hue_resolver=app_vm.file_hue_resolver())
    panel.add_signal(f"{key1}::s1")

    palette = active().colors.signal_palette
    hue1 = app_vm.file_hue_index[key1]
    expected = hue_variant(palette[hue1].hex, 0)
    assert panel.inspect()["plotted_signals"][0]["color"] == expected

    app_vm.unload_file(key2)  # drop to 1 file

    assert app_vm.is_comparison_mode() is False  # >=2-files guard now fails
    assert app_vm.comparison_enabled is True  # raw flag persists (M9)

    panel.reapply_auto_colors()  # even if invoked, must be a no-op (frozen)

    assert panel.inspect()["plotted_signals"][0]["color"] == expected  # frozen
