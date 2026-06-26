"""Tests for Task 4: Drag & Drop Integration.

Verify that dropping signals on different zones of the GraphPanelView results
in different outcomes:
- Dropping on the plot area creates a NEW axis for each signal.
- Dropping on a Y-axis adds the signal to THAT specific axis.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDropEvent
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.gui.test_graph_panel_view import _keys, _loaded_session, _make_view
from valisync.gui.adapters.qt_signal_models import encode_signal_keys
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


class _DragEvent:
    """Duck-typed pyqtgraph MouseDragEvent.

    Exposes the exact interface ``RegionDividerItem.mouseDragEvent`` consumes,
    so a divider drag can be driven on the real view the same way a real mouse
    drag would, without mocking the view or the ViewModel.
    """

    def __init__(
        self,
        pos: QPointF,
        last_pos: QPointF,
        *,
        start: bool = False,
        finish: bool = False,
    ) -> None:
        self._pos, self._last = pos, last_pos
        self._start, self._finish = start, finish
        self.accepted = False

    def pos(self) -> QPointF:
        return self._pos

    def lastPos(self) -> QPointF:
        return self._last

    def isStart(self) -> bool:
        return self._start

    def isFinish(self) -> bool:
        return self._finish

    def button(self) -> Qt.MouseButton:
        return Qt.MouseButton.LeftButton

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


class TestContextualDrop:
    def test_first_drop_on_plot_fills_full_height(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """The FIRST signal dropped on the plot must fill the whole panel.

        The panel starts with one empty placeholder axis; dropping the first
        signal must consume it (full-height, single region) rather than leaving
        the placeholder above a half-height new region.
        """
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Force ZONE_PLOT
        view._zone_at = lambda pos: "plot"  # type: ignore

        mime = encode_signal_keys([key])
        event = QDropEvent(
            QPointF(100.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dropEvent(event)

        # One full-height region holding the signal — no empty placeholder left.
        assert len(vm.axes) == 1
        plotted = vm.inspect()["plotted_signals"]
        assert plotted[0]["signal_key"] == key
        assert plotted[0]["axis_index"] == 0
        assert vm.axes[0].height_ratio == 1.0
        assert vm.axes[0].top_ratio == 0.0

    def test_drop_on_y_axis_joins_that_axis(self, qtbot: QtBot, tmp_path: Path) -> None:
        session, _ = _loaded_session(tmp_path)
        key = _keys(session)[0]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Force ZONE_Y_INNER and axis index 0
        view._zone_at = lambda pos: "y_inner"  # type: ignore
        view._axis_index_at = lambda pos: 0  # type: ignore

        mime = encode_signal_keys([key])
        event = QDropEvent(
            QPointF(10.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dropEvent(event)

        # Still 1 axis
        assert len(vm.axes) == 1
        plotted = vm.inspect()["plotted_signals"]
        assert plotted[0]["signal_key"] == key
        assert plotted[0]["axis_index"] == 0

    def test_drop_multiple_signals_on_plot_creates_multiple_axes(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        session, _ = _loaded_session(tmp_path, n_signals=2)
        k0, k1 = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Force ZONE_PLOT
        view._zone_at = lambda pos: "plot"  # type: ignore

        mime = encode_signal_keys([k0, k1])
        event = QDropEvent(
            QPointF(100.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.dropEvent(event)

        # Two signals -> two equal regions (the placeholder is consumed).
        assert len(vm.axes) == 2
        plotted = vm.inspect()["plotted_signals"]
        assert plotted[0]["axis_index"] == 0
        assert plotted[1]["axis_index"] == 1

        # Verify ratios (1/2 = 0.5)
        for ax in vm.axes:
            assert abs(ax.height_ratio - 0.5) < 1e-6


class TestAxisResizing:
    def test_resize_axis_updates_ratios(self, tmp_path: Path) -> None:
        from valisync.core.session import Session

        session = Session()
        vm = GraphPanelVM(session)
        # Create 2 axes (0.5 each): first signal fills the panel, second splits it.
        vm.create_new_axis("sig0")
        vm.create_new_axis("sig1")
        assert len(vm.axes) == 2

        # Move divider 0 down by 0.1
        vm.resize_axis(0, 0.1)

        assert vm.axes[0].height_ratio == pytest.approx(0.6)
        assert vm.axes[1].top_ratio == pytest.approx(0.6)
        assert vm.axes[1].height_ratio == pytest.approx(0.4)

    def test_resize_axis_respects_minimum_height(self, tmp_path: Path) -> None:
        from valisync.core.session import Session

        session = Session()
        vm = GraphPanelVM(session)
        vm.create_new_axis("sig0")
        vm.create_new_axis("sig1")

        # Try to move divider 0 down so much that below axis disappears
        vm.resize_axis(0, 0.6)  # 0.5 + 0.6 = 1.1 (invalid, should cap)

        # Min height is 0.05
        assert vm.axes[1].height_ratio == pytest.approx(0.05)
        assert vm.axes[0].height_ratio == pytest.approx(0.95)


class TestMultiAxisLayout:
    def test_unit_propagation(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Verify that signal unit is propagated to the YAxisVM and then to AxisItem."""
        session, _ = _loaded_session(tmp_path)
        # Manually set a unit on a signal
        sig_name = _keys(session)[0]
        for sig in session.signals():
            if sig.name == sig_name:
                sig.metadata["unit"] = "m/s"
                break

        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Add signal to first axis
        vm.add_signal_to_axis(sig_name, 0)

        # Check VM
        assert vm.axes[0].unit == "m/s"

        # Check View (AxisItem)
        # Note: AxisItem.labelUnits might be used, or just prefix in label
        axis_item = view._y_axes[0]
        assert axis_item.labelUnits == "m/s"

    def test_x_axis_not_crushed(self, qtbot: QtBot, tmp_path: Path) -> None:
        """Verify that X-axis doesn't get crushed when Y-axis has high stretch."""
        session, _ = _loaded_session(tmp_path, n_signals=2)
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Add two axes with signals
        vm.add_signal_to_axis(_keys(session)[0], 0)
        vm.create_new_axis(_keys(session)[1])

        # Force a high stretch factor in VM
        vm.axes[0].height_ratio = 0.9
        vm.axes[1].height_ratio = 0.1
        view.refresh()

        # Check X-axis height. It should be a positive reasonable value.
        x_axis_height = view._x_axis.boundingRect().height()
        assert x_axis_height > 10  # Typically ~20-30px

        # Check layout stretch factors
        # Root layout should have Row 0 stretch=1, Row 1 stretch=0
        root_layout = view.plot_widget.ci.layout
        assert root_layout.rowStretchFactor(0) == 1
        assert root_layout.rowStretchFactor(1) == 0

    def test_waveforms_render_in_their_home_regions(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Each axis's data range must map into its own vertical region.

        Regression for the multi-ViewBox vertical-transform bug: secondary
        ViewBoxes kept stale geometry, so their waveforms were drawn outside
        their home region (e.g. the bottom region rendered empty).
        """
        session, _ = _loaded_session(tmp_path, n_signals=3)
        keys = _keys(session)
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal_to_axis(keys[0], 0)
        vm.create_new_axis(keys[1])
        vm.create_new_axis(keys[2])

        view.resize(1000, 700)
        view.show()
        qtbot.waitExposed(view)
        # Wait until the layout assigns the plot area real geometry.
        qtbot.waitUntil(
            lambda: view._view_boxes[0].geometry().height() > 100, timeout=2000
        )
        view.refresh()

        master = view._view_boxes[0].geometry()
        top, height = master.y(), master.height()
        for i, axis_vm in enumerate(vm.axes):
            assert axis_vm.y_range is not None
            y_lo, y_hi = axis_vm.y_range
            p_hi = view._view_boxes[i].mapViewToScene(QPointF(0.0, y_hi)).y()
            p_lo = view._view_boxes[i].mapViewToScene(QPointF(0.0, y_lo)).y()
            band_top = top + axis_vm.top_ratio * height
            band_bot = top + (axis_vm.top_ratio + axis_vm.height_ratio) * height
            tol = 2.0
            assert band_top - tol <= p_hi <= band_bot + tol, (
                f"axis {i}: data top maps to {p_hi:.1f}, "
                f"home band [{band_top:.1f}, {band_bot:.1f}]"
            )
            assert band_top - tol <= p_lo <= band_bot + tol, (
                f"axis {i}: data bottom maps to {p_lo:.1f}, "
                f"home band [{band_top:.1f}, {band_bot:.1f}]"
            )

    def test_y_axis_shows_data_range_not_virtual(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Y-axis ticks must reflect the data range, not the expanded virtual range.

        The ViewBox uses an expanded 'virtual' range to place data in a sub-region;
        the AxisItem must still display the real data range so its labels are correct.
        """
        session, _ = _loaded_session(tmp_path, n_signals=2)
        keys = _keys(session)
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal_to_axis(keys[0], 0)
        vm.create_new_axis(keys[1])
        view.refresh()

        for i, axis_vm in enumerate(vm.axes):
            assert axis_vm.y_range is not None
            lo, hi = axis_vm.y_range
            ax_lo, ax_hi = view._y_axes[i].range
            assert ax_lo == pytest.approx(lo, abs=1e-6), f"axis {i} low"
            assert ax_hi == pytest.approx(hi, abs=1e-6), f"axis {i} high"

    def test_no_orphaned_viewboxes_after_adding_axes(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Rebuilding for each new axis must not leave stale ViewBoxes behind.

        Regression: secondary ViewBoxes added directly to the scene were not
        removed on rebuild (ci.clear() only drops layout-managed items), so a
        signal from an intermediate build was drawn twice by the orphan.
        """
        import pyqtgraph as pg

        session, _ = _loaded_session(tmp_path, n_signals=3)
        keys = _keys(session)
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal_to_axis(keys[0], 0)
        vm.create_new_axis(keys[1])
        vm.create_new_axis(keys[2])
        view.refresh()

        scene_vbs = [
            it for it in view.plot_widget.scene().items() if isinstance(it, pg.ViewBox)
        ]
        assert len(scene_vbs) == len(vm.axes), (
            f"{len(scene_vbs)} ViewBoxes in scene for {len(vm.axes)} axes "
            "(orphans left behind)"
        )

        # Each plotted signal must be drawn by exactly one ViewBox.
        counts: dict[str, int] = {}
        for vb in scene_vbs:
            for it in vb.addedItems:
                if isinstance(it, pg.PlotDataItem) and it.name():
                    counts[it.name()] = counts.get(it.name(), 0) + 1
        assert all(c == 1 for c in counts.values()), f"duplicated curves: {counts}"

    def test_dragging_divider_resizes_adjacent_regions(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """E2E: a divider drag resizes adjacent regions through the real VM.

        Drives `RegionDividerItem.mouseDragEvent` on the real (shown) view with
        synthesized start/move/finish events — the same handler path a real
        mouse drag exercises — and checks the height ratios shift accordingly.
        This is the "adjust their heights" gesture of the Task 3.3 E2E check.
        """
        session, _ = _loaded_session(tmp_path, n_signals=3)
        keys = _keys(session)
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.add_signal_to_axis(keys[0], 0)
        vm.create_new_axis(keys[1])
        vm.create_new_axis(keys[2])
        view.resize(1000, 700)
        view.show()
        qtbot.waitExposed(view)
        qtbot.waitUntil(
            lambda: view._view_boxes[0].geometry().height() > 100, timeout=2000
        )

        before = [a.height_ratio for a in vm.axes]
        assert before == pytest.approx([1 / 3, 1 / 3, 1 / 3], abs=1e-3)

        divider = view._dividers[0]  # divider between region 0 and region 1
        view_h = divider.getViewWidget().height()
        assert view_h > 0
        dy = 0.15 * view_h  # drag down by 15% of the view height
        divider.mouseDragEvent(_DragEvent(QPointF(0, 0), QPointF(0, 0), start=True))
        divider.mouseDragEvent(_DragEvent(QPointF(0, dy), QPointF(0, 0)))
        divider.mouseDragEvent(_DragEvent(QPointF(0, dy), QPointF(0, dy), finish=True))

        after = [a.height_ratio for a in vm.axes]
        delta = dy / view_h  # == 0.15
        # Region 0 grows by ~delta, region 1 shrinks by ~delta, region 2 is fixed.
        assert after[0] == pytest.approx(before[0] + delta, abs=1e-3)
        assert after[1] == pytest.approx(before[1] - delta, abs=1e-3)
        assert after[2] == pytest.approx(before[2], abs=1e-3)
        # Ratios always remain a valid partition of the panel height.
        assert sum(after) == pytest.approx(1.0, abs=1e-6)

    def test_stacked_yaxes_share_one_fixed_width(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """All stacked Y-axes use a single fixed width.

        So their tick spines (and right-aligned tick numbers) line up into one
        vertical edge instead of being ragged per label magnitude. The width is
        fixed (not data-dependent) and wide enough for ~6 digits / scientific
        notation, so the layout never shifts when the displayed signals change.
        """
        session, _ = _loaded_session(tmp_path, n_signals=3)
        keys = _keys(session)
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.create_new_axis(keys[0])
        vm.create_new_axis(keys[1])
        vm.create_new_axis(keys[2])
        view.refresh()

        widths = [round(ax.width(), 1) for ax in view._y_axes]
        # One uniform width across every stacked axis.
        assert len(set(widths)) == 1, f"ragged Y-axis widths: {widths}"
        # Wide enough for ~6-digit / scientific labels (e.g. "-1.2e+06").
        assert widths[0] >= 60, f"fixed Y-axis width too small: {widths[0]}"
