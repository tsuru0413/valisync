"""Tests for X-axis sync in the Graph_Area view — Task 8.4.

GraphAreaView injects real GraphPanelViews, which each carry a
"X軸同期(タブ内全パネル)" checkable item (ASCII-safe parens here — the real
label, matched via _SYNC_LABEL below, uses full-width parens) on their
blank-area context menu (計測 IA 刷新 spec §2.3 / v3 決定4 — the standalone
"Sync X" checkbox was retired in favor of right-click-only). The sync
coordination itself lives in
GraphAreaVM (a panel's X-range change drives its siblings when enabled); here
we verify the view wires real panels through that path and that the menu item
reflects/drives the VM (R7.1-7.4), via an injected getter/setter pair (the
flag's ownership stays on GraphAreaView, not the panel).

TDD: written before the wiring exists; all must FAIL first.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QAction
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import ZONE_X_INNER, GraphPanelView

_SYNC_LABEL = "X軸同期（タブ内全パネル）"  # noqa: RUF001

# ─── Helpers ────────────────────────────────────────────────────────────────


def _make_area(qtbot: QtBot) -> tuple[object, GraphAreaVM]:
    from valisync.gui.views.graph_area_view import GraphAreaView

    vm = GraphAreaVM(AppViewModel(Session()))
    vm.add_panel(0)  # 2 panels in tab 0
    view = GraphAreaView(vm)
    qtbot.addWidget(view)
    return view, vm


def _panel_view(view: object, tab: int, panel: int) -> GraphPanelView:
    page = view.tabs.widget(tab)  # type: ignore[attr-defined]
    widget = page.widget(panel)
    assert isinstance(widget, GraphPanelView)
    return widget


def _sync_action(panel: GraphPanelView) -> QAction:
    """The panel's blank-menu "X軸同期(タブ内全パネル)" item (spec §2.3)."""
    return next(
        a for a in panel.build_context_menu().actions() if a.text() == _SYNC_LABEL
    )


# ─── Default factory builds real panels ───────────────────────────────────────


class TestFactory:
    def test_default_factory_builds_graph_panel_views(self, qtbot: QtBot) -> None:
        view, _ = _make_area(qtbot)
        assert isinstance(_panel_view(view, 0, 0), GraphPanelView)
        assert isinstance(_panel_view(view, 0, 1), GraphPanelView)


# ─── Propagation through real panel views (R7.1/R7.2) ──────────────────────────


class TestPropagation:
    def test_sync_on_zoom_propagates_to_sibling(self, qtbot: QtBot) -> None:
        view, vm = _make_area(qtbot)
        vm.set_x_sync(0, True)

        # Zoom panel 0 via its view's gesture method.
        _panel_view(view, 0, 0).apply_zone_drag(ZONE_X_INNER, 0.2, 0.5)

        assert vm.panels(0)[1].x_range == pytest.approx((0.2, 0.5))

    def test_sync_off_zoom_stays_local(self, qtbot: QtBot) -> None:
        view, vm = _make_area(qtbot)
        vm.set_x_sync(0, False)

        _panel_view(view, 0, 0).apply_zone_drag(ZONE_X_INNER, 0.2, 0.5)

        assert vm.panels(0)[0].x_range == pytest.approx((0.2, 0.5))
        assert vm.panels(0)[1].x_range is None


# ─── Sync toggle menu item (R7.3; 計測 IA 刷新 spec §2.3 — 右クリックのみ) ──────


class TestToggle:
    def test_menu_item_defaults_to_enabled(self, qtbot: QtBot) -> None:
        view, _ = _make_area(qtbot)
        act = _sync_action(_panel_view(view, 0, 0))
        assert act.isCheckable()
        assert act.isChecked() is True

    def test_trigger_disables_vm_sync(self, qtbot: QtBot) -> None:
        view, vm = _make_area(qtbot)
        _sync_action(_panel_view(view, 0, 0)).trigger()  # user click → False
        assert vm.tabs()[0].x_sync_enabled is False

    def test_menu_item_reflects_vm_state_change(self, qtbot: QtBot) -> None:
        view, vm = _make_area(qtbot)
        vm.set_x_sync(0, False)  # external change → next menu build reflects it
        act = _sync_action(_panel_view(view, 0, 0))
        assert act.isChecked() is False

    def test_trigger_toggle_actually_drives_propagation(self, qtbot: QtBot) -> None:
        """弱体化禁止 (spec §2.3): ON で 2 パネル追随・OFF で追随しないという既存
        挙動 (旧 test_checkbox_* が checkbox 経由で守っていたもの) を、右クリック
        メニューの trigger 配線経由でも守り続けることを実証する。"""
        view, vm = _make_area(qtbot)
        panel0 = _panel_view(view, 0, 0)

        _sync_action(panel0).trigger()  # default ON → OFF
        assert vm.tabs()[0].x_sync_enabled is False
        panel0.apply_zone_drag(ZONE_X_INNER, 0.2, 0.5)
        assert vm.panels(0)[1].x_range is None  # OFF: sibling untouched

        _sync_action(panel0).trigger()  # OFF → ON
        assert vm.tabs()[0].x_sync_enabled is True
        panel0.apply_zone_drag(ZONE_X_INNER, 0.3, 0.6)
        assert vm.panels(0)[1].x_range == pytest.approx((0.3, 0.6))  # ON: follows


# ─── Uninjected GraphPanelView (bare harness — spec §2.3) ──────────────────────


class TestUninjected:
    def test_bare_panel_view_has_no_sync_menu_item(self, qtbot: QtBot) -> None:
        """未注入 (getter/setter なし) の GraphPanelView 単体構成では項目を出さない
        — GraphPanelView の area 非依存を保つ (既存 headless/realgui のメニュー
        列挙が壊れない互換路)。"""
        vm = GraphPanelVM(Session())
        panel = GraphPanelView(vm)
        qtbot.addWidget(panel)
        texts = [a.text() for a in panel.build_context_menu().actions()]
        assert _SYNC_LABEL not in texts
