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


def _make_dock(qtbot, name: str):
    from PySide6.QtWidgets import QDockWidget

    dock = QDockWidget(name)
    dock.setObjectName(name)
    qtbot.addWidget(dock)
    return dock


def test_rail_hidden_when_empty_shown_when_tab_added(qtbot):
    from valisync.gui.views.dock_collapse_rail import DockCollapseRail

    rail = DockCollapseRail(Qt.DockWidgetArea.RightDockWidgetArea)
    qtbot.addWidget(rail)
    rail.show()
    assert rail.is_empty()
    assert rail.isHidden()  # 空なら隠れる
    dock = _make_dock(qtbot, "file_dock")
    rail.add_tab(dock, "File Browser", 0)
    assert not rail.is_empty()
    assert not rail.isHidden()


def test_rail_remove_tab_hides_when_last_removed(qtbot):
    from valisync.gui.views.dock_collapse_rail import DockCollapseRail

    rail = DockCollapseRail(Qt.DockWidgetArea.RightDockWidgetArea)
    qtbot.addWidget(rail)
    rail.show()
    dock = _make_dock(qtbot, "file_dock")
    rail.add_tab(dock, "File Browser", 0)
    rail.remove_tab(dock)
    assert rail.is_empty()
    assert rail.isHidden()


def test_rail_tab_click_emits_expand_requested_with_dock(qtbot):
    from valisync.gui.views.dock_collapse_rail import DockCollapseRail

    rail = DockCollapseRail(Qt.DockWidgetArea.RightDockWidgetArea)
    qtbot.addWidget(rail)
    dock = _make_dock(qtbot, "file_dock")
    rail.add_tab(dock, "File Browser", 0)
    seen: list = []
    rail.expand_requested.connect(seen.append)
    rail._tabs[dock].clicked.emit()  # タブ本体クリック相当
    assert seen == [dock]


def test_rail_tabs_ordered_by_order_index(qtbot):
    from valisync.gui.views.dock_collapse_rail import DockCollapseRail

    rail = DockCollapseRail(Qt.DockWidgetArea.RightDockWidgetArea)
    qtbot.addWidget(rail)
    ch = _make_dock(qtbot, "channel_dock")
    fi = _make_dock(qtbot, "file_dock")
    rail.add_tab(ch, "Channel Browser", 1)  # 先に order=1 を入れても
    rail.add_tab(fi, "File Browser", 0)  # order=0 が上に来る
    lay = rail._layout
    idx_fi = lay.indexOf(rail._tabs[fi])
    idx_ch = lay.indexOf(rail._tabs[ch])
    assert idx_fi < idx_ch
