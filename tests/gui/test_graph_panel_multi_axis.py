"""Tests for Task 4: Drag & Drop Integration.

Verify that dropping signals on different zones of the GraphPanelView results
in different outcomes:
- Dropping on the plot area creates a NEW axis for each signal.
- Dropping on a Y-axis adds the signal to THAT specific axis.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QDropEvent
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.gui.test_graph_panel_view import _keys, _loaded_session, _make_view
from valisync.gui.adapters.qt_signal_models import encode_axis_index, encode_signal_keys
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
from valisync.gui.viewmodels.y_axis_vm import YAxisVM
from valisync.gui.views.graph_panel_view import _Y_AXIS_FIXED_WIDTH, GraphPanelView


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

    def test_plain_drop_on_empty_y_axis_places_signal(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Plain drop (no modifier) onto an empty axis writes the signal onto axis 0.

        Under R5 this is an overwrite of an empty axis — the observable result is
        the same as the old join behaviour: the signal lands on axis 0.
        """
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

    def test_plain_drop_on_populated_axis_overwrites(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Plain drop (no modifier) onto a populated axis replaces its signals.

        R5 key behaviour: a plain drop replaces the axis contents — signal A is
        removed and only the dropped signal B remains on axis 0.
        """
        from PySide6.QtWidgets import QApplication

        session, _ = _loaded_session(tmp_path, n_signals=2)
        key_a, key_b = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Populate axis 0 with signal A.
        vm.add_signal_to_axis(key_a, 0)

        # Stub geometry helpers so the drop hits ZONE_Y_INNER / axis 0.
        view._zone_at = lambda pos: "y_inner"  # type: ignore
        view._axis_index_at = lambda pos: 0  # type: ignore

        # Hold mime in a local variable — GC'd mime mid-send is a known pitfall.
        mime = encode_signal_keys([key_b])
        event = QDropEvent(
            QPointF(10.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        # Try sendEvent for the real Qt dispatch path; dropEvent is the fallback.
        routed = QApplication.sendEvent(view, event)
        if not routed or _signals_on_axis(vm, 0) == [key_a]:
            # sendEvent did not route to dropEvent under offscreen — use handler path.
            view.dropEvent(event)

        # Plain drop must replace: only key_b remains, key_a is gone.
        assert _signals_on_axis(vm, 0) == [key_b]

    def test_ctrl_drop_on_populated_axis_adds_signal(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Ctrl+drop onto a populated axis adds the new signal (keeps both).

        R5: Ctrl modifier means join — the existing signal and the dropped signal
        must both be present on axis 0 after the drop.
        """
        from PySide6.QtWidgets import QApplication

        session, _ = _loaded_session(tmp_path, n_signals=2)
        key_a, key_b = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Populate axis 0 with signal A.
        vm.add_signal_to_axis(key_a, 0)

        view._zone_at = lambda pos: "y_inner"  # type: ignore
        view._axis_index_at = lambda pos: 0  # type: ignore

        mime = encode_signal_keys([key_b])
        event = QDropEvent(
            QPointF(10.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
        )
        routed = QApplication.sendEvent(view, event)
        if not routed or key_b not in _signals_on_axis(vm, 0):
            view.dropEvent(event)

        # Ctrl-add must keep both signals.
        assert set(_signals_on_axis(vm, 0)) == {key_a, key_b}

    def test_plain_drop_on_plot_background_creates_new_axis(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Plain drop on the plot background creates a new axis (unchanged R5 rule).

        The plot-background branch is unaffected by the R5 overwrite/Ctrl-add
        change — each dropped signal still calls create_new_axis.

        Pre-populate axis 0 with key_a so the placeholder is already consumed;
        then a plot drop of key_b must create a second axis (len goes 1 → 2).
        """
        from PySide6.QtWidgets import QApplication

        session, _ = _loaded_session(tmp_path, n_signals=2)
        key_a, key_b = _keys(session)[:2]
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)

        # Consume the placeholder so the VM is in a real (non-trivial) state.
        vm.add_signal_to_axis(key_a, 0)
        before = len(vm.axes)  # == 1

        view._zone_at = lambda pos: "plot"  # type: ignore

        mime = encode_signal_keys([key_b])
        event = QDropEvent(
            QPointF(100.0, 100.0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        routed = QApplication.sendEvent(view, event)
        if not routed or len(vm.axes) == before:
            # sendEvent did not route to dropEvent under offscreen — use handler path.
            view.dropEvent(event)

        # A new axis must have been created (1 → 2).
        assert len(vm.axes) > before

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

    def test_axis_tick_labels_use_uniform_scientific(self, qtbot: QtBot) -> None:
        """When any tick on an axis is scientific, all non-zero ticks are too.

        Plain pyqtgraph mixes e.g. "500000" and "1e+06" on the same axis; here
        the whole axis switches to scientific (0 stays "0").
        """
        from valisync.gui.views.graph_panel_view import _AlignedAxisItem

        ax = _AlignedAxisItem(orientation="left")
        mixed = ax.tickStrings([0, 5e5, 1e6, -5e5, -1e6], 1.0, 5e5)
        assert mixed == ["0", "5e+05", "1e+06", "-5e+05", "-1e+06"]
        # Non-round values keep precision.
        assert ax.tickStrings([0, 1.5e6], 1.0, 1.5e6) == ["0", "1.5e+06"]
        # No scientific anywhere -> untouched.
        assert ax.tickStrings([0, 0.5, 1.0], 1.0, 0.5) == ["0", "0.5", "1.0"]

    def test_axis_label_shows_first_signal_name_and_unit(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """The Y-axis label shows the representative signal's short name + unit.

        Representative = first signal added to that axis; name = the part after
        the namespace separator "::".
        """
        session, _ = _loaded_session(tmp_path, n_signals=2)
        names = _keys(session)
        for sig in session.signals():
            sig.metadata["unit"] = "V"
        vm = GraphPanelVM(session)
        view = _make_view(qtbot, vm)
        vm.create_new_axis(names[0])  # first signal -> representative
        vm.add_signal_to_axis(names[1], 0)  # joined; must NOT change the label
        view.refresh()

        short = names[0].split("::")[-1]
        assert vm.axes[0].name == short
        assert view._y_axes[0].labelText == short
        assert view._y_axes[0].labelUnits == "V"

    def test_remove_signal_prunes_now_empty_axis(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """Removing the only signal on an axis drops that axis (no empty region)."""
        session, _ = _loaded_session(tmp_path, n_signals=2)
        keys = _keys(session)
        vm = GraphPanelVM(session)
        vm.create_new_axis(keys[0])
        vm.create_new_axis(keys[1])
        assert len(vm.axes) == 2

        vm.remove_signal(keys[0])

        assert len(vm.axes) == 1  # empty axis pruned
        assert vm.axes[0].height_ratio == 1.0
        plotted = [p["signal_key"] for p in vm.inspect()["plotted_signals"]]
        assert plotted == [keys[1]]

    def test_remove_signal_preserves_remaining_proportions(self) -> None:
        """Removing the middle of 3 regions keeps survivors' relative heights."""
        from valisync.core.session import Session

        vm = GraphPanelVM(Session())
        vm.add_signal_to_axis("s::a", 0)
        vm.create_new_axis("s::b")
        vm.create_new_axis("s::c")
        vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.5
        vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.5, 0.3
        vm.axes[2].top_ratio, vm.axes[2].height_ratio = 0.8, 0.2

        vm.remove_signal("s::b")

        assert len(vm.axes) == 2
        assert vm.axes[0].height_ratio == pytest.approx(0.5 / 0.7)
        assert vm.axes[1].height_ratio == pytest.approx(0.2 / 0.7)
        assert vm.axes[0].top_ratio == pytest.approx(0.0)
        assert vm.axes[1].top_ratio == pytest.approx(0.5 / 0.7)

    def test_remove_one_signal_from_multisignal_axis_keeps_heights(self) -> None:
        """Removing one of two signals on an axis leaves it (no prune); heights stay."""
        from valisync.core.session import Session

        vm = GraphPanelVM(Session())
        vm.add_signal_to_axis("s::a", 0)
        vm.add_signal_to_axis("s::a2", 0)  # second signal on the same axis 0
        vm.create_new_axis("s::b")
        vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.6
        vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.6, 0.4

        vm.remove_signal("s::a2")  # axis 0 still holds s::a → not pruned

        assert len(vm.axes) == 2
        assert vm.axes[0].height_ratio == pytest.approx(0.6)
        assert vm.axes[1].height_ratio == pytest.approx(0.4)

    def test_prune_missing_signals_drops_signals_absent_from_session(
        self, qtbot: QtBot, tmp_path: Path
    ) -> None:
        """prune_missing_signals removes plotted entries no longer in the Session."""
        session, _ = _loaded_session(tmp_path, n_signals=2)
        keys = _keys(session)
        vm = GraphPanelVM(session)
        vm.create_new_axis(keys[0])
        vm.create_new_axis(keys[1])

        # Simulate keys[0] no longer existing in the Session.
        remaining = [s for s in session.signals() if s.name != keys[0]]
        session.signals = lambda: remaining  # type: ignore[method-assign]
        vm.prune_missing_signals()

        plotted = [p["signal_key"] for p in vm.inspect()["plotted_signals"]]
        assert plotted == [keys[1]]
        assert len(vm.axes) == 1  # axes reconciled


# ─── Task 0.1: column_count ──────────────────────────────────────────────────


def test_default_column_count_is_two() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    assert vm.column_count == 2


def test_set_column_count_notifies_and_clamps() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    seen: list[str] = []
    vm.subscribe(lambda tag: seen.append(tag))
    vm.set_column_count(3)
    assert vm.column_count == 3 and "axes" in seen
    vm.set_column_count(0)  # invalid
    assert vm.column_count == 1  # clamped to >=1


# ─── Task 0.2: helpers (reused by later wave tasks) ──────────────────────────


def _inject_signal(vm: GraphPanelVM, key: str) -> None:
    """Add ONE signal as ONE axis to *vm*.

    Uses the existing placeholder axis 0 for the very first signal so it fills
    the whole panel; subsequent calls each append a new axis.
    """
    if not vm.inspect()["plotted_signals"]:
        vm.add_signal_to_axis(key, 0)
    else:
        vm.create_new_axis(key)


def _inject_two_signals(vm: GraphPanelVM) -> None:
    """Produce exactly 2 stacked axes on *vm* using synthetic keys."""
    vm.add_signal_to_axis("sig::a", 0)
    vm.create_new_axis("sig::b")


def _col(vm: GraphPanelVM, col: int) -> list[YAxisVM]:
    """Return axes in *col*, sorted top-to-bottom by top_ratio."""
    return sorted([a for a in vm.axes if a.column == col], key=lambda a: a.top_ratio)


# ─── Task 0.2: column-aware _normalize_axes ──────────────────────────────────


def test_normalize_splits_height_per_column() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_two_signals(vm)  # 2 axes, both col=0 by default

    # Move both axes to column 1 (inner column)
    vm.axes[0].column, vm.axes[1].column = 1, 1
    vm._relayout_columns()
    assert [(a.top_ratio, a.height_ratio) for a in _col(vm, 1)] == [
        (0.0, 0.5),
        (0.5, 0.5),
    ]

    # Move axis 1 to column 0 — each axis is now alone in its own column
    vm.axes[1].column = 0
    vm._relayout_columns()
    assert all(a.height_ratio == 1.0 for a in vm.axes)


def test_relayout_columns_preserves_proportions() -> None:
    """preserve_heights=True renormalizes a sub-unity column to 1.0, keeping ratios."""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    vm.add_signal_to_axis("s::a", 0)
    vm.create_new_axis("s::c")  # 2 axes in inner column
    # Heights summing to 0.7 simulate the post-prune state (a 0.3 axis removed).
    vm.axes[0].top_ratio, vm.axes[0].height_ratio = 0.0, 0.5
    vm.axes[1].top_ratio, vm.axes[1].height_ratio = 0.8, 0.2

    vm._relayout_columns(preserve_heights=True)

    assert vm.axes[0].height_ratio == pytest.approx(0.5 / 0.7)
    assert vm.axes[1].height_ratio == pytest.approx(0.2 / 0.7)
    assert vm.axes[0].top_ratio == pytest.approx(0.0)
    assert vm.axes[1].top_ratio == pytest.approx(0.5 / 0.7)


def test_relayout_total_zero_falls_back_to_equal() -> None:
    """A degenerate zero-sum column falls back to an equal split (no ZeroDivision)."""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    vm.add_signal_to_axis("s::a", 0)
    vm.create_new_axis("s::b")
    vm.axes[0].height_ratio = 0.0
    vm.axes[1].height_ratio = 0.0

    vm._relayout_columns(preserve_heights=True)

    assert vm.axes[0].height_ratio == pytest.approx(0.5)
    assert vm.axes[1].height_ratio == pytest.approx(0.5)


# ─── Task 0.3: create_new_axis targets inner column (rule A) ─────────────────


def test_new_axis_lands_in_inner_column() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")  # first signal — reuses placeholder axis 0
    assert vm.axes[0].column == vm.column_count - 1  # placeholder must be in inner col
    vm.create_new_axis("sig::b")
    assert all(a.column == vm.column_count - 1 for a in vm.axes)  # both inner, stacked
    assert [a.height_ratio for a in vm.axes] == [0.5, 0.5]


def test_third_new_axis_lands_at_bottom() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")  # a (first signal, placeholder axis)
    vm.create_new_axis("sig::b")  # b
    vm.create_new_axis("sig::c")  # c
    inner = vm.column_count - 1
    col = _col(vm, inner)  # axes in inner column, top->bottom
    assert col[0] is vm.axes[0]  # a stays at the top
    assert col[1] is vm.axes[1]  # b in the middle
    assert col[2] is vm.axes[2]  # c (newest) at the BOTTOM
    assert [a.height_ratio for a in col] == [1 / 3, 1 / 3, 1 / 3]


# ─── Task 0.4: overwrite_axis + Ctrl-add semantics ───────────────────────────


def _signals_on_axis(vm: GraphPanelVM, axis_index: int) -> list[str]:
    """Return signal keys plotted on *axis_index*, in insertion order."""
    return [
        p["signal_key"]
        for p in vm.inspect()["plotted_signals"]
        if p["axis_index"] == axis_index
    ]


def test_overwrite_axis_replaces_signals_on_that_axis() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")  # axis 0 has 'a'
    vm.overwrite_axis("sig::b", 0)
    assert _signals_on_axis(vm, 0) == ["sig::b"]  # 'a' replaced


def test_add_signal_to_axis_keeps_both() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")
    vm.add_signal_to_axis("sig::b", 0)
    assert set(_signals_on_axis(vm, 0)) == {"sig::a", "sig::b"}


# ─── Task 0.5: move_axis_to_column ───────────────────────────────────────────


def test_move_axis_to_column_revacates_source() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")
    vm.create_new_axis("sig::b")
    vm.move_axis_to_column(0, 0)  # move first inner axis to outer column 0
    assert vm.axes[0].column == 0 and vm.axes[0].height_ratio == 1.0  # alone in col 0
    assert _col(vm, vm.column_count - 1)[0].height_ratio == 1.0  # remaining fills inner


def test_move_axis_inserts_at_given_vertical_position() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")
    vm.create_new_axis("sig::b")
    inner = vm.column_count - 1
    a, b = vm.axes[0], vm.axes[1]  # both inner; a above b
    vm.move_axis_to_column(
        1, inner, position=0
    )  # move b to the TOP of the inner column
    col = _col(vm, inner)  # column members, top->bottom
    assert col[0] is b and col[1] is a  # b is now the topmost
    assert col[0].top_ratio < col[1].top_ratio  # equal-split, b on top


# ─── Task 0.6: inspect() exposes column_count ────────────────────────────────


def test_inspect_exposes_column_count_and_axis_fields() -> None:
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    snap = vm.inspect()
    assert snap["column_count"] == 2
    for ax in snap["axes"]:
        assert "column" in ax and "top_ratio" in ax and "height_ratio" in ax


# ─── Task 1.1: render N axis columns + plot as the last grid column ───────────


def _mounted_panel(
    qtbot: QtBot, columns: int = 2
) -> tuple[GraphPanelView, GraphPanelVM]:
    """Mount a GraphPanelView over a fresh VM with *columns* layout columns.

    Uses an empty Session — the Task 1.1 assertions read only the view's grid
    structure (axis_columns / plot_grid_column), not real signal data.
    """
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    vm.set_column_count(columns)
    view = cast(GraphPanelView, _make_view(qtbot, vm))
    return view, vm


def test_view_builds_one_sublayout_per_column(qtbot: QtBot) -> None:
    """Each occupied column gets its own axis sub-layout; the plot sits last.

    With two axes split across columns 0 (outer) and 1 (inner) of a 2-column
    layout, the view exposes one axis sub-layout per occupied column and the
    plot ViewBox container occupies root column ``column_count``.
    """
    view, vm = _mounted_panel(qtbot, columns=2)
    _inject_signal(vm, "sig::a")
    vm.move_axis_to_column(0, 0)  # axis in OUTER col 0
    vm.create_new_axis("sig::b")  # axis in INNER col 1
    view.refresh()

    assert sorted(view.axis_columns()) == [0, 1]
    assert view.plot_grid_column() == 2


# ─── Task 1.2: column-scoped, vertical-order resize_axis + within-column handles ─


def test_resize_axis_is_scoped_to_one_column() -> None:
    """A column-scoped resize moves the divider between that column's
    vertically-adjacent pair and never touches another column's axes.

    A lone OUTER-column axis makes VM-index order diverge from the inner
    column's vertical order, so a VM-index-based resize would be wrong; the
    column-scoped path must resize the inner pair only.
    """
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")
    vm.move_axis_to_column(0, 0)  # lone axis in OUTER col 0
    vm.create_new_axis("sig::b")
    vm.create_new_axis("sig::c")  # two axes in INNER col
    inner = vm.column_count - 1
    top, bot = _col(vm, inner)  # inner pair, top->bottom
    outer = _col(vm, 0)[0]  # lone outer axis (1.0)
    vm.resize_axis(0, 0.1, column=inner)  # grow inner top axis by 0.1
    assert top.height_ratio + bot.height_ratio == pytest.approx(1.0)  # column fills
    assert top.height_ratio > bot.height_ratio  # top grew
    assert outer.height_ratio == pytest.approx(1.0)  # OTHER column untouched


def test_dragging_divider_is_column_scoped(qtbot: QtBot, tmp_path: Path) -> None:
    """Handler-path: dragging a within-column divider resizes that column's
    vertically-adjacent pair (top grows, bottom shrinks) — not a VM-index pair.

    A lone OUTER-column axis makes VM-index order diverge from the inner
    column's vertical order, so a VM-index-based resize would touch the wrong
    (cross-column) axes; the column-scoped divider must not.

    Honest-layering note: this drives ``RegionDividerItem.mouseDragEvent``
    directly (the divider-style handler path), NOT a full ``sendEvent`` Layer B;
    the real OS drag path is confirmed by Layer C / manual per
    ``docs/gui-testing-layers.md``.
    """
    session, _ = _loaded_session(tmp_path, n_signals=3)
    keys = _keys(session)
    vm = GraphPanelVM(session)
    view = _make_view(qtbot, vm)
    vm.add_signal_to_axis(keys[0], 0)
    vm.move_axis_to_column(0, 0)  # lone axis in OUTER col 0
    vm.create_new_axis(keys[1])  # INNER col, top
    vm.create_new_axis(keys[2])  # INNER col, bottom
    inner = vm.column_count - 1

    view.resize(1000, 700)
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(lambda: view._view_boxes[0].geometry().height() > 100, timeout=2000)

    top, bot = _col(vm, inner)
    before_top, before_bot = top.height_ratio, bot.height_ratio
    assert before_top == pytest.approx(0.5) and before_bot == pytest.approx(0.5)
    outer_before = _col(vm, 0)[0].height_ratio

    divider = view._dividers[0]  # within-column divider for the inner pair
    view_h = divider.getViewWidget().height()
    assert view_h > 0
    dy = 0.15 * view_h  # drag down by 15% of the view height
    divider.mouseDragEvent(_DragEvent(QPointF(0, 0), QPointF(0, 0), start=True))
    divider.mouseDragEvent(_DragEvent(QPointF(0, dy), QPointF(0, 0)))
    divider.mouseDragEvent(_DragEvent(QPointF(0, dy), QPointF(0, dy), finish=True))

    delta = dy / view_h  # == 0.15
    top, bot = _col(vm, inner)  # re-read (top_ratio may have shifted)
    assert top.height_ratio == pytest.approx(before_top + delta, abs=1e-3)
    assert bot.height_ratio == pytest.approx(before_bot - delta, abs=1e-3)
    assert top.height_ratio > bot.height_ratio  # top region grew
    assert sum(a.height_ratio for a in _col(vm, inner)) == pytest.approx(1.0, abs=1e-6)
    # The OTHER column's lone axis is untouched (no cross-column resize).
    assert _col(vm, 0)[0].height_ratio == pytest.approx(outer_before)


# ─── Task 1.4a: axis-move drag/drop → move_axis_to_column (testable core) ─────


def test_axis_drop_target_resolves_column_and_position(qtbot: QtBot) -> None:
    """``_axis_drop_target`` maps a widget pos -> (column, insertion position)."""
    view, vm = _mounted_panel(qtbot, columns=2)
    _inject_signal(vm, "sig::a")
    vm.move_axis_to_column(0, 0)  # one axis in OUTER col 0
    vm.create_new_axis("sig::b")
    vm.create_new_axis("sig::c")  # two axes in INNER col 1
    view.refresh()

    # Deterministic geometry: plot rect spans y in [0, 300].
    view._plot_rect_in_widget = lambda: QRectF(200.0, 0.0, 600.0, 300.0)  # type: ignore
    w = _Y_AXIS_FIXED_WIDTH
    # x in column 0's band, y near the very top -> (0, 0) (lone column -> position 0).
    assert view._axis_drop_target(QPointF(w * 0.5, 5.0)) == (0, 0)
    # x in inner column 1's band, y near the TOP boundary -> (1, 0).
    assert view._axis_drop_target(QPointF(w * 1.5, 2.0)) == (1, 0)
    # x in inner column, y near the BOTTOM -> (1, 2) (n+1 boundaries: 0,1,2 for 2 axes).
    assert view._axis_drop_target(QPointF(w * 1.5, 299.0)) == (1, 2)


def test_axis_move_drop_calls_move_to_target(qtbot: QtBot) -> None:
    """A dropped axis-index mime relocates that axis via ``move_axis_to_column``."""
    view, vm = _mounted_panel(qtbot, columns=2)
    _inject_signal(vm, "sig::a")
    vm.create_new_axis("sig::b")  # both inner (col 1)
    view.refresh()
    moved = vm.axes[1]  # move axis index 1 (b)
    view._axis_drop_target = lambda pos: (0, 0)  # type: ignore  # force target
    mime = encode_axis_index(1)  # hold local (a GC'd mime mid-send is a known pitfall)
    event = QDropEvent(
        QPointF(10.0, 10.0),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.dropEvent(event)  # handler-path (sendEvent can't route drops to this view)
    assert moved.column == 0  # b moved to outer column 0
    assert _col(vm, 0)[0] is moved  # and it's there


# ─── Task 1.4b: axis-move drop-feedback visuals ──────────────────────────────


def test_axis_move_feedback_insertion_line_at_boundary(qtbot: QtBot) -> None:
    """_update_axis_move_feedback shows an insertion line at the nearest boundary.

    Handler-path: drives _update_axis_move_feedback directly with a stubbed
    _plot_rect_in_widget so geometry is deterministic.  Placement (not pixel
    appearance) is asserted; pixel appearance is Layer C / manual.
    """
    view, vm = _mounted_panel(qtbot, columns=2)
    _inject_signal(vm, "sig::a")
    vm.create_new_axis("sig::b")  # two axes in inner col 1
    view.refresh()

    view._plot_rect_in_widget = lambda: QRectF(200.0, 0.0, 600.0, 300.0)  # type: ignore
    W = _Y_AXIS_FIXED_WIDTH
    # inner col (col 1): x = W*1.5; y = 2.0 → nearest boundary is the top (y ≈ 0.0)
    view._update_axis_move_feedback(0, QPointF(W * 1.5, 2.0))

    # Insertion line is visible and sits at the top boundary y
    assert view._axis_move_line.isVisible()
    assert abs(view._axis_move_line_y() - 0.0) < 1.0
    # Source axis 0 is dimmed
    assert view._y_axes[0].opacity() < 1.0

    view._clear_axis_move_feedback()
    assert not view._axis_move_line.isVisible()
    assert view._y_axes[0].opacity() == 1.0


def test_axis_move_feedback_empty_column_highlights(qtbot: QtBot) -> None:
    """_update_axis_move_feedback highlights the whole column when it is empty.

    Handler-path with stubbed geometry; pixel appearance is Layer C / manual.
    """
    view, vm = _mounted_panel(qtbot, columns=2)
    _inject_signal(vm, "sig::a")  # one axis in inner col 1; col 0 is empty
    view.refresh()

    view._plot_rect_in_widget = lambda: QRectF(200.0, 0.0, 600.0, 300.0)  # type: ignore
    W = _Y_AXIS_FIXED_WIDTH
    # col 0 (empty): x = W*0.5 = 36
    view._update_axis_move_feedback(0, QPointF(W * 0.5, 150.0))

    assert view._axis_move_highlight.isVisible()
    assert not view._axis_move_line.isVisible()


# ─── Task 2.1: column-count plumbing ─────────────────────────────────────────


def test_view_renders_configured_column_count(qtbot: QtBot) -> None:
    """set_column_count propagates end-to-end to the view's grid structure.

    Verifies that the public setter triggers a view re-render that:
      * reserves ``column_count`` fixed-width axis columns in the root grid, and
      * places the plot ViewBox in the next column (``column_count``).

    After set_column_count(3) the axis stays in column 1 (its original inner
    column when count=2). _normalize_axes only migrates the *placeholder* to
    ``column_count-1`` when there are no signals; with a signal present the
    column assignment is unchanged.
    """
    view, vm = _mounted_panel(qtbot, columns=2)
    _inject_signal(vm, "sig::a")
    view.refresh()
    assert view.plot_grid_column() == 2  # plot in root col 2 => cols 0,1 reserved
    vm.set_column_count(3)  # public setter notifies "axes" -> view refreshes
    assert view.plot_grid_column() == 3  # now plot in col 3 => cols 0,1,2 reserved
    # _normalize_axes does not migrate existing axes to the new inner column
    # (column_count-1=2) when signals are present; the axis stays at column 1.
    assert view.axis_columns() == [1]


# ─── Final-review fixes: column-aware _axis_index_at + column clamping ─────────


def test_axis_index_at_respects_column(qtbot: QtBot) -> None:
    """``_axis_index_at`` resolves the cursor's COLUMN before the vertical band.

    Regression: after an axis is moved to the outer column it often spans the
    full height (band ``[0, 1]``), so a column-blind scan matched EVERY ``y_rel``
    and a drop/zoom in the INNER column wrongly targeted the outer-column axis.
    The column must be resolved from ``pos.x()`` first, then only same-column
    axes are considered in the vertical-band test.
    """
    view, vm = _mounted_panel(qtbot, columns=2)
    _inject_signal(vm, "sig::a")  # axis 0 -> inner col 1
    vm.move_axis_to_column(0, 0)  # move axis 0 to OUTER col 0 (full height)
    vm.create_new_axis("sig::b")  # axis 1 -> inner col 1 (full height)
    view.refresh()

    # Deterministic geometry: plot rect spans y in [0, 300].
    view._plot_rect_in_widget = lambda: QRectF(200.0, 0.0, 600.0, 300.0)  # type: ignore
    w = _Y_AXIS_FIXED_WIDTH
    # A point in the INNER column band (x in [W, 2W)) at mid-height must resolve
    # to the inner axis (index 1), NOT the column-0 full-height axis (index 0).
    assert view._axis_index_at(QPointF(w * 1.5, 150.0)) == 1
    # A point in the OUTER column band resolves to axis 0.
    assert view._axis_index_at(QPointF(w * 0.5, 150.0)) == 0


def test_set_column_count_clamps_existing_axis_columns() -> None:
    """Reducing column_count clamps any axis stranded in an out-of-range column.

    Otherwise ``_reconcile_axes`` would ``addLayout`` the stranded axis into the
    plot's own root grid cell (column == column_count), overlapping the layout.
    """
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")  # axis in inner col 1 (count == 2)
    vm.set_column_count(1)  # reduce to a single column
    assert all(a.column == 0 for a in vm.axes)  # clamped into the only column


def test_move_axis_to_column_out_of_range_index_is_noop() -> None:
    """A stale/out-of-range axis index is a no-op, not an ``IndexError``."""
    from valisync.core.session import Session

    vm = GraphPanelVM(Session())
    _inject_signal(vm, "sig::a")
    vm.move_axis_to_column(99, 0)  # stale drag index must not raise
    assert len(vm.axes) == 1
    assert vm.axes[0].column == vm.column_count - 1  # state unchanged
