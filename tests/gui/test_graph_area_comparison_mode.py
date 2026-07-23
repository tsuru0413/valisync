"""Tests for GraphAreaVM's "comparison_mode" reconciliation branch (T-B5/T-B6).

comparison-mode-toggle spec §4: GraphAreaVM._on_app_change must reapply
hue-family colors to every panel (all tabs) the moment the user flips
AppViewModel.set_comparison_mode(True) on an ALREADY-loaded 2-file session --
distinct from the existing "2nd file's real request_load reapplies colors"
coverage in test_graph_area_vm.py:806-893 (which exercises the "loaded" event
chain, not the toggle). Both event chains are required and neither supersedes
the other (spec §7 T-B5 note).
"""

from __future__ import annotations

import csv
from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.color_variants import hue_variant
from valisync.gui.theme.tokens import active
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM

# ─── Helpers ────────────────────────────────────────────────────────────────


def _csv_format_n(n_signals: int) -> FormatDefinition:
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
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t"] + [f"s{i}" for i in range(1, n_signals + 1)])
        writer.writerow([0.0, *[10.0 * i for i in range(1, n_signals + 1)]])
        writer.writerow([1.0, *[20.0 * i for i in range(1, n_signals + 1)]])
    return path


def _colors(panel: object) -> list[str]:
    entries = panel.inspect()["plotted_signals"]  # type: ignore[attr-defined]
    return [e["color"] for e in entries]


# ─── T-B5 ───────────────────────────────────────────────────────────────────


def test_toggle_on_recolors_all_panels_via_comparison_mode_branch(
    tmp_path: Path,
) -> None:
    """2 files loaded while comparison mode is OFF (count-mod colors) -> the
    user toggles set_comparison_mode(True) -> the "comparison_mode" branch
    in _on_app_change fires -> every panel's auto entries reapply into hue
    families, deterministically matching hue_variant(palette[hue], step)."""
    app_vm = AppViewModel()
    key1 = app_vm.request_load(_write_csv_n(tmp_path / "a.csv", 1), _csv_format_n(1))
    key2 = app_vm.request_load(_write_csv_n(tmp_path / "b.csv", 2), _csv_format_n(2))
    area = GraphAreaVM(app_vm)
    panel = area.panels(0)[0]
    panel.add_signal(f"{key1}::s1")
    panel.add_signal(f"{key2}::s1")
    panel.add_signal(f"{key2}::s2")

    before = _colors(panel)
    assert app_vm.is_comparison_mode() is False  # still count-mod at this point

    app_vm.set_comparison_mode(True)

    after = _colors(panel)
    assert after != before  # families applied

    palette = active().colors.signal_palette
    hue1 = app_vm.file_hue_index[key1]
    hue2 = app_vm.file_hue_index[key2]
    expected = [
        hue_variant(palette[hue1].hex, 0),
        hue_variant(palette[hue2].hex, 0),
        hue_variant(palette[hue2].hex, 1),
    ]
    assert after == expected


# ─── T-B6 ───────────────────────────────────────────────────────────────────


def test_resolver_reaches_added_tab_panel(tmp_path: Path) -> None:
    """The resolver injected at EVERY panel-construction site (spec §4.1's
    single _make_panel factory) must reach a panel created via add_tab AFTER
    the 2 files are already loaded -- an added-tab panel is not exempt from
    the comparison_mode toggle's reapply (pairs with the OFF-freeze test as
    the "resolver reaches every construction site" invariant, spec §10)."""
    app_vm = AppViewModel()
    app_vm.request_load(_write_csv_n(tmp_path / "a.csv", 1), _csv_format_n(1))
    key2 = app_vm.request_load(_write_csv_n(tmp_path / "b.csv", 2), _csv_format_n(2))
    area = GraphAreaVM(app_vm)
    tab_index = area.add_tab()
    panel = area.panels(tab_index)[0]
    panel.add_signal(f"{key2}::s1")
    panel.add_signal(f"{key2}::s2")

    assert app_vm.is_comparison_mode() is False

    app_vm.set_comparison_mode(True)

    palette = active().colors.signal_palette
    hue2 = app_vm.file_hue_index[key2]
    expected = [
        hue_variant(palette[hue2].hex, 0),
        hue_variant(palette[hue2].hex, 1),
    ]
    assert _colors(panel) == expected
