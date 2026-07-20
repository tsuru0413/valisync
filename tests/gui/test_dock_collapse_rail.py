"""DockCollapseRail — 辺対応の折りたたみレール (edge-aware-collapse)。"""

from __future__ import annotations

from PySide6.QtCore import Qt


def test_rail_kind_for_area_maps_edges():
    from valisync.gui.views.dock_collapse_rail import RailKind, rail_kind_for_area

    assert rail_kind_for_area(Qt.DockWidgetArea.LeftDockWidgetArea) is RailKind.VERTICAL
    assert (
        rail_kind_for_area(Qt.DockWidgetArea.RightDockWidgetArea) is RailKind.VERTICAL
    )
    assert (
        rail_kind_for_area(Qt.DockWidgetArea.BottomDockWidgetArea)
        is RailKind.HORIZONTAL
    )


def test_rail_kind_for_area_unsupported_is_none():
    from valisync.gui.views.dock_collapse_rail import rail_kind_for_area

    assert rail_kind_for_area(Qt.DockWidgetArea.TopDockWidgetArea) is None
    assert rail_kind_for_area(Qt.DockWidgetArea.NoDockWidgetArea) is None
