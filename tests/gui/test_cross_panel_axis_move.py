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
