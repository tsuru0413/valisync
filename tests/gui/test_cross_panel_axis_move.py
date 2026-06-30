"""Layer A/B: cross-panel axis move — MIME, VM logic, and view wiring."""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

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


def _area_two_panels(tmp_path: Path):  # type: ignore[no-untyped-def]
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


def test_move_axis_across_panels_same_panel_noop(tmp_path: Path) -> None:
    area, p0, _p1, _keys = _area_two_panels(tmp_path)
    before = sorted(e.signal_key for e in p0._plotted)
    area.move_axis_across_panels(0, 0, 0, 0, column=0, position=None)  # src==dst
    assert sorted(e.signal_key for e in p0._plotted) == before


def test_move_axis_across_panels_stale_index_noop(tmp_path: Path) -> None:
    area, _p0, p1, _keys = _area_two_panels(tmp_path)
    area.move_axis_across_panels(0, 0, 99, 1, column=0, position=None)  # axis 99 absent
    assert [e.signal_key for e in p1._plotted] == []
