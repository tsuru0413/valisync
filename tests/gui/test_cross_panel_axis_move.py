"""Layer A/B: cross-panel axis move — MIME, VM logic, and view wiring."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM

from valisync.gui.adapters.qt_signal_models import decode_axis_move, encode_axis_move


def test_axis_move_mime_roundtrip() -> None:
    md = encode_axis_move(2, 5)
    assert decode_axis_move(md) == (2, 5)


def test_decode_axis_move_none_without_payload() -> None:
    from PySide6.QtCore import QMimeData

    assert decode_axis_move(QMimeData()) is None


def test_panel_index_set_via_wire(qtbot: QtBot, tmp_path: Path) -> None:
    from tests.gui._panel_factory import make_two_axis_panel
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = make_two_axis_panel()
    qtbot.addWidget(view)
    assert isinstance(view, GraphPanelView)
    view.set_panel_index(3)
    assert view._panel_index == 3


# ─── Layer A/B: VM logic tests ───────────────────────────────────────────────


def _area_two_panels(
    tmp_path: Path,
) -> tuple[GraphAreaVM, GraphPanelVM, GraphPanelVM, list[str]]:
    """GraphAreaVM with one tab, two panels sharing a session; panel0 has 2 signals
    (axis0=k0, axis1=k1), panel1 empty. Returns (area_vm, p0, p1, keys)."""
    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM

    csv = tmp_path / "d.csv"
    csv.write_text("t,a,b\n0,1,4\n1,2,5\n", encoding="utf-8")
    session = Session()
    session.load(
        csv,
        FormatDefinition(
            name="f",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=2,
            has_header=True,
        ),
    )
    keys = sorted(s.name for s in session.signals())
    area = GraphAreaVM(AppViewModel(session))
    area.add_panel(0)  # tab 0 now has 2 panels (panel0 default + panel1)
    p0, p1 = area.panels(0)[0], area.panels(0)[1]
    p0.add_signal_to_axis(keys[0], 0)
    p0.create_new_axis(keys[1])  # p0: axis0=k0, axis1=k1
    return area, p0, p1, keys


def test_move_axis_across_panels_moves_signal(tmp_path: Path) -> None:
    area, p0, p1, keys = _area_two_panels(tmp_path)
    assert keys[0] in [e.signal_key for e in p0._plotted]
    area.move_axis_across_panels(
        0, 0, 0, 1, column=0, position=None
    )  # move p0.axis0 → p1
    p0_keys = [e.signal_key for e in p0._plotted]
    p1_keys = [e.signal_key for e in p1._plotted]
    assert keys[0] not in p0_keys, "moved signal still in source"
    assert keys[0] in p1_keys, "moved signal absent from target"
    assert keys[1] in p0_keys, "non-moved signal was incorrectly dropped from source"


def test_move_axis_across_panels_same_panel_noop(tmp_path: Path) -> None:
    area, p0, _p1, _keys = _area_two_panels(tmp_path)
    before = sorted(e.signal_key for e in p0._plotted)
    area.move_axis_across_panels(0, 0, 0, 0, column=0, position=None)  # src==dst
    assert sorted(e.signal_key for e in p0._plotted) == before


def test_move_axis_across_panels_stale_index_noop(tmp_path: Path) -> None:
    area, _p0, p1, _keys = _area_two_panels(tmp_path)
    area.move_axis_across_panels(0, 0, 99, 1, column=0, position=None)  # axis 99 absent
    assert [e.signal_key for e in p1._plotted] == []


def test_extract_single_axis_placeholder_is_distinct(tmp_path: Path) -> None:
    """After extracting the ONLY axis from a single-axis source, the source's empty-
    panel placeholder must be a DISTINCT YAxisVM from the extracted axis.

    Without the fix, _compact_axes keeps self._axes[0] == axis (the same object),
    so insert_axis's move_axis_to_column mutates the source placeholder's
    top_ratio/height_ratio/column — cross-contaminating the source.
    This test FAILS before the alias-break fix and PASSES after.
    """
    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.core.session import Session
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM

    csv = tmp_path / "d.csv"
    csv.write_text("t,a\n0,1\n1,2\n", encoding="utf-8")
    session = Session()
    session.load(
        csv,
        FormatDefinition(
            name="f",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    keys = sorted(s.name for s in session.signals())
    area = GraphAreaVM(AppViewModel(session))
    area.add_panel(0)  # tab 0 now has 2 panels
    p0, p1 = area.panels(0)[0], area.panels(0)[1]
    # p0 starts with exactly 1 axis (the default placeholder); add one signal so
    # extract_axis has an actual axis to pull out.
    p0.add_signal_to_axis(keys[0], 0)
    assert len(p0._axes) == 1, "pre-condition: p0 is single-axis"

    # Capture the axis object before extraction.
    orig_axis = p0._axes[0]

    # Extract axis 0 (the ONLY axis) → _compact_axes no-signals branch fires.
    result = p0.extract_axis(0)
    assert result is not None
    extracted_axis, _entries = result

    # The extracted axis must be the original one.
    assert extracted_axis is orig_axis

    # The source placeholder must be a DISTINCT object (the alias-break fix).
    assert p0._axes[0] is not extracted_axis, (
        "source placeholder is still the same object as the extracted axis — "
        "alias-break fix is missing"
    )

    # Spot-check that the placeholder has the correct default layout values.
    assert p0._axes[0].top_ratio == 0.0
    assert p0._axes[0].height_ratio == 1.0
    assert p0._axes[0].column == p0._column_count - 1

    # Confirm that inserting the axis into p1 does NOT mutate the source placeholder.
    p1.insert_axis(extracted_axis, _entries, column=0, position=None)
    assert p0._axes[0] is not extracted_axis, (
        "insert_axis corrupted the source placeholder identity"
    )
    src_top_before = p0._axes[0].top_ratio
    src_h_before = p0._axes[0].height_ratio
    # Mutating the target axis layout should not change the source placeholder.
    extracted_axis.top_ratio = 0.5
    assert p0._axes[0].top_ratio == src_top_before, (
        "source placeholder top_ratio changed when extracted axis was mutated"
    )
    extracted_axis.height_ratio = 0.5
    assert p0._axes[0].height_ratio == src_h_before, (
        "source placeholder height_ratio changed when extracted axis was mutated"
    )
