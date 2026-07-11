"""Layer B: rendered-geometry tests — the View must paint the VM's absolute
region layout (blank gaps included), not normalize/fill. Asserts actual
sceneBoundingRect() geometry, NOT VM values (the gap the prior tests missed)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pytestqt.qtbot import QtBot

from tests.gui.test_graph_panel_view import (
    _keys,
    _loaded_session,
    _make_view,
    _multi_group_session,
)
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.views.graph_panel_view import GraphPanelView

# NOTE: _keys/_loaded_session/_make_view are the project's existing GUI-test
# helpers in tests/gui/test_graph_panel_view.py (re-imported the same way by
# tests/gui/test_graph_panel_multi_axis.py:19). _make_view returns `object`,
# hence the cast.


def _mounted(qtbot: QtBot, vm: GraphPanelVM) -> GraphPanelView:
    """Mount the view over a VM whose axes are already configured, show it, and
    wait until layout geometry has settled (mirrors the mount pattern in
    test_dragging_divider_is_column_scoped)."""
    view = cast(GraphPanelView, _make_view(qtbot, vm))
    view.resize(1000, 700)
    view.show()
    qtbot.waitExposed(view)
    view.refresh()
    qtbot.waitUntil(
        lambda: (
            bool(view._view_boxes)
            and view._view_boxes[0].sceneBoundingRect().height() > 100
        ),
        timeout=3000,
    )
    return view


def _plot_rect(view: GraphPanelView):
    return view._view_boxes[0].sceneBoundingRect()


def _strip_of_axis(view: GraphPanelView, i: int):
    """Return (top_frac, height_frac) of axis i's spine within the plot Y-band."""
    R = _plot_rect(view)
    rect = view._y_axes[i].sceneBoundingRect()
    return ((rect.y() - R.y()) / R.height(), rect.height() / R.height())


def test_axis_spines_render_at_absolute_strips_with_blank_gap(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """3 regions 0.5/0.3/0.2 in one column, delete the middle -> survivors render
    at absolute strips (A=[0,0.5], C=[0.8,1.0]) with a blank band [0.5,0.8].

    A fresh GraphPanelVM(session) has zero axes; three create_new_axis calls
    stack three regions in the inner column (column_count-1)."""
    session, keys = _multi_group_session(tmp_path, n_groups=3)
    keys = sorted(keys)
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])
    vm.create_new_axis(keys[1])
    vm.create_new_axis(keys[2])
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.5
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.5, 0.3
    vm.axes[2].top_ratio, vm.axes[2].height_ratio = 0.8, 0.2

    view = _mounted(qtbot, vm)
    # Unload the middle signal's group -> VM leaves A(0,0.5)/C(0.8,0.2) with a blank gap.
    session.remove_group(keys[1].split("::", 1)[0])
    vm.prune_missing_signals()
    view.refresh()
    qtbot.waitUntil(lambda: len(view._y_axes) == 2, timeout=2000)

    # Survivors sorted by rendered top.
    strips = sorted(_strip_of_axis(view, i) for i in range(len(view._y_axes)))
    (a_top, a_h), (c_top, c_h) = strips
    assert a_top == pytest.approx(0.0, abs=0.03)
    assert a_h == pytest.approx(0.5, abs=0.03)
    assert c_top == pytest.approx(0.8, abs=0.03)
    assert c_h == pytest.approx(0.2, abs=0.03)
    # The middle band [0.5,0.8] must contain NO axis spine rect.
    R = _plot_rect(view)
    gap_lo, gap_hi = R.y() + 0.55 * R.height(), R.y() + 0.75 * R.height()
    for i in range(len(view._y_axes)):
        r = view._y_axes[i].sceneBoundingRect()
        assert not (r.y() < gap_hi and r.y() + r.height() > gap_lo), (
            "an axis spine overlaps the blank band — gap not rendered (filled)"
        )


