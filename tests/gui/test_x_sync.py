"""Tests for X-axis sync in the Graph_Area view — Task 8.4.

GraphAreaView injects real GraphPanelViews and exposes a sync toggle.  The
sync coordination itself lives in GraphAreaVM (a panel's X-range change drives
its siblings when enabled); here we verify the view wires real panels through
that path and that the toggle reflects/drives the VM (R7.1-7.4).

TDD: written before the wiring exists; all must FAIL first.
"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.views.graph_panel_view import ZONE_X_INNER, GraphPanelView

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


# ─── Sync toggle UI (R7.3) ─────────────────────────────────────────────────────


class TestToggle:
    def test_checkbox_defaults_to_enabled(self, qtbot: QtBot) -> None:
        view, _ = _make_area(qtbot)
        assert view.sync_checkbox.isChecked() is True  # type: ignore[attr-defined]

    def test_unchecking_disables_vm_sync(self, qtbot: QtBot) -> None:
        view, vm = _make_area(qtbot)
        view.sync_checkbox.setChecked(False)  # type: ignore[attr-defined]
        assert vm.tabs()[0].x_sync_enabled is False

    def test_checkbox_reflects_vm_state_change(self, qtbot: QtBot) -> None:
        view, vm = _make_area(qtbot)
        vm.set_x_sync(0, False)  # external change → checkbox follows
        assert view.sync_checkbox.isChecked() is False  # type: ignore[attr-defined]