def test_axis_spine_renders_at_absolute_strip(qtbot: QtBot, tmp_path: Path) -> None:
    """Each spine renders at its absolute top strip (top_ratio / height_ratio from VM)."""
    session, _ = _loaded_session(tmp_path, n_signals=2)
    keys = sorted(_keys(session))
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])
    vm.create_new_axis(keys[1])
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.7
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.7, 0.3

    view = _mounted(qtbot, vm)
    for i, expected_top in ((0, 0.0), (1, 0.7)):
        top_frac, _h = _strip_of_axis(view, i)
        assert top_frac == pytest.approx(expected_top, abs=0.03), (
            f"axis {i} spine not at its absolute strip (got {top_frac})"
        )


def test_region_geometry_follows_resize(qtbot: QtBot, tmp_path: Path) -> None:
    """After a window resize, each region's spine still renders at its absolute
    strip (the sigResized -> _sync_overlay_geometry path keeps ratios)."""
    session, _ = _loaded_session(tmp_path, n_signals=2)
    keys = sorted(_keys(session))
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])
    vm.create_new_axis(keys[1])
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.7
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.7, 0.3
    view = _mounted(qtbot, vm)
    view.resize(1200, 900)
    qtbot.waitUntil(lambda: _plot_rect(view).height() > 100, timeout=2000)
    top0, h0 = _strip_of_axis(view, 0)
    assert top0 == pytest.approx(0.0, abs=0.03)
    assert h0 == pytest.approx(0.7, abs=0.03)
    top1, h1 = _strip_of_axis(view, 1)
    assert top1 == pytest.approx(0.7, abs=0.03)
    assert h1 == pytest.approx(0.3, abs=0.03)


def test_waveform_data_band_coincides_with_axis_spine_strip(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """The waveform (ViewBox data band) must render in the SAME absolute strip as
    its axis spine — spine ticks and curve aligned, not just the spine geometry.

    Maps each axis's data y-range through its ViewBox to scene coords
    (mapViewToScene) and compares to the spine strip, BEFORE and AFTER a prune.
    Guards waveform<->spine alignment, which the spine-only tests do not assert.
    """
    from PySide6.QtCore import QPointF

    session, keys = _multi_group_session(tmp_path, n_groups=3)
    keys = sorted(keys)
    vm = GraphPanelVM(session)
    vm.create_new_axis(keys[0])
    vm.create_new_axis(keys[1])
    vm.create_new_axis(keys[2])
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.2
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.2, 0.5
    vm.axes[2].top_ratio, vm.axes[2].height_ratio = 0.7, 0.3

    view = _mounted(qtbot, vm)

    def _assert_waveform_aligned_with_spine() -> None:
        R = _plot_rect(view)
        for i, ax in enumerate(vm.axes):
            assert ax.y_range is not None, f"axis {i}: no y_range (data not mapped)"
            y_lo, y_hi = ax.y_range
            vb = view._view_boxes[i]
            # data y_hi -> top of the data band; y_lo -> bottom (scene coords)
            data_top = (vb.mapViewToScene(QPointF(0.0, y_hi)).y() - R.y()) / R.height()
            data_bot = (vb.mapViewToScene(QPointF(0.0, y_lo)).y() - R.y()) / R.height()
            spine_top, spine_h = _strip_of_axis(view, i)
            spine_bot = spine_top + spine_h
            assert data_top == pytest.approx(spine_top, abs=0.03), (
                f"axis {i}: waveform top {data_top:.3f} != spine top {spine_top:.3f}"
            )
            assert data_bot == pytest.approx(spine_bot, abs=0.03), (
                f"axis {i}: waveform bot {data_bot:.3f} != spine bot {spine_bot:.3f}"
            )

    _assert_waveform_aligned_with_spine()  # 3 contiguous regions

    # Unload the middle signal's group: survivors keep absolute strips; the
    # waveform must still coincide with its (repositioned) spine, blank gap between.
    session.remove_group(keys[1].split("::", 1)[0])
    vm.prune_missing_signals()
    view.refresh()
    qtbot.waitUntil(lambda: len(view._y_axes) == 2, timeout=2000)
    _assert_waveform_aligned_with_spine()  # 2 survivors with a blank gap
